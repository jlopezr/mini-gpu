"""Perifericos funcionales compartidos por CPU, GPU y GPU por ciclos.

El reloj de video es sintetico; no simula contienda ni temporizacion fisica.
HALT_AT y serie estan disponibles en los tres modelos, aunque no en toda FPGA.
"""

def u32(value):
    return value & 0xFFFFFFFF


class VideoDevice:
    """Vídeo funcional común, en un slot de 256 bytes.

    Modela framebuffer, swaps, HALT_AT y VIDEO_CTRL. Un frame transcurre cada
    `frame_instructions` instrucciones CPU o de warp, no por lane ni por ciclo
    del pipeline. No modela contienda, desgarro ni underflow (siempre cero).
    Las bases se alinean a 4 bytes. Para portabilidad a FPGA GPU, usar 16.
    HALT_AT y serie son capacidades del simulador aunque falten en la FPGA GPU.
    """

    BASE = 0x8020_0000
    SIZE = 0x1_0000                 # bloque MMIO v2 de 64 KiB

    # Disposición de MMIO v2 (§9). CTRL vuelve a +0x00, `FRAME_COUNT` tiene
    # registro propio en vez de vivir en los bits altos de STATUS, y aparecen
    # HALT_TARGET y VIDEO_TX. §17 exige que el simulador implemente el MISMO
    # contrato que el RTL, así que esta tabla y `video_registers.v` dicen lo
    # mismo registro por registro.
    VIDEO_CTRL = 0x00
    FB_FRONT = 0x04
    FB_BACK = 0x08
    SWAP = 0x0C
    STATUS = 0x10
    FRAME_COUNT = 0x14
    SWAP_COUNT = 0x18
    HALT_AT = 0x1C
    HALT_TARGET = 0x20
    VIDEO_TX = 0x24

    # Bits de HALT_TARGET (§9.6).
    HALT_TARGET_CPU = 1 << 0
    HALT_TARGET_GPU = 1 << 1

    # Alineamiento exigido a FB_FRONT y FB_BACK (§9.2): dieciséis bytes, y
    # desalinear es ERROR, no se trunca. El truncamiento silencioso era
    # distinto en cada familia --4 bytes en CPU y 16 en GPU-- así que el mismo
    # programa dibujaba bien en una placa y torcido en la otra.
    FB_ALIGN = 16

    MODE_BLANK = 0
    MODE_PATTERN = 1
    MODE_SCANOUT = 2

    # Las dos bases arrancan a cero, igual que `video_registers.v` desde la fase
    # 3.5. Cero no es una dirección útil --es el principio de la memoria, donde
    # está el propio programa-- y eso es justamente lo que se quiere modelar:
    # el framebuffer es una decisión del programa, no algo que herede del
    # encendido. Quien quiera dibujar escribe FB_FRONT y FB_BACK.
    #
    # Poner aquí la dirección cómoda sería peor que no modelarlo: un programa
    # que la heredase pasaría en el simulador y fallaría en la placa.
    # Consola de texto (30.fpga-cpu-console, `video_registers.v`). Solo existe
    # con `console=True`: sin ella esas direcciones siguen siendo «registro
    # inexistente», que es lo que hace el resto de prototipos.
    CONFIG = 0x40
    PALETTE_BASE = 0x1000           # 256 palabras
    PALETTE_WORDS = 256
    TEXT_BASE = 0x6000              # 80x30 celdas, una palabra cada una
    TEXT_COLUMNS = 80
    TEXT_ROWS = 30
    TEXT_WORDS = TEXT_COLUMNS * TEXT_ROWS
    CONFIG_TEXT_ENABLE = 1 << 2
    SWAP_REQUEST = 1 << 0           # con consola, SWAP son dos bits (RTL)
    STATE_COMMIT = 1 << 1

    def __init__(self, fb_front: int = 0, fb_back: int = 0,
                 frame_instructions: int = 1000, console: bool = False):
        if frame_instructions <= 0:
            raise ValueError("frame_instructions debe ser positivo")
        self.console = console
        self.config_shadow = 0
        self.config_active = 0
        self.state_commit_pending = False
        self.palette = [0] * self.PALETTE_WORDS
        self.text_ram = [0] * self.TEXT_WORDS
        self.fb_front = fb_front & ~(self.FB_ALIGN - 1)
        self.fb_back = fb_back & ~(self.FB_ALIGN - 1)
        self.swap_pending = False
        self.frame_count = 0
        self.swap_count = 0
        self.halt_at = 0
        self.halt_armed = False
        # Intercambios completados desde que se armo la alarma. Interno, como
        # en el RTL: no es un registro.
        self.halt_swaps = 0
        self.halt_target = 0
        #: Que bit de HALT_TARGET detiene a ESTE nucleo: el de CPU por defecto, y
        #: el simulador de GPU lo pone a `HALT_TARGET_GPU` al colgarselo. El otro
        #: bit se acepta y no hace nada (§9.6): el registro significa lo mismo
        #: en las dos familias y un binario compartido no tiene que saber donde
        #: corre.
        self.halt_owner = self.HALT_TARGET_CPU
        self.video_tx = 0
        # Alto durante un solo `tick`, cuando se completa el intercambio N
        # desde que se armo HALT_AT.
        self.halt_request = False
        #: Parada del ARNES: «para tras N intercambios contados desde el
        #: reset». No es un registro y no se puede leer desde el programa.
        #: `run_until: {swap: N}` de los casos es una condicion de observacion
        #: --capturar el frame N-- y no pasa por HALT_AT ni por HALT_TARGET, que
        #: son del contrato: el programa podria verlos y cambiarlos.
        self.stop_after_swaps = 0
        # PATTERN tras el reset, igual que el RTL. Aquí no gobierna nada --no
        # hay barrido que leer la memoria-- pero el REGISTRO tiene que existir y
        # comportarse igual: un programa que lo escriba y lo relea debe obtener
        # lo mismo en las dos partes, o el simulador deja de servir para
        # desarrollar el programa antes de subirlo.
        self.video_mode = self.MODE_PATTERN
        self.frame_instructions = frame_instructions
        self._since_frame = 0

    #: Los diez registros de §9, en orden. Lo que no esta aqui es ERROR, no
    #: cero: §4.3 cambio el fallo silencioso por uno que se ve.
    REGISTROS = (VIDEO_CTRL, FB_FRONT, FB_BACK, SWAP, STATUS, FRAME_COUNT,
                 SWAP_COUNT, HALT_AT, HALT_TARGET, VIDEO_TX)

    def _console_index(self, offset: int):
        """(memoria, índice) si `offset` cae en paleta o texto; si no, None."""
        if not self.console:
            return None
        if self.PALETTE_BASE <= offset < self.PALETTE_BASE + 4 * self.PALETTE_WORDS:
            return self.palette, (offset - self.PALETTE_BASE) >> 2
        if self.TEXT_BASE <= offset < self.TEXT_BASE + 4 * self.TEXT_WORDS:
            return self.text_ram, (offset - self.TEXT_BASE) >> 2
        return None

    def validate(self, offset: int, writing: bool = False) -> None:
        if offset in self.REGISTROS:
            return
        if self.console and (offset == self.CONFIG
                             or self._console_index(offset) is not None):
            return
        raise RuntimeError(f"registro MMIO inexistente: {self.BASE + offset:#010x}")

    # Los códigos 0x01-0x1F de la fuente son glifos (triángulos de scrollbar,
    # flechas...), no controles. Python los decodifica como control y
    # `str.splitlines` partiría la fila en 0x1C-0x1E.
    _LOW_GLYPHS = "☺☻♥♦♣♠•◘○◙♂♀♪♫☼►◄↕‼¶§▬↨↑↓→←∟↔▲▼"

    def text_lines(self):
        """El contenido de la consola como 30 cadenas de 80 caracteres (CP437)."""
        def glyph(cell):
            code = cell & 0xFF
            if code == 0:
                return " "
            if code < 0x20:
                return self._LOW_GLYPHS[code - 1]
            return bytes([code]).decode("cp437")

        return ["".join(glyph(cell) for cell in
                        self.text_ram[row * self.TEXT_COLUMNS:(row + 1) * self.TEXT_COLUMNS])
                for row in range(self.TEXT_ROWS)]

    def contains(self, address: int) -> bool:
        return self.BASE <= address < self.BASE + self.SIZE

    def tick(self) -> None:
        """Avanza el reloj de frames sintético una instrucción CPU/de warp.

        El intercambio se aplica en la frontera de frame, igual que en el
        hardware: allí es la primera petición de línea de un frame, que es el
        único instante en el que no queda nada del frame anterior por leer ni se
        ha leído nada del siguiente.
        """
        self.halt_request = False
        self._since_frame += 1
        if self._since_frame < self.frame_instructions:
            return

        self._since_frame = 0
        # FRAME_COUNT: frames de video, independiente de la alarma.
        self.frame_count = u32(self.frame_count + 1)
        # VIDEO_TX cuenta frames emitidos mientras el nucleo corre; aqui
        # `tick` solo se llama mientras corre, asi que es el mismo contador.
        self.video_tx = u32(self.video_tx + 1)

        if self.state_commit_pending:
            self.config_active = self.config_shadow
            self.state_commit_pending = False

        if self.swap_pending:
            self.fb_front, self.fb_back = self.fb_back, self.fb_front
            self.swap_pending = False
            self.swap_count = u32(self.swap_count + 1)
            self.halt_swaps = u32(self.halt_swaps + 1)
            # La alarma cuenta INTERCAMBIOS completados desde que se armo
            # (§9.6), y se compara con `>=` --decision congelada 17--: armarla
            # con un valor ya rebasado para en el intercambio siguiente en vez
            # de no parar nunca.
            if self.halt_armed and self.halt_swaps >= self.halt_at:
                # HALT_TARGET decide A QUIEN se para. Sin el bit puesto la
                # alarma se consume igual y no para a nadie: es lo que hace el
                # RTL, y es la trampa de la que hay que acordarse al portar un
                # programa viejo --HALT_TARGET arranca a cero, asi que escribir
                # solo HALT_AT, como bastaba en v1, ya no detiene nada--.
                self.halt_request = bool(self.halt_target & self.halt_owner)
                self.halt_armed = False
            if self.stop_after_swaps and self.swap_count >= self.stop_after_swaps:
                self.halt_request = True

    def read(self, offset: int) -> int:
        self.validate(offset)
        indexed = self._console_index(offset)
        if indexed is not None:
            memory, index = indexed
            return memory[index]
        if offset == self.CONFIG:
            return self.config_shadow
        if offset == self.FB_FRONT:
            return self.fb_front
        if offset == self.FB_BACK:
            return self.fb_back
        if offset == self.SWAP:
            if self.console:
                return (int(self.state_commit_pending) << 1) | int(self.swap_pending)
            return 1 if self.swap_pending else 0
        if offset == self.STATUS:
            # bit 0 underflow (siempre cero aqui), bit 1 intercambio pendiente.
            # Los frames YA NO viven aqui: tienen registro propio en v2, que es
            # lo que les devuelve los 32 bits --en v1 cabian 16 y daban la
            # vuelta a los 65536 frames, unos 18 minutos de video--.
            if self.console:
                return (int(self.state_commit_pending) << 3) | (
                    2 if self.swap_pending else 0)
            return 2 if self.swap_pending else 0
        if offset == self.FRAME_COUNT:
            return self.frame_count
        if offset == self.SWAP_COUNT:
            return self.swap_count
        if offset == self.HALT_AT:
            return self.halt_at
        if offset == self.HALT_TARGET:
            return self.halt_target
        if offset == self.VIDEO_TX:
            return self.video_tx
        if offset == self.VIDEO_CTRL:
            return self.video_mode
        return 0

    def write(self, offset: int, value: int) -> None:
        self.validate(offset, writing=True)
        indexed = self._console_index(offset)
        if indexed is not None:
            memory, index = indexed
            memory[index] = u32(value)
            return
        if offset == self.CONFIG:
            # Bits 31:3 reservados: error y la escritura no surte efecto.
            if value >> 3:
                raise RuntimeError(f"CONFIG con bits reservados: 0x{value:08X}")
            self.config_shadow = value
            return
        if self.console and offset == self.SWAP:
            # Con consola, SWAP es FRAME_COMMIT: bit 0 intercambio y bit 1
            # STATE_COMMIT. Bits reservados o petición con la anterior aún
            # pendiente son error y no tienen efecto, como en el RTL.
            if (value >> 2
                    or (value & self.SWAP_REQUEST and self.swap_pending)
                    or (value & self.STATE_COMMIT and self.state_commit_pending)):
                raise RuntimeError(f"FRAME_COMMIT inválido: 0x{value:08X}")
            if value & self.SWAP_REQUEST:
                self.swap_pending = True
            if value & self.STATE_COMMIT:
                self.state_commit_pending = True
            return
        if offset in (self.FB_FRONT, self.FB_BACK):
            # Desalinear es ERROR, no se trunca (§9.2). El truncamiento
            # silencioso dibujaba bien en una familia y torcido en la otra.
            if value & (self.FB_ALIGN - 1):
                raise RuntimeError(
                    f"base de framebuffer no alineada a {self.FB_ALIGN} "
                    f"bytes: 0x{value:08X}")
            if offset == self.FB_FRONT:
                self.fb_front = value
            else:
                self.fb_back = value
        elif offset == self.SWAP:
            # Cualquier escritura pide intercambio.
            self.swap_pending = True
        elif offset == self.STATUS:
            pass            # escribir el bit 0 borra el underflow, que aquí
                            # nunca está puesto: no hay nada que borrar
        elif offset == self.HALT_AT:
            # Armar la alarma pone el origen de la cuenta aquí: HALT_AT es
            # «para dentro de N intercambios», no «para en el intercambio
            # número N desde el encendido». Aquí daría igual —cada ejecución
            # construye un dispositivo nuevo— pero en la placa no: con la
            # cuenta libre, un programa solo podría usarla una vez por
            # arranque. La cuenta es `halt_swaps`, interna: armar NO toca
            # FRAME_COUNT ni SWAP_COUNT, igual que `video_registers.v`.
            self.halt_at = value
            self.halt_swaps = 0
            self.halt_armed = value != 0
        elif offset == self.HALT_TARGET:
            self.halt_target = value & (self.HALT_TARGET_CPU
                                        | self.HALT_TARGET_GPU)
        elif offset == self.VIDEO_CTRL:
            # El modo 3 esta reservado (§9.1) y escribirlo es error, no un
            # modo raro: el RTL no lo decodifica y el scanout se quedaria sin
            # fuente, que es peor de diagnosticar que un fallo en la tienda.
            if value & 0b11 == 3:
                raise RuntimeError("modo de video reservado: 3")
            self.video_mode = value & 0b11
        # FRAME_COUNT, SWAP_COUNT y VIDEO_TX son de solo lectura.


