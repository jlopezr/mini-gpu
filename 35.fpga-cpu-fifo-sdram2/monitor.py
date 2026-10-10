#!/usr/bin/env python3
"""Command-line client for the minimal FPGA UART monitor."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import serial

# 1 Mbaud: el dominio de CPU corre a 100 MHz y el divisor es 100. Ese divisor
# es múltiplo de 4, que es lo que necesita la recepción de `uart.v` (muestrea
# a 4x con DIVISOR/4, y la división es entera), y 1 Mbaud es además 3 MHz / 3,
# que el generador del FTDI produce exacto. Ver el comentario de `top.v`.
BAUDRATE = 1_000_000
DEFAULT_TIMEOUT = 1.0
MAX_ADDRESS = 0x01FF_FFFF
# Espacio MMIO v2 (1.isa/mmio.md §2): bloques de 64 KiB, separados por
# megabytes. Ya no es una pagina de 4 KiB con dieciseis ranuras de 256 B.
#
#   0x80000000  SYSTEM            identificacion, memoria, version
#   0x80100000  SERIAL
#   0x80200000  VIDEO
#   0x81010000  CPU PERFORMANCE
#   0x80020000  SDRAM PHASE (experimental, solo prototipo 35)
#
# Las constantes salen del mapa generado y NO se escriben aqui: eran una
# gemela del decodificador Verilog, y §20 existe para quitarla. El mapa lo
# genera `tools/generate-mmio` desde `1.isa/mmio_map.vh`.
#
# De momento se importa el mapa de MMIO v2
# porque `video_registers.v` todavia tiene CTRL en +0x18. Cuando se migren los
# offsets, esta linea pasa a `mmio_map`.
#
# El `sys.path` tiene que estar puesto ANTES, asi que el insert de la raiz del
# repo sube aqui desde mas abajo, donde estaba para `tools/serial_ports.py`.
_RAIZ = Path(__file__).resolve().parents[1]
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from tools.mmio_map import (  # noqa: E402
    MMIO_SYSTEM_BASE, MMIO_SERIAL_BASE, MMIO_VIDEO_BASE, MMIO_CPU_PERF_BASE,
    MMIO_BLOCK_SIZE,
)

MMIO_BASE = MMIO_SYSTEM_BASE
SERIAL_BASE = MMIO_SERIAL_BASE
MMIO_LIMIT = MMIO_CPU_PERF_BASE + MMIO_BLOCK_SIZE - 1
# Espacio físico unificado: la CPU y el monitor ven las mismas direcciones.
ARCHITECTURAL_REGIONS = (
    (0x0000_0000, 0x0200_0000),
)
# Las ventanas MMIO que el host acepta, una por bloque. Son GEMELAS de los
# parametros WINDOW0..3 del `monitor #(...)` de top.v, y las dos tienen que
# decir lo mismo: anadir una ventana en el RTL sin anadirla aqui hace que el
# host rechace el comando antes de que llegue al decodificador, y el sintoma
# es un NACK que parece un bitstream viejo.
#
# §16.4 quiere que esta lista se DERIVE de DEVICES en vez de mantenerse a
# mano. Todavia no se hace; lo que si esta hecho es que las direcciones salgan
# del mapa generado, asi que mover un bloque ya no son dos ediciones.
#
# Cada ventana es el bloque ENTERO de 64 KiB, no el subconjunto de registros
# que existen hoy. Un subconjunto seria una tercera gemela que mantener, y ya
# se quedo atras una vez: estuvo en 0x8000_0018 con un comentario que decia
# "llegara a 0x8000_001c cuando la fase 3.5 anada VIDEO_CTRL", la fase lo
# anadio y la constante se quedo. Quien rechaza un offset sin registro es el
# decodificador, que es el unico que lo sabe.
#
# Solo filtra bloques y transferencias (validate_block / validate_transfer);
# los accesos byte a byte no pasan por aqui, que es por lo que esta lista pudo
# estar vacia sin que se notara.
# Los números van LITERALES y no derivados del mapa, aunque el mapa esté
# importado justo arriba: `tools/prototype_report.py` lee esta asignación del
# TEXTO del fichero, sin importar el módulo, y un `tuple(... for ...)` lo deja
# ciego. Lo vigila `test_monitor_protocol.test_cada_carpeta_declara_su_propio_mapa`.
#
# Que estén escritos a mano no los deja sin comprobar: hay un test que los
# contrasta contra el mapa generado y otro contra los WINDOWn_* del top.v.
MONITOR_REGIONS = (
    (0x8000_0000, 0x8001_0000),     # SYSTEM
    (0x8002_0000, 0x8003_0000),     # SDRAM PHASE, experimental local
    (0x8010_0000, 0x8011_0000),     # SERIAL
    (0x8020_0000, 0x8021_0000),     # VIDEO
    (0x8101_0000, 0x8102_0000),     # CPU PERFORMANCE
    (0x8060_0000, 0x8061_0000),     # INPUT
)
MEMORY_REGIONS = ARCHITECTURAL_REGIONS + MONITOR_REGIONS

# `tools` en el camino ANTES de importar de ahi. El insert ya existia
# mas abajo, para tools/serial_ports.py, pero ahora hace falta aqui
# arriba; es idempotente.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# El protocolo del monitor vive UNA vez, en tools/monitor_protocol.py:
# veinte de los veintiun metodos de este cliente eran identicos en las
# diez carpetas con juego de comandos. Lo que se queda aqui es lo que
# describe a ESTE prototipo: su baudrate, su mapa y los comandos que su
# hardware tiene de verdad -- por eso los mixins se componen y no se
# heredan todos.
from tools import monitor_protocol as protocolo  # noqa: E402
from tools.monitor_protocol import (  # noqa: E402,F401
    MAX_BLOCK_SIZE,
    CommandRejected,
    CpuStatus,
    MonitorError,
    Version,
    parse_integer,
    InputMixin,
    SerialMixin,
    PerfMixin,
)

# El cuerpo de una clase no puede LEER un global que ademas asigna, asi
# que estos alias son lo que permite que el atributo de clase y la
# constante del modulo -que es la que se lee desde fuera- se llamen
# igual.
_REGIONES = MEMORY_REGIONS


# SDRAM PHASE (experimental, solo prototipo 35): el bloque MMIO que mueve la fase de
# `sdram_clk` en la PLL (`phase_mmio.v`). La posicion arranca en 0 tras programar
# la FPGA y solo avanza, dando la vuelta a las 48 posiciones (208,3 ps cada una).
PHASE_CTRL = 0x8002_0000
PHASE_STATUS = 0x8002_0004
PHASES = 48
VERSION_JSON = Path(__file__).with_name("version.json")


class PhaseMixin:
    """Fase del reloj de la SDRAM, y el valor por defecto de `version.json`."""

    def phase_status(self) -> dict:
        value = self.read_word(PHASE_STATUS)
        return {"busy": bool(value & 1), "err": bool(value & 2),
                "locked": bool(value & 4), "init_done": bool(value & 8),
                "pos": (value >> 8) & 0x3F}

    def phase_move(self, steps: int, timeout: float = 2.0) -> dict:
        """Avanza `steps` posiciones (1..48) y espera a que el controlador acabe."""
        if not 1 <= steps <= PHASES:
            raise MonitorError("steps debe estar entre 1 y 48")
        before = self.phase_status()
        expected_pos = (before["pos"] + steps) % PHASES
        self.write_word(PHASE_CTRL, 1 | (steps << 8))
        deadline = time.monotonic() + timeout
        saw_busy = False
        while time.monotonic() < deadline:
            current = self.phase_status()
            saw_busy |= current["busy"]
            # Un movimiento dura microsegundos y una consulta por UART tarda mucho
            # mas: es normal no llegar a observar BUSY=1. POS es Gray en el CDC y
            # solo cambia al completar cada paso, asi que tambien sirve de ack.
            if (saw_busy or current["pos"] == expected_pos) and not current["busy"]:
                if current["err"] or not current["locked"] or not current["init_done"]:
                    raise MonitorError(f"fallo al mover la fase: {current}")
                return current
            time.sleep(0.002)
        raise MonitorError("el cambio de fase no termino")

    def set_sdram_phase(self, target: int) -> dict:
        """Deja la fase en `target` (0..47). Si ya esta ahi, no escribe nada."""
        if not 0 <= target < PHASES:
            raise MonitorError(f"la fase debe estar entre 0 y {PHASES - 1}")
        current = self.phase_status()
        if current["busy"] or current["err"] or not current["locked"]:
            raise MonitorError(f"estado de fase no valido: {current}")
        delta = (target - current["pos"]) % PHASES
        return self.phase_move(delta) if delta else current

    def apply_version_settings(self, path: Path = VERSION_JSON) -> int | None:
        """Pone la fase que fija `version.json` (`"sdram_phase"`), si la hay.

        Tras programar la FPGA la fase vuelve a 0, que en esta placa no es buena.
        El valor sale de un barrido (`phase_sweep.py`): el centro de la ventana de
        fases que pasan. Devuelve la fase aplicada, o None si no hay ninguna.
        """
        import json

        phase = json.loads(path.read_text(encoding="utf-8")).get("sdram_phase")
        if phase is None:
            return None
        self.set_sdram_phase(phase)
        return phase


class MonitorClient(PhaseMixin, InputMixin, SerialMixin, PerfMixin, protocolo.MonitorClient):
    MEMORY_REGIONS = _REGIONES


def validate_block(address: int, length: int) -> None:
    protocolo.validate_block(address, length, MEMORY_REGIONS)


def validate_transfer(address: int, length: int) -> None:
    protocolo.validate_transfer(address, length, MEMORY_REGIONS)


def interactive_uart(client: MonitorClient, poll: float = 0.005) -> None:
    """Terminal sobre el puerto serie de la CPU. Se sale con Ctrl+].

    Esto NO es el codec: es la parte que no se puede probar sin una persona
    delante. Todo lo que sí se puede probar --empaquetar, control de flujo,
    reensamblar-- vive en `send_bytes`/`recv_bytes`/`send_all`, que no saben
    nada de teclados. Por eso estan separados.

    La lectura de teclado usa `msvcrt`, no `select()`: esto es Windows. En otros
    sistemas cae a una lectura por lineas, que sirve para probar aunque no de
    caracter a caracter.
    """
    try:
        import msvcrt
    except ImportError:
        msvcrt = None

    print("Consola sobre el puerto serie de la CPU. Ctrl+] para salir.")
    if msvcrt is None:
        print("  (sin msvcrt: se envia por lineas, no caracter a caracter)")

    salida = sys.stdout
    while True:
        # Primero lo que venga de la placa, para que el eco se vea antes de
        # que el usuario escriba lo siguiente.
        datos = client.recv_bytes(255)
        if datos:
            salida.write(datos.decode("latin-1"))
            salida.flush()

        if msvcrt is not None:
            enviados = bytearray()
            while msvcrt.kbhit():
                tecla = msvcrt.getwch()
                if tecla == "\x1d":       # Ctrl+]
                    print()
                    return
                # Enter llega como \r y casi todo programa espera \n.
                enviados += ("\n" if tecla == "\r" else tecla).encode("latin-1")
            if enviados:
                client.send_all(bytes(enviados))
            elif not datos:
                time.sleep(poll)
        else:
            linea = sys.stdin.readline()
            if not linea:
                return
            client.send_all(linea.encode("latin-1"))


def interactive_input(client: MonitorClient, home: bool = True) -> None:
    """Teclado y raton del PC hacia el INPUT de la placa. F12 sale.

    Abre una ventana que SOLO captura (la imagen la ensena el HDMI de la placa:
    leer el framebuffer por UART costaria ~1,5 s por frame) y manda cada report
    como eventos con INPUT_EVENTS. Todo lo que se puede probar sin una persona
    delante --que eventos salen, el control de flujo, las liberaciones al
    salir-- vive en `tools/input_adapter.py`; esto es solo la ventana.
    """
    from tools import input_adapter

    ventana = input_adapter.WindowSource()
    print("Teclado y raton del PC -> INPUT de la placa. F12 en la ventana para salir.")
    ultimo = [0.0]

    def estado(adaptador) -> None:
        ahora = time.monotonic()
        if ahora - ultimo[0] < 0.5:
            return
        ultimo[0] = ahora
        huecos = "?" if adaptador.free is None else adaptador.free
        ventana.panel(
            "Capturando teclado y raton hacia la placa.\n\n"
            f"huecos libres en la FIFO: {huecos}\n"
            f"eventos esperando: {len(adaptador.queue)}\n\n"
            "F12 para salir.")

    try:
        input_adapter.run_session(client, ventana, status=estado, home=home)
    except CommandRejected:
        raise MonitorError(
            "La placa rechazo INPUT_PRESENCE: este bitstream no tiene el bloque "
            "INPUT (hace falta monitor 5.x, o sea la 30 con INPUT).") from None
    finally:
        ventana.close()
    print("INPUT desconectado: teclas soltadas y presencia a cero.")

# Deteccion del puerto y listado: en tools/serial_ports.py.
#
# Estaba COPIADA palabra por palabra en los trece monitores, y coger el primer
# puerto del sistema no vale: con la placa desenchufada ese primero puede ser
# el puerto serie de la placa base o un enlace Bluetooth, y entonces el fallo
# aparece tarde y disfrazado de timeout. Se filtra por fabricante (FTDI).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.serial_ports import (  # noqa: E402
    FTDI_VENDOR_ID,
    PortError,
    available_ports,
    detect_port,
    ftdi_ports,
)


# Las unicas opciones que se comen el token siguiente. Lo necesita
# `_extrae_texto_de_send` para saber cual es el primer POSICIONAL.
_OPCIONES_CON_VALOR = ("--port", "--serial-timeout")


def _extrae_texto_de_send(argv: list[str]) -> tuple[list[str], str | None]:
    """Saca de `argv` el texto de `send` cuando empieza por `-`.

    `send` es el unico comando cuyo argumento es texto ARBITRARIO, y argparse
    lee como opcion cualquier cosa que empiece por guion: `send -y` moria con
    el usage en vez de mandarle dos caracteres al programa que esta corriendo
    en la CPU. Y mandar `-y` a un programa que pregunta es justo lo que uno
    quiere hacer con `send`.

    El escape `--` de argparse ya valia, pero exige acordarse y ademas es
    GLOBAL: en `send -- -y --port COM6` el puerto tambien se vuelve texto, asi
    que arregla un caso rompiendo el otro. Por eso el texto se saca a mano
    antes de parsear y se devuelve a su sitio despues; `--port`/`--serial-timeout`
    siguen funcionando vayan delante o detras.

    Si el usuario escribe su propio `--`, no se toca nada: ha dicho
    explicitamente donde acaban las opciones.
    """
    if "--" in argv:
        return argv, None
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in _OPCIONES_CON_VALOR:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        # Primer posicional: el comando.
        if token == "send" and index + 1 < len(argv) and argv[index + 1].startswith("-"):
            resto = argv[:index + 1] + argv[index + 2:]
            return resto, argv[index + 1]
        return argv, None
    return argv, None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    argv = list(sys.argv[1:] if argv is None else argv)
    argv, texto_de_send = _extrae_texto_de_send(argv)
    parser = argparse.ArgumentParser(
        description="Communicate with the minimal FPGA UART monitor.",
        epilog="Para mandar texto que empieza por guion sin que argparse lo "
               "lea como opcion: `send -y` ya funciona, y `send -- -y` es el "
               "escape estandar si el texto es algo mas raro.",
    )
    parser.add_argument(
        "command",
        choices=(
            "ping",
            "get-version",
            "write-byte",
            "read-byte",
            "read-word",
            "write-word",
            "write-block",
            "read-block",
            "verify",
            "memory-test",
            "phase-status",
            "phase-step",
            "phase-set",
            "run",
            "halt",
            "step",
            "status",
            "read-register",
            "reset",
            "perf",
            "uart",
            "send",
            "input",
            "screen",
        ),
    )
    parser.add_argument("arguments", nargs="*", metavar="ARG")
    parser.add_argument(
        "--port",
        default=None,
        help="Puerto serie de la ULX3S (por defecto: el unico FTDI conectado)",
    )
    parser.add_argument(
        "--serial-timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Response timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--script",
        default=None,
        metavar="GUION",
        help="input: ejecuta un guion (tools/board_script.py) en vez de abrir la ventana",
    )
    parser.add_argument(
        "--settle-ms",
        type=int,
        default=150,
        help="input --script: tiempo que se deja a la aplicacion para repintar antes "
             "de mirar la pantalla (por defecto 150)",
    )
    parser.add_argument(
        "--keep-pointer",
        action="store_true",
        help="input: no llevar el puntero de la placa al centro al conectar "
             "(por defecto se resincroniza con la ventana)",
    )
    args = parser.parse_args(argv)
    if texto_de_send is not None:
        args.arguments.insert(0, texto_de_send)
    return args


def parse_address(value: str) -> int:
    """Dirección para CUALQUIER comando: SDRAM o la ventana de registros.

    Los registros de vídeo viven en `MMIO_BASE` y no son memoria, pero eso no
    los hace exclusivos del acceso byte a byte, que es lo que esto daba por
    supuesto mientras se llamaba `parse_byte_address` y sólo lo usaban
    `read-byte`/`write-byte`. El RTL atiende una palabra y un bloque sobre el
    MMIO igual que sobre la SDRAM --en el adaptador la rama `is_mmio` va antes
    de la comprobación de `cpu_halted`-- y `MONITOR_REGIONS` abre la página
    entera justamente para que `validate_block` los deje pasar. El resto de
    comandos usaba un tope de 32 MiB que sólo describe la SDRAM, así que
    `read-word 0x80000300` --el contador de ciclos que `perf` sí lee-- se
    rechazaba en el cliente y la única forma de verlo a mano era juntar cuatro
    `read-byte`: exactamente la lectura desgarrada que `read_word` existe para
    evitar.

    Al contrario que la memoria, estos registros responden también con la CPU
    en marcha, que es lo que permite leer el contador de frames o mover el
    framebuffer mientras un programa dibuja.
    """
    try:
        result = int(value, 0)
    except ValueError as error:
        raise MonitorError(f"Invalid address: {value}") from error

    if 0 <= result <= MAX_ADDRESS or MMIO_BASE <= result <= MMIO_LIMIT:
        return result

    raise MonitorError(
        f"Address must be between 0 and 0x{MAX_ADDRESS:x}, "
        f"or inside the MMIO register window "
        f"0x{MMIO_BASE:08x}-0x{MMIO_LIMIT:08x}"
    )


def test_pattern(number: int, address: int, length: int) -> bytes:
    """Build one deterministic SDRAM test pattern for a physical byte range."""
    if number == 0:
        return bytes(length)
    if number == 1:
        return bytes((0xFF,)) * length
    if number == 2:
        return bytes(((address + offset) ^ 0xA5) & 0xFF for offset in range(length))
    return bytes(0xAA if (address + offset) & 1 else 0x55 for offset in range(length))


# Los comandos que tocan la memoria del sistema. Todos empiezan por una
# dirección y ninguno de los demás la tiene, que es lo que permite hacer la
# comprobación de `require_halted` en UN sitio (ver `main`) en vez de
# repetirla en las siete ramas del despacho.
MEMORY_COMMANDS = frozenset({
    "write-byte",
    "read-byte",
    "read-word",
    "write-word",
    "write-block",
    "read-block",
    "verify",
    "memory-test",
})


def require_halted(client: MonitorClient, command: str, address: int) -> None:
    """La SDRAM sólo se deja tocar por el monitor con el núcleo parado.

    No es sólo cosa de las escrituras: en el adaptador, la rama de SDRAM
    contesta `mem_error` si `!cpu_halted` sin mirar si la petición era de
    lectura (`monitor_mem_adapter_128.v`, el `else if (!cpu_halted ||
    !init_done || !address_in_sdram)`). Así que `read-block` y `verify`
    fallaban igual de mal que `write-block`, y el cliente traducía el `ff` a
    "The FPGA rejected the command": verdad, pero no dice lo único que hay que
    hacer.

    Se PREGUNTA en vez de parar por las bravas. Un `halt` automático mataría
    la demo que estuviera corriendo, y quien lanza un test destructivo quiere
    enterarse de eso antes y no después.

    El MMIO queda fuera a propósito, y sale antes de hablar con la placa: esos
    registros responden en marcha --es justo cuando tiene gracia mirarlos-- y
    así `capture-frames`, que lee los registros de vídeo de cuatro en cuatro
    bytes, no paga una consulta de estado por cada byte.
    """
    if MMIO_BASE <= address <= MMIO_LIMIT:
        return
    if not client.get_status().halted:
        raise MonitorError(
            f"{command} necesita la CPU parada: el monitor no puede leer ni "
            f"escribir memoria con el núcleo en marcha. Ejecuta "
            f"`monitor.py halt` (o `reset`) antes."
        )


def memory_test(client: MonitorClient, address: int, length: int) -> None:
    """Destructively write and verify four patterns over an SDRAM range."""
    validate_transfer(address, length)
    names = ("00", "ff", "address XOR a5", "55/aa")
    for pattern_number, name in enumerate(names):
        print(f"Pattern {pattern_number + 1}/4: {name} (write)", flush=True)
        for offset in range(0, length, MAX_BLOCK_SIZE):
            size = min(MAX_BLOCK_SIZE, length - offset)
            client.write_block(
                address + offset,
                test_pattern(pattern_number, address + offset, size),
            )

        print(f"Pattern {pattern_number + 1}/4: {name} (verify)", flush=True)
        for offset in range(0, length, MAX_BLOCK_SIZE):
            size = min(MAX_BLOCK_SIZE, length - offset)
            expected = test_pattern(pattern_number, address + offset, size)
            actual = client.read_block(address + offset, size)
            if actual != expected:
                mismatch = next(
                    index
                    for index, (left, right) in enumerate(zip(actual, expected))
                    if left != right
                )
                absolute = address + offset + mismatch
                raise MonitorError(
                    f"Memory test failed at 0x{absolute:08x}: "
                    f"memory=0x{actual[mismatch]:02x}, "
                    f"expected=0x{expected[mismatch]:02x}"
                )

    print(f"SDRAM test passed: {length} byte(s) from 0x{address:08x}")


def main() -> int:
    args = parse_args()

    try:
        expected_arguments = {
            "ping": 0,
            "get-version": 0,
            "write-byte": 2,
            "read-byte": 1,
            "read-word": 1,
            "write-word": 2,
            "write-block": 2,
            "read-block": 3,
            "verify": 2,
            "memory-test": 2,
            "phase-status": 0,
            "phase-step": 1,
            "phase-set": 1,
            "run": 0,
            "halt": 0,
            "step": 0,
            "status": 0,
            "read-register": 1,
            "reset": 0,
            "perf": 0,
            "uart": 0,
            "send": 1,
            "input": 0,
            "screen": 0,
        }
        # `perf` admite un argumento opcional: la ventana en segundos.
        if args.command == "perf" and len(args.arguments) <= 1:
            pass
        # `screen` admite las filas que se quieren ver; sin ninguna, todas.
        elif args.command == "screen":
            pass
        elif len(args.arguments) != expected_arguments[args.command]:
            raise MonitorError(
                f"{args.command} expects {expected_arguments[args.command]} argument(s)"
            )

        with serial.Serial(
            port=args.port if args.port is not None else detect_port(),
            baudrate=BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=args.serial_timeout,
            write_timeout=args.serial_timeout,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        ) as connection:
            client = MonitorClient(connection)

            # La fase de `version.json` se aplica al abrir, salvo que el comando
            # sea justo de manejar la fase (un barrido no puede pelearse con ella).
            if not args.command.startswith("phase-"):
                applied = client.apply_version_settings()
                if applied is not None:
                    print(f"SDRAM phase: {applied} (version.json)", file=sys.stderr)

            # Antes de nada, y una sola vez: si el comando toca memoria y la
            # CPU sigue corriendo, decirlo con esas palabras en vez de dejar
            # que la placa conteste `ff` mas abajo.
            if args.command in MEMORY_COMMANDS:
                require_halted(
                    client, args.command, parse_address(args.arguments[0]))

            if args.command == "ping":
                client.ping()
                print("PONG: FPGA monitor is responding")
            elif args.command == "get-version":
                version = client.get_version()
                print(f"FPGA monitor version: {version}")
            elif args.command == "write-byte":
                address = parse_address(args.arguments[0])
                value = parse_integer(args.arguments[1], 0xFF, "byte value")
                client.write_byte(address, value)
                print(f"Written 0x{value:02x} at address 0x{address:04x}")
            elif args.command == "read-byte":
                address = parse_address(args.arguments[0])
                value = client.read_byte(address)
                print(f"Address 0x{address:04x}: 0x{value:02x}")
            elif args.command == "read-word":
                address = parse_address(args.arguments[0])
                value = client.read_word(address)
                print(f"Address 0x{address:08x}: 0x{value:08x}")
            elif args.command == "write-word":
                address = parse_address(args.arguments[0])
                value = parse_integer(args.arguments[1], 0xFFFF_FFFF, "word value")
                client.write_word(address, value)
                print(f"Written 0x{value:08x} at address 0x{address:08x}")
            elif args.command == "write-block":
                address = parse_address(args.arguments[0])
                source = Path(args.arguments[1])
                data = source.read_bytes()
                client.write_memory(address, data)
                print(f"Written {len(data)} byte(s) at address 0x{address:04x}")
            elif args.command == "read-block":
                address = parse_address(args.arguments[0])
                length = parse_integer(args.arguments[1], MAX_ADDRESS + 1, "length")
                destination = Path(args.arguments[2])
                data = client.read_memory(address, length)
                destination.write_bytes(data)
                print(
                    f"Read {len(data)} byte(s) from address 0x{address:04x} "
                    f"into {destination}"
                )
            elif args.command == "verify":
                address = parse_address(args.arguments[0])
                source = Path(args.arguments[1])
                expected = source.read_bytes()
                actual = client.read_memory(address, len(expected))
                if actual != expected:
                    mismatch = next(
                        index
                        for index, (left, right) in enumerate(zip(actual, expected))
                        if left != right
                    )
                    raise MonitorError(
                        f"Verification failed at address 0x{address + mismatch:04x}: "
                        f"memory=0x{actual[mismatch]:02x}, file=0x{expected[mismatch]:02x}"
                    )
                print(f"Verified {len(expected)} byte(s) at address 0x{address:04x}")
            elif args.command == "memory-test":
                address = parse_address(args.arguments[0])
                length = parse_integer(args.arguments[1], MAX_ADDRESS + 1, "length")
                memory_test(client, address, length)
            elif args.command == "phase-status":
                status = client.read_word(0x8002_0004)
                print(
                    f"busy={bool(status & 1)} err={bool(status & 2)} "
                    f"locked={bool(status & 4)} init_done={bool(status & 8)} "
                    f"pos={(status >> 8) & 0x3f} "
                    f"delay_ps={((status >> 8) & 0x3f) * 625 / 3:.1f}"
                )
            elif args.command == "phase-step":
                steps = parse_integer(args.arguments[0], 48, "steps")
                if steps == 0:
                    raise MonitorError("steps debe estar entre 1 y 48")
                client.write_word(0x8002_0000, 1 | (steps << 8))
                status = client.read_word(0x8002_0004)
                if status & 2:
                    raise MonitorError("el controlador de fase rechazo la peticion")
                print(f"Cambio solicitado: {steps} paso(s) de retraso")
            elif args.command == "phase-set":
                target = parse_integer(args.arguments[0], PHASES - 1, "phase")
                status = client.set_sdram_phase(target)
                print(f"Fase SDRAM: {status['pos']} "
                      f"({status['pos'] * 625 / 3:.1f} ps de retraso)")
            elif args.command == "run":
                client.run_cpu()
                print("CPU started")
            elif args.command == "halt":
                client.halt_cpu()
                print("CPU halt requested")
            elif args.command == "step":
                client.step_cpu()
                print("CPU step requested")
            elif args.command == "status":
                status = client.get_status()
                print(
                    f"CPU halted={status.halted} error={status.error} "
                    f"error_code=0x{status.error_code:02x} pc=0x{status.pc:08x}"
                )
            elif args.command == "perf":
                # Los ocho contadores de CPU PERFORMANCE (mmio.md §13.2), leidos
                # con el bloque congelado para que sean de un mismo instante
                # aunque la CPU siga corriendo. Los da la vuelta a 2^32: ver el
                # aviso si alguno lo ha hecho.
                from tools.perf_counters import difference, format_report, read_counters

                # `perf` da los valores acumulados; `perf N` espera N segundos y
                # da lo contado en ESA ventana, que es lo que sirve con un
                # programa que lleva minutos corriendo (los contadores dan la
                # vuelta a los 53 s y sus valores absolutos ya no dicen nada).
                ventana = None
                if args.arguments:
                    try:
                        ventana = float(args.arguments[0])
                    except ValueError as error:
                        raise MonitorError(
                            f"perf espera segundos, no {args.arguments[0]!r}") from error
                    if ventana <= 0:
                        raise MonitorError("perf espera una ventana de mas de 0 segundos")
                aviso = None
                con_esperas = True
                try:
                    contadores = read_counters(
                        client.read_word, client.write_word, stalls=True)
                except MonitorError:
                    # Un bitstream anterior a los contadores de espera: leer
                    # una ranura sin contador da error de MMIO, no ceros.
                    con_esperas = False
                    contadores = read_counters(client.read_word, client.write_word)
                    aviso = ("  (esta placa solo tiene CYCLES y RETIRED: falta el "
                             "bitstream con los contadores de espera)")
                if ventana is not None:
                    time.sleep(ventana)
                    contadores = difference(contadores, read_counters(
                        client.read_word, client.write_word, stalls=con_esperas))
                    print(f"ventana de {ventana:g} s")
                print("\n".join(format_report(contadores)))
                if aviso:
                    print(aviso)
            elif args.command == "uart":
                interactive_uart(client)
            elif args.command == "input" and args.script is not None:
                from tools import board_script

                try:
                    pasos = board_script.load(args.script)
                    comprobaciones = board_script.run(
                        client, pasos, home=not args.keep_pointer,
                        settle=args.settle_ms / 1000)
                except (board_script.ScriptError, board_script.ScriptFailure,
                        OSError) as error:
                    raise MonitorError(str(error)) from None
                print(f"Guion terminado: {comprobaciones} comprobacion(es) correctas.")
            elif args.command == "input":
                interactive_input(client, home=not args.keep_pointer)
            elif args.command == "screen":
                # La pantalla de texto como texto: sin ventana ni captura. Sin
                # argumentos, las 30 filas (~5 s: la RAM de texto se lee palabra
                # a palabra); con numeros, solo esas filas.
                from tools import board_input

                filas = [parse_integer(texto, board_input.ROWS - 1, "fila")
                         for texto in args.arguments] or None
                captura = board_input.read_screen(client, filas)
                for numero in sorted(captura.cells):
                    print(f"{numero:2d}|{captura.row(numero)}")
            elif args.command == "send":
                # Manda una cadena y ensena lo que conteste, sin terminal. Es
                # la forma de probar un programa interactivo desde un script.
                client.send_all(args.arguments[0].encode("latin-1"))
                time.sleep(0.2)
                respuesta = client.recv_bytes(255)
                print(respuesta.decode("latin-1"), end="")
            elif args.command == "read-register":
                register = parse_integer(args.arguments[0], 31, "register number")
                value = client.read_register(register)
                print(f"R{register} = 0x{value:08x} ({value})")
            else:
                client.reset_cpu()
                print("CPU reset: PC, registers and error state cleared")

    except (MonitorError, PortError, OSError, serial.SerialException) as error:
        print(f"Error: {error}", file=sys.stderr)
        print(available_ports(), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