class SerialDevice:
    """Puerto serie de la CPU, en 0x80000200. Dos colas y nada mas.

    Modela `19.fpga-cpu-hdmi-ls/serial_port.v`, incluidas las dos cosas que
    tienen truco:

      - **Leer DATA saca de la cola.** Es el unico registro del repositorio con
        efecto secundario, y por eso existe `PEEK`, que devuelve lo mismo sin
        sacarlo.
      - **Nada bloquea.** Leer DATA con la cola vacia devuelve cero, y escribir
        con la de salida llena pierde el byte. En la FPGA no puede ser de otra
        forma: un acceso MMIO se resuelve en un ciclo, asi que un dispositivo
        que esperase colgaria el bus. Un programa que no mire `STATUS` antes se
        comporta igual aqui que en la placa, que es justo lo que se quiere de
        un simulador.

    Lo que aqui NO hay es tiempo: en la placa los bytes llegan cuando el PC
    manda un paquete, y aqui estan desde el principio. Para un programa de
    peticion-respuesta da igual --lee lo que hay, contesta, vuelve a esperar--
    y por eso el flujo de bytes se puede comparar con el de la placa. Para un
    programa que dependa de CUANDO llega cada byte, no.
    """

    BASE = 0x8010_0000
    SIZE = 0x1_0000             # bloque MMIO v2 de 64 KiB

    DATA = 0x00
    STATUS = 0x04
    PEEK = 0x08

    def __init__(self, depth: int = 64, stdin: bytes = b""):
        if depth <= 0:
            raise ValueError("depth debe ser positivo")
        self.depth = depth
        self.rx = bytearray(stdin)   # lo que el PC ha mandado
        self.tx = bytearray()                       # lo que la CPU ha escrito
        self.overrun = False
        self.host_output = None
        self._host_ticks = 0

    def tick(self):
        if self.host_output is not None:
            self._host_ticks += 1
            if self._host_ticks >= 32:
                self._host_ticks = 0
                self.host_output.extend(self.pop(255))

    def attach_host(self):
        """El host vacía TX cada 32 instrucciones; conserva la observación de FIFO."""
        self.host_output = bytearray()
        self._host_ticks = 0

    def output(self):
        return bytes(self.host_output or b"") + bytes(self.tx)

    def validate(self, offset: int, writing: bool = False) -> None:
        if offset not in (self.DATA, self.STATUS, self.PEEK):
            raise RuntimeError(f"registro MMIO inexistente: {self.BASE + offset:#010x}")

    def contains(self, address: int) -> bool:
        return self.BASE <= address < self.BASE + self.SIZE

    def push(self, data: bytes) -> int:
        """Mete lo que quepa, como hace SEND_BYTES; devuelve cuantos entraron."""
        free = max(0, self.depth - len(self.rx))
        accepted = min(free, len(data))
        self.rx += data[:accepted]
        if accepted < len(data):
            self.overrun = True
        return accepted

    def pop(self, maximum: int = 255) -> bytes:
        """Saca de la cola de salida, como hace RECV_BYTES."""
        count = min(maximum, len(self.tx))
        out = bytes(self.tx[:count])
        del self.tx[:count]
        return out

    def read(self, offset: int) -> int:
        self.validate(offset)
        if offset == self.DATA:
            if not self.rx:
                return 0
            value = self.rx[0]
            del self.rx[:1]
            return value
        if offset == self.PEEK:
            return self.rx[0] if self.rx else 0
        if offset == self.STATUS:
            rx_count = min(len(self.rx), 0xFF)
            tx_free = max(0, self.depth - len(self.tx))
            return (int(self.overrun) << 16) | (tx_free << 8) | rx_count
        return 0

    def write(self, offset: int, value: int) -> None:
        self.validate(offset, writing=True)
        if offset == self.DATA:
            if len(self.tx) < self.depth:
                self.tx.append(value & 0xFF)
            return
        if offset == self.STATUS and (value >> 16) & 1:
            self.overrun = False


