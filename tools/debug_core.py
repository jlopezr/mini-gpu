"""El depurador de verdad: estado, comandos y ejecución controlada.

Aquí no se pinta nada. `DebugSession` sabe parar, avanzar, mirar y escribir, y
devuelve texto; la TUI (`tools/debug_tui.py`) solo coloca ese texto en paneles.
Esa separación es deliberada por dos motivos: se puede probar el depurador
entero con `unittest` sin abrir un terminal, y la misma sesión sirve para el
modo línea (`--no-tui`), para la TUI y, cuando exista `BoardTarget`, para la
placa sin cambiar una coma.
"""
from __future__ import annotations

import bisect
import threading
from dataclasses import dataclass

from tools.debug_source import SourceMap
from tools.debug_target import (
    CAPS_FREE_RUN, CAPS_RESET, CAPS_RESET_GPU, CAPS_WRITE_MEMORY,
    CAPS_WRITE_PC, CAPS_WRITE_REGISTER, POLL_BREAKPOINT, POLL_ERROR,
    POLL_HALT, POLL_STALLED, DebugTarget, LaneGrid, TargetError, WarpRow,
)

# Por qué se paró la ejecución. La TUI los traduce a un color y un mensaje.
# Los cuatro primeros son lo que contesta `DebugTarget.poll`.
STOP_BREAKPOINT = POLL_BREAKPOINT
STOP_HALT = POLL_HALT
STOP_ERROR = POLL_ERROR
STOP_STALLED = POLL_STALLED
STOP_WATCH = "watch"
STOP_LIMIT = "limit"
STOP_STEPPED = "stepped"
STOP_SWAP = "swap"
STOP_INTERRUPTED = "interrupted"
STOP_FINISHED = "finished"
STOP_ALREADY = "already-halted"

ERROR_NAMES = {
    0x00: "sin error",
    0x01: "opcode invalido",
    0x02: "acceso a memoria",
    0x03: "trap explicito",
    0x04: "division por cero",
    0x05: "encoding invalido",
    # Solo los da la GPU.
    0x06: "SIMT: salto divergente sin SSY o pilas llenas",
    0x07: "barrera invalida",
}

# Opcodes que dejan dirección de retorno: los que `over` salta entero.
_CALL_OPCODES = {0x2C, 0x2D}  # JAL, JALR

DEFAULT_RUN_LIMIT = 10_000_000


class CommandError(ValueError):
    """Comando mal escrito o imposible. Se enseña, no se propaga."""


@dataclass(frozen=True)
class StopReason:
    kind: str
    executed: int
    #: Si es mejor que el texto genérico del motivo, lo que se enseña.
    detail: str = ""

    @property
    def stopped_by_user_mark(self) -> bool:
        return self.kind == STOP_BREAKPOINT


@dataclass(frozen=True)
class ListingRow:
    address: int
    word: int | None
    text: str
    is_pc: bool
    has_breakpoint: bool
    labels: tuple[str, ...]
    #: Los dos indicadores de un sistema CPU+GPU: el PC de la CPU y el del warp
    #: con foco. `is_pc` sigue siendo el del núcleo con foco.
    cpu_pc: bool = False
    gpu_pc: bool = False


@dataclass
class Watch:
    """Una región de memoria vigilada y el valor con que se vio por última vez."""

    address: int
    length: int
    value: bytes
    #: Valor antes del último cambio y quién lo hizo (vacío si no se sabe: un
    #: `step` explícito no recoge autor).
    previous: bytes | None = None
    writer: str = ""
    #: Número del comando en que cambió por última vez.
    changed_at: int = -1


@dataclass(frozen=True)
class WatchRow:
    """Lo que enseña el panel de watches de la TUI."""

    address: int
    label: str | None
    length: int
    value: bytes
    previous: bytes | None
    writer: str
    #: Cambió con el último comando.
    changed: bool


class DebugSession:
    """Una máquina parada, un mapa de fuente y un puñado de comandos."""

    def __init__(self, target: DebugTarget, source: SourceMap | None = None,
                 run_limit: int | None = None) -> None:
        self.target = target
        self.source = source or SourceMap()
        self.run_limit = run_limit
        # `finish` y `frame` necesitan una red de seguridad porque no aceptan
        # límite explícito. `run`, en cambio, es ilimitado salvo `run N` o
        # `--run-limit N`.
        self.operation_limit = run_limit or DEFAULT_RUN_LIMIT
        self.breakpoints: set[int] = set()
        self.watches: dict[int, Watch] = {}
        # Cuenta de comandos: dice si un watch cambió «con el último».
        self._serial = 0
        # Lo que dijo el último `watch` que paró una ejecución.
        self._watch_lines: list[str] = []
        self._interrupt = threading.Event()
        self.warnings: list[str] = []
        self.quit = False
        # La ventana de framebuffer se crea al primer `fb`: quien no la use no
        # paga ni un proceso ni el import.
        self._video = None
        # Ventana de pantalla (`fb screen`): la del simulador, con consola y con
        # teclado y ratón hacia INPUT. Es distinta de la de `_video`, que enseña
        # los buffers crudos y sirve también en la placa.
        self._screen = None
        self.screen_font = None
        # Ventana del panel de memoria; los comandos `mem`/`x` la mueven.
        self.memory_address = 0
        self.memory_length = 128
        self._known_pcs = sorted(self.source.addresses)

    # -- ejecución ---------------------------------------------------------

    def step(self, count: int = 1) -> StopReason:
        """`count` instrucciones, parando antes si la máquina se para.

        Un breakpoint NO corta un `step` explícito: si se pide avanzar tres
        instrucciones es porque se quiere ver esas tres, y pararse en una marca
        puesta para el `run` sería una sorpresa.
        """
        executed = 0
        for _ in range(max(1, count)):
            state = self.target.state()
            if state.halted:
                if executed == 0:
                    return StopReason(STOP_ALREADY, 0,
                                      self.target.idle_reason() or "")
                return StopReason(self._halt_kind(), executed)
            self.target.step()
            executed += 1
        state = self.target.state()
        if state.halted:
            return StopReason(self._halt_kind(), executed)
        return StopReason(STOP_STEPPED, executed)

    def resume(self, stop_at: set[int] | None = None,
               max_instructions: int | None = None) -> StopReason:
        """Ejecuta hasta una marca, hasta que pare, o hasta agotar el límite.

        La marca del PC actual se ignora: si no, `run` con un breakpoint justo
        donde estamos parados no avanzaría nunca.
        """
        marks = set(self.breakpoints)
        if stop_at:
            marks |= stop_at
        budget = max_instructions

        if not self.target.can_run():
            return StopReason(STOP_ALREADY, 0)

        if not marks and not self.watches and self.target.supports(
                CAPS_FREE_RUN):
            # Sin ninguna marca no hay nada que comprobar entre instrucción e
            # instrucción, así que se deja correr al objetivo. El contador sale
            # de su propio estado, no de contar pasos aquí.
            before = self.target.state().instructions
            progress = (self.refresh_video_title
                        if self._video is not None and self._video.open
                        else None)
            self.target.free_run(on_progress=progress)
            after = self.target.state()
            if self._interrupt.is_set():
                return StopReason(
                    STOP_INTERRUPTED,
                    max(0, after.instructions - before))
            return StopReason(self._halt_kind(),
                              max(0, after.instructions - before))

        executed = 0
        watch_swaps = (self._video is not None and self._video.open
                       and self._video.auto)
        last_swap = self.target.video_swap_count() if watch_swaps else None
        while budget is None or executed < budget:
            if self._interrupt.is_set():
                return StopReason(STOP_INTERRUPTED, executed)
            self.target.advance()
            executed += 1
            self.refresh_video_title()
            if watch_swaps:
                current_swap = self.target.video_swap_count()
                if (current_swap is not None and last_swap is not None
                        and current_swap != last_swap):
                    self.refresh_video()
                last_swap = current_swap
            if self.watches and self._watch_stop():
                return StopReason(STOP_WATCH, executed)
            kind = self.target.poll(marks)
            if kind is not None:
                return StopReason(kind, executed)
        return StopReason(STOP_LIMIT, executed)

    def _watch_stop(self) -> bool:
        """Si una región vigilada cambió con la última instrucción."""
        changes = self._watch_changes(self.target.last_writer())
        if not changes:
            return False
        self._watch_lines = changes
        # El foco va al núcleo que escribió: es de quien se quiere el estado.
        self.target.focus_last_actor()
        return True

    def _watch_changes(self, writer: str = "") -> list[str]:
        """Regiones vigiladas que ya no valen lo que valían; las rebasa."""
        changes = []
        for watch in self.watches.values():
            try:
                now = self.target.read_memory(watch.address, watch.length)
            except TargetError:
                continue
            if now != watch.value:
                changes.append(
                    f"watch 0x{watch.address:08X}: "
                    f"{_format_watch(watch.value)} → {_format_watch(now)}")
                watch.previous, watch.value = watch.value, now
                watch.writer = writer
                watch.changed_at = self._serial
        return changes

    def watch_rows(self) -> list[WatchRow]:
        return [WatchRow(
            address=watch.address, label=self.source.symbol(watch.address),
            length=watch.length, value=watch.value, previous=watch.previous,
            writer=watch.writer, changed=watch.changed_at == self._serial)
            for watch in sorted(self.watches.values(),
                                key=lambda w: w.address)]

    def _rebase_watches(self) -> None:
        """Da por bueno el valor actual: lo cambió el usuario, no el programa."""
        for watch in self.watches.values():
            try:
                watch.value = self.target.read_memory(
                    watch.address, watch.length)
            except TargetError:
                pass

    def step_over(self) -> StopReason:
        """Un paso, pero una llamada cuenta como una sola instrucción."""
        state = self.target.state()
        if state.halted:
            return StopReason(STOP_ALREADY, 0)
        word = self.word_at(state.pc)
        if word is None or ((word >> 26) & 0x3F) not in _CALL_OPCODES:
            return self.step()
        return self.resume(stop_at={(state.pc + 4) & 0xFFFFFFFF})

    def finish(self) -> StopReason:
        """Ejecuta hasta retornar de la función que contiene el PC actual.

        Se sigue la profundidad de las llamadas ejecutadas desde este punto;
        así un RET de una función hija no se confunde con el RET que buscamos.
        No depende del valor inicial de R31 ni de cómo se guarde en la pila.
        """
        if self.target.state().halted:
            return StopReason(STOP_ALREADY, 0)

        executed = 0
        depth = 0
        while executed < self.operation_limit:
            if self._interrupt.is_set():
                return StopReason(STOP_INTERRUPTED, executed)
            state = self.target.state()
            word = self.word_at(state.pc)
            if word is None:
                self.target.step()
                executed += 1
            else:
                opcode = (word >> 26) & 0x3F
                is_call = opcode in _CALL_OPCODES
                is_return = (opcode == 0x2E
                             and ((word >> 16) & 0x1F) == 31)
                self.target.step()
                executed += 1
                if is_return:
                    if depth == 0:
                        state = self.target.state()
                        if state.halted:
                            return StopReason(self._halt_kind(), executed)
                        return StopReason(STOP_FINISHED, executed)
                    depth -= 1
                elif is_call:
                    depth += 1

            state = self.target.state()
            if state.halted:
                return StopReason(self._halt_kind(), executed)
            if state.pc in self.breakpoints:
                return StopReason(STOP_BREAKPOINT, executed)
        return StopReason(STOP_LIMIT, executed)

    def run_to_next_swap(self) -> StopReason:
        """Ejecuta hasta que el vídeo complete el siguiente intercambio."""
        initial = self.target.video_swap_count()
        if initial is None:
            raise TargetError("este objetivo no permite esperar un frame")
        executed = 0
        if not self.target.can_run():
            return StopReason(STOP_ALREADY, 0)
        while executed < self.operation_limit:
            if self._interrupt.is_set():
                return StopReason(STOP_INTERRUPTED, executed)
            self.target.advance()
            executed += 1
            current = self.target.video_swap_count()
            if current is not None and current != initial:
                return StopReason(STOP_SWAP, executed)
            if self.watches and self._watch_stop():
                return StopReason(STOP_WATCH, executed)
            kind = self.target.poll(set())
            if kind is not None:
                return StopReason(kind, executed)
        return StopReason(STOP_LIMIT, executed)

    def clear_interrupt(self) -> None:
        self._interrupt.clear()

    def interrupt(self) -> None:
        self._interrupt.set()
        self.target.request_interrupt()

    def _halt_kind(self) -> str:
        return STOP_ERROR if self.target.state().error else STOP_HALT

    # -- lectura de estado -------------------------------------------------

    def word_at(self, address: int) -> int | None:
        try:
            data = self.target.read_memory(address, 4)
        except TargetError:
            return None
        return int.from_bytes(data, "little")

    def listing(self, before: int = 8, after: int = 16,
                center: int | None = None) -> list[ListingRow]:
        """Las instrucciones alrededor del PC, para el panel de código.

        Con mapa de fuente se recorren los PC que el ensamblador asignó de
        verdad --así una directiva de 40 bytes ocupa una línea, no diez--; sin
        él, de cuatro en cuatro, que es lo único que se puede suponer.
        """
        pc = self.target.state().pc
        view_pc = pc if center is None else center
        if self._known_pcs:
            index = bisect.bisect_left(self._known_pcs, view_pc)
            if (index >= len(self._known_pcs)
                    or self._known_pcs[index] != view_pc):
                # El PC no está en el mapa (datos, o programa distinto del
                # fuente): se enseña igualmente, encajado donde le toca.
                addresses = self._known_pcs[max(0, index - before):index]
                addresses = (addresses + [view_pc]
                             + self._known_pcs[index:index + after])
            else:
                start = max(0, index - before)
                addresses = self._known_pcs[start:index + after + 1]
        else:
            start = max(0, view_pc - 4 * before)
            addresses = list(range(start, view_pc + 4 * (after + 1), 4))

        pcs = self.target.pcs()
        rows = []
        for address in addresses:
            word = self.word_at(address)
            rows.append(ListingRow(
                address=address,
                word=word,
                text=self.source.describe(address, word, pc),
                is_pc=address == pc,
                has_breakpoint=address in self.breakpoints,
                labels=tuple(self.source.labels_at.get(address, ())),
                cpu_pc=pcs is not None and address == pcs[0],
                gpu_pc=pcs is not None and address == pcs[1],
            ))
        return rows

    def register_rows(self) -> list[tuple[str, int]]:
        return [(f"R{index}", value)
                for index, value in enumerate(self.target.registers())]

    def memory_rows(self, address: int | None = None,
                    length: int | None = None) -> list[tuple[int, bytes]]:
        """Filas de 16 bytes. Una región ilegible devuelve lista vacía."""
        address = self.memory_address if address is None else address
        length = self.memory_length if length is None else length
        address &= ~0xF
        try:
            data = self.target.read_memory(address, length)
        except TargetError:
            return []
        return [(address + offset, data[offset:offset + 16])
                for offset in range(0, len(data), 16)]

    def status_line(self) -> str:
        state = self.target.state()
        label = self.source.nearest(state.pc)
        where = f"0x{state.pc:08X}"
        if label is not None:
            name, offset = label
            where += f" <{name}+{offset}>" if offset else f" <{name}>"
        parts = [self.target.name, f"PC={where}", f"instr={state.instructions}"]
        if state.error:
            name = ERROR_NAMES.get(state.error_code, "desconocido")
            parts.append(
                f"ERROR 0x{state.error_code:02X} ({name}) "
                f"en 0x{state.error_pc:08X}")
        elif state.halted:
            parts.append("HALT")
        summary = self.target.summary()
        if summary:
            parts.append(f"│ {summary}")
        return "  ".join(parts)

    def describe_stop(self, stop: StopReason) -> str:
        state = self.target.state()
        if stop.kind == STOP_ALREADY:
            return stop.detail or "la maquina ya estaba parada (usa `reset`)"
        suffix = f" ({stop.executed} instrucciones)"
        where = self.target.stop_location()
        if stop.kind == STOP_STEPPED:
            return f"0x{state.pc:08X}" + where + suffix
        if stop.kind == STOP_BREAKPOINT:
            return f"parada en 0x{state.pc:08X}" + where + suffix
        if stop.kind == STOP_WATCH:
            writer = self.target.last_writer()
            return ("; ".join(self._watch_lines)
                    + (f" (escrito por {writer})" if writer else "") + suffix)
        if stop.kind == STOP_STALLED:
            return ("sin progreso: la CPU esta parada y quedan warps vivos que "
                    "no pueden avanzar (¿una barrera a la que no llegan todos?)"
                    + suffix)
        if stop.kind == STOP_SWAP:
            return "intercambio de framebuffer completado" + suffix
        if stop.kind == STOP_FINISHED:
            return f"retorno completado en 0x{state.pc:08X}" + suffix
        if stop.kind == STOP_INTERRUPTED:
            return "ejecucion interrumpida" + suffix
        if stop.kind == STOP_ERROR:
            name = ERROR_NAMES.get(state.error_code, "desconocido")
            return (f"ERROR 0x{state.error_code:02X} ({name}) en "
                    f"0x{state.error_pc:08X}" + where + suffix)
        if stop.kind == STOP_HALT:
            return "HALT" + suffix
        return f"limite de {stop.executed} instrucciones alcanzado"

    # -- comandos ----------------------------------------------------------

    def parse_address(self, token: str) -> int:
        """Una etiqueta, `pc`, o un número (`0x...`, decimal, `0b...`)."""
        label = self.source.resolve(token)
        if label is not None:
            return label
        if token.lower() == "pc":
            return self.target.state().pc
        try:
            return int(token, 0) & 0xFFFFFFFF
        except ValueError:
            raise CommandError(f"no se que direccion es '{token}'") from None

    def _parse_value(self, token: str) -> int:
        try:
            return int(token, 0) & 0xFFFFFFFF
        except ValueError:
            label = self.source.resolve(token)
            if label is None:
                raise CommandError(f"valor invalido: '{token}'") from None
            return label

    def _parse_count(self, token: str) -> int:
        try:
            count = int(token, 0)
        except ValueError:
            raise CommandError(f"numero invalido: '{token}'") from None
        if count <= 0:
            raise CommandError("tiene que ser positivo")
        return count

    @property
    def video(self):
        if self._video is None:
            from tools.debug_video import VideoViewer

            self._video = VideoViewer(self.target, on_interrupt=self.interrupt)
        return self._video

    def _input_device(self):
        machine = self.target.simulated_machine()
        return getattr(machine, "input", None)

    def open_screen(self) -> str:
        """Abre (o refresca) la ventana de pantalla del simulador."""
        machine = self.target.simulated_machine()
        if machine is None or getattr(machine, "video", None) is None:
            raise TargetError(
                "la ventana de pantalla solo existe en el simulador con vídeo "
                "(hace falta --video o --window)")
        device = machine.input
        if self._screen is not None and self._screen.is_open:
            self._screen.refresh(device, force=True)
            return "pantalla refrescada"
        from tools.sim_display import SimDisplay
        from tools.sim_peripherals import resolve_font

        # F12 y cerrar la ventana no paran la máquina: F12 interrumpe la
        # ejecución en curso, como cualquier otra orden del depurador.
        display = SimDisplay(self.screen_font or resolve_font("cpc464"),
                             on_interrupt=self.interrupt, stop_on_close=False)
        display.bind(machine)
        if device is not None:
            device.attach_host(display, every=1000)
        display.start(device)
        self._screen = display
        if device is None:
            return ("ventana de pantalla (sin INPUT: --keyboard, --mouse o "
                    "--window para teclado y ratón)")
        return "ventana de pantalla con teclado y ratón; F12 interrumpe"

    def close_screen(self) -> None:
        screen, self._screen = self._screen, None
        if screen is None:
            return
        device = self._input_device()
        if device is not None and device.host is screen:
            device.host = None
        screen.close()

    def close_video(self) -> None:
        """Cierra las ventanas si llegaron a abrirse. Idempotente."""
        if self._video is not None:
            self._video.close()
        self.close_screen()

    def refresh_video(self) -> None:
        """Repinta la ventana si está abierta y toca. Barato si no lo está."""
        if self._video is not None:
            self._video.refresh()
        if self._screen is not None:
            self._screen.refresh(self._input_device(), force=True)

    def refresh_video_title(self) -> None:
        """Actualiza la barra de la ventana sin tocar los píxeles."""
        if self._video is not None:
            self._video.refresh_title()
        if self._screen is not None and self._screen.process is not None:
            # Con INPUT, `InputDevice.tick` ya da la mano; esto cubre el caso
            # sin INPUT y es barato: `poll` solo trabaja si toca refrescar.
            self._screen.poll(self._input_device())

    def execute(self, line: str) -> list[str]:
        """Ejecuta una línea de comando y devuelve lo que hay que enseñar.

        Los errores de uso salen como `CommandError` y los de capacidad como
        `TargetError`: los dos son texto para el usuario, no fallos. Quien
        llama los captura e imprime; nada aquí escribe por su cuenta.
        """
        parts = line.split()
        if not parts:
            return []
        name, args = parts[0].lower(), parts[1:]
        self._serial += 1

        handler = _COMMANDS.get(name)
        if handler is None:
            raise CommandError(
                f"comando desconocido: '{name}' (prueba `help`)")
        lines = handler(self, args)
        if self.watches:
            if name in _USER_WRITES:
                # Lo cambió quien depura: no es una noticia.
                self._rebase_watches()
            else:
                # Un `step`, `over`... que no pasó por `resume` también puede
                # haber escrito; si `resume` ya lo contó, aquí no hay cambio.
                lines = lines + self._watch_changes()
        # Tras cualquier comando, la ventana de vídeo enseña el estado nuevo.
        # Aquí y no en la TUI: así el modo línea la refresca igual, sin repetir
        # la llamada en dos sitios.
        self.refresh_video()
        return lines

    # Cada comando devuelve las líneas a enseñar. Registrados abajo en
    # _COMMANDS para que `help` y la TUI puedan listarlos sin duplicar nada.

    def _cmd_step(self, args: list[str]) -> list[str]:
        count = self._parse_count(args[0]) if args else 1
        stop = self.step(count)
        return self.target.pop_notices() + [self.describe_stop(stop)]

    def _cmd_over(self, args: list[str]) -> list[str]:
        if args:
            raise CommandError("`over` no lleva argumentos")
        return [self.describe_stop(self.step_over())]

    def _cmd_finish(self, args: list[str]) -> list[str]:
        if args:
            raise CommandError("`finish` no lleva argumentos")
        return [self.describe_stop(self.finish())]

    def _cmd_run(self, args: list[str]) -> list[str]:
        limit = self._parse_count(args[0]) if args else self.run_limit
        return [self.describe_stop(self.resume(max_instructions=limit))]

    def _cmd_until(self, args: list[str]) -> list[str]:
        if len(args) != 1:
            raise CommandError("uso: until DIRECCION|etiqueta")
        target = self.parse_address(args[0])
        return [self.describe_stop(self.resume(stop_at={target}))]

    def _cmd_break(self, args: list[str]) -> list[str]:
        if not args:
            return self._cmd_breaks([])
        address = self.parse_address(args[0])
        self.breakpoints.add(address)
        return [f"breakpoint en 0x{address:08X}"]

    def _cmd_delete(self, args: list[str]) -> list[str]:
        if not args or args[0] == "all":
            count = len(self.breakpoints)
            self.breakpoints.clear()
            return [f"{count} breakpoints borrados"]
        address = self.parse_address(args[0])
        if address not in self.breakpoints:
            raise CommandError(f"no hay breakpoint en 0x{address:08X}")
        self.breakpoints.discard(address)
        return [f"borrado el breakpoint de 0x{address:08X}"]

    def _cmd_breaks(self, args: list[str]) -> list[str]:
        if not self.breakpoints:
            return ["sin breakpoints"]
        lines = []
        for address in sorted(self.breakpoints):
            symbol = self.source.symbol(address)
            lines.append(f"0x{address:08X}" + (f"  {symbol}" if symbol else ""))
        return lines

    def _cmd_watch(self, args: list[str]) -> list[str]:
        """`watch X [N]`: parar cuando cambie el valor de N bytes en X."""
        if not args:
            if not self.watches:
                return ["sin watches"]
            return [f"0x{watch.address:08X}  {watch.length} bytes  "
                    f"= {_format_watch(watch.value)}"
                    + (f"  {self.source.symbol(watch.address)}"
                       if self.source.symbol(watch.address) else "")
                    for watch in sorted(self.watches.values(),
                                        key=lambda w: w.address)]
        if len(args) > 2:
            raise CommandError("uso: watch DIRECCION|etiqueta [BYTES]")
        if not self.target.fast_memory:
            raise TargetError(
                "este objetivo lee la memoria por un enlace lento: un watch "
                "obligaría a leerla tras cada instruccion")
        address = self.parse_address(args[0])
        length = self._parse_count(args[1]) if len(args) > 1 else 4
        try:
            value = self.target.read_memory(address, length)
        except TargetError:
            raise CommandError(
                f"region ilegible: 0x{address:08X}+{length}") from None
        self.watches[address] = Watch(address, length, value)
        self.target.track_writer = True
        return [f"watch en 0x{address:08X} ({length} bytes), "
                f"vale {_format_watch(value)}"]

    def _cmd_unwatch(self, args: list[str]) -> list[str]:
        if not args or args[0] == "all":
            count = len(self.watches)
            self.watches.clear()
            self.target.track_writer = False
            return [f"{count} watches borrados"]
        address = self.parse_address(args[0])
        if address not in self.watches:
            raise CommandError(f"no hay watch en 0x{address:08X}")
        del self.watches[address]
        self.target.track_writer = bool(self.watches)
        return [f"borrado el watch de 0x{address:08X}"]

    def _cmd_regs(self, args: list[str]) -> list[str]:
        if args:
            index = _parse_register(args[0])
            value = self.target.registers()[index]
            return [f"R{index} = 0x{value:08X} ({_signed(value)})"]
        lines = []
        registers = self.target.registers()
        for base in range(0, len(registers), 4):
            lines.append("  ".join(
                f"R{index:<2} 0x{registers[index]:08X}"
                for index in range(base, min(base + 4, len(registers)))))
        return lines

    def _cmd_set(self, args: list[str]) -> list[str]:
        if len(args) != 2:
            raise CommandError("uso: set R5 0x10  |  set pc etiqueta")
        destination, value_text = args
        value = self._parse_value(value_text)
        if destination.lower() == "pc":
            self.target.require(CAPS_WRITE_PC)
            self.target.set_pc(value)
            return [f"PC = 0x{value:08X}"]
        index = _parse_register(destination)
        self.target.require(CAPS_WRITE_REGISTER)
        self.target.set_register(index, value)
        return [f"R{index} = 0x{value:08X}"]

    def _cmd_mem(self, args: list[str]) -> list[str]:
        if args:
            self.memory_address = self.parse_address(args[0]) & ~0xF
        if len(args) > 1:
            self.memory_length = self._parse_count(args[1])
        rows = self.memory_rows()
        if not rows:
            raise CommandError(
                f"region ilegible: 0x{self.memory_address:08X}"
                f"+{self.memory_length}")
        return [format_memory_row(address, data) for address, data in rows]

    def _cmd_write(self, args: list[str]) -> list[str]:
        if len(args) != 2:
            raise CommandError("uso: write DIRECCION VALOR")
        address = self.parse_address(args[0])
        value = self._parse_value(args[1])
        self.target.require(CAPS_WRITE_MEMORY)
        self.target.write_word(address, value)
        return [f"[0x{address:08X}] = 0x{value:08X}"]

    def _cmd_fb(self, args: list[str]) -> list[str]:
        """`fb`, `fb back`, `fb both`, `fb off`, `fb auto on|off`."""
        if self.target.video_layout() is None:
            raise TargetError("este objetivo no tiene vídeo")
        if args == ["screen"]:
            return [self.open_screen()]
        if args and args[0] == "off":
            self.close_screen()
            return [self.video.close()]
        if args and args[0] == "auto":
            if len(args) != 2 or args[1] not in ("on", "off"):
                raise CommandError("uso: fb auto on|off")
            self.video.auto = args[1] == "on"
            estado = "solo cuando se pide"
            if self.video.auto:
                estado = "tras cada comando"
            return [f"refresco: {estado}"]

        if not args:
            buffers = ("front",)
        elif args == ["both"]:
            buffers = ("front", "back")
        else:
            buffers = tuple(args)
        lines = [self.video.show(buffers)]
        if not self.video.auto:
            lines.append("`fb` otra vez para refrescar "
                         "(o `fb auto on`, a ~1,5 s por buffer)")
        return lines

    def _cmd_input(self, args: list[str]) -> list[str]:
        """Estado de INPUT sin consumir nada: mirar la cola no la vacía."""
        if args:
            raise CommandError("`input` no lleva argumentos")
        device = self._input_device()
        if device is None:
            raise TargetError(
                "este objetivo no tiene INPUT (en el simulador: --keyboard, "
                "--mouse, --window o --input-script)")
        from tools import hid_keys
        from tools.sim_devices import InputDevice

        def present(flag: bool) -> str:
            return "presente" if flag else "ausente"

        buttons = {0: "left", 1: "right", 2: "middle"}
        lines = [
            f"teclado {present(device.keyboard_present)}, "
            f"ratón {present(device.mouse_present)}, "
            f"cola {len(device.fifo)}/{InputDevice.FIFO_DEPTH}"
            + (", OVERFLOW" if device.overflow else ""),
            "teclas pulsadas: "
            + (" ".join(hid_keys.name_of(u) for u in device.pressed()) or "ninguna"),
            "botones del ratón: "
            + (" ".join(buttons.get(n, str(n)) for n in device._bits(device.mouse_buttons))
               or "ninguno"),
        ]
        for index, word in enumerate(device.fifo):
            event = InputDevice.decode_event(word)
            if event["type"] == "key":
                text = (f"tecla {hid_keys.name_of(event['usage'])} "
                        f"{'down' if event['down'] else 'up'}"
                        f"  modificadores=0x{event['modifiers']:02X}")
            elif event["type"] == "modifiers":
                text = f"modificadores 0x{event['modifiers']:02X}"
            elif event["type"] == "button":
                text = (f"botón {buttons.get(event['button'], event['button'])} "
                        f"{'down' if event['down'] else 'up'}")
            elif event["type"] == "move":
                text = f"movimiento dx={event['dx']} dy={event['dy']}"
            else:
                text = f"evento reservado 0x{event['word']:08X}"
            lines.append(f"  {index:>2}: {text}")
        return lines

    def _cmd_frame(self, args: list[str]) -> list[str]:
        if args:
            raise CommandError("`frame` no lleva argumentos")
        return [self.describe_stop(self.run_to_next_swap())]

    def _cmd_reset(self, args: list[str]) -> list[str]:
        if args == ["gpu"]:
            self.target.require(CAPS_RESET_GPU)
            self.target.reset_gpu()
            return ["reset blando de la GPU: warps, errores y barreras "
                    "descartados; descriptores y memoria intactos"]
        if args:
            raise CommandError("uso: reset  |  reset gpu")
        self.target.require(CAPS_RESET)
        self.target.reset()
        if self.target.warp_rows() is not None:
            return ["reset duro: RAM a cero, imagen recargada, CPU y GPU "
                    "como tras el reset del sistema"]
        return ["reset"]

    # -- CPU + GPU ---------------------------------------------------------

    def _require_gpu(self) -> list[WarpRow]:
        rows = self.target.warp_rows()
        if rows is None:
            raise TargetError(
                "este objetivo no tiene GPU (en el simulador: --gpu)")
        return rows

    def _parse_index(self, token: str) -> int:
        try:
            value = int(token, 0)
        except ValueError:
            raise CommandError(f"numero invalido: '{token}'") from None
        if value < 0:
            raise CommandError("no puede ser negativo")
        return value

    def _focus_line(self) -> str:
        return f"foco: {self.target.name}"

    def _cmd_core(self, args: list[str]) -> list[str]:
        if len(args) > 1:
            raise CommandError("uso: core [cpu|gpu]")
        self._require_gpu()
        self.target.set_core(args[0].lower() if args else None)
        return [self._focus_line()]

    def _cmd_warp(self, args: list[str]) -> list[str]:
        if len(args) > 1:
            raise CommandError("uso: warp [N]")
        self._require_gpu()
        self.target.select_warp(self._parse_index(args[0]) if args else None)
        return [self._focus_line()]

    def _cmd_lane(self, args: list[str]) -> list[str]:
        if len(args) > 1:
            raise CommandError("uso: lane [N]")
        self._require_gpu()
        self.target.select_lane(self._parse_index(args[0]) if args else None)
        return [self._focus_line()]

    def _cmd_round(self, args: list[str]) -> list[str]:
        """`round [N]`: una instrucción en cada warp que pueda avanzar, N veces."""
        count = self._parse_count(args[0]) if args else 1
        self._require_gpu()
        executed, rounds, last = 0, 0, []
        for _ in range(count):
            try:
                last = self.target.round_warps()
            except TargetError:
                if rounds == 0:
                    raise
                break
            rounds += 1
            executed += len(last)
            if self.target.gpu_fault():
                break
        if rounds == 1:
            lines = ["ronda: warps " + " ".join(str(n) for n in last)
                     + f" ({executed} instrucciones)"]
        else:
            lines = [f"{rounds} rondas ({executed} instrucciones)"]
        if self.target.gpu_fault():
            lines.append(self.describe_stop(StopReason(STOP_ERROR, executed)))
        return lines

    def _cmd_sched(self, args: list[str]) -> list[str]:
        """`sched [N]`: N instrucciones elegidas por el planificador; el foco las sigue."""
        count = self._parse_count(args[0]) if args else 1
        self._require_gpu()
        executed = 0
        for _ in range(count):
            try:
                self.target.sched_step()
            except TargetError:
                if executed == 0:
                    raise
                break
            executed += 1
            if self.target.gpu_fault():
                break
        if self.target.gpu_fault():
            return [self.describe_stop(StopReason(STOP_ERROR, executed))]
        return [self.describe_stop(StopReason(STOP_STEPPED, executed))]

    def _cmd_warps(self, args: list[str]) -> list[str]:
        if args:
            raise CommandError("`warps` no lleva argumentos")
        return format_warp_table(self._require_gpu())

    def _cmd_lanes(self, args: list[str]) -> list[str]:
        if args:
            raise CommandError("`lanes` no lleva argumentos")
        self._require_gpu()
        grid = self.target.lane_grid()
        return format_lane_grid(grid) if grid is not None else []

    def _cmd_quit(self, args: list[str]) -> list[str]:
        self.quit = True
        # Sin esto la ventana sobrevive al depurador que la abrió.
        self.close_video()
        return []

    def help_entries(self) -> list[tuple[str, str]]:
        """Los comandos que este objetivo tiene: sin `fb` si no hay vídeo, etc."""
        hidden = set()
        if self.target.video_layout() is None:
            hidden.add("fb")
        if self.target.video_swap_count() is None:
            hidden.add("frame")
        if self._input_device() is None:
            hidden.add("input")
        if self.target.warp_rows() is None:
            hidden.update({"core", "warp", "lane", "warps", "lanes",
                           "round", "sched"})
        return [(name, text) for name, text in HELP
                if name.split()[0] not in hidden]

    def help_sections(self) -> list[tuple[str, list[tuple[str, str]]]]:
        """`help_entries` agrupados por tema, en el orden de `HELP_SECTIONS`."""
        grouped: dict[str, list[tuple[str, str]]] = {
            title: [] for title in HELP_SECTIONS}
        for name, text in self.help_entries():
            title = next((title for title, names in HELP_SECTIONS.items()
                          if name.split()[0] in names), "Otros")
            grouped.setdefault(title, []).append((name, text))
        return [(title, items) for title, items in grouped.items() if items]

    def _cmd_help(self, args: list[str]) -> list[str]:
        return [f"{name:<10} {text}" for name, text in self.help_entries()]


def _parse_register(token: str) -> int:
    text = token.upper()
    if text.startswith("R"):
        text = text[1:]
    if not text.isdigit():
        raise CommandError(f"no es un registro: '{token}'")
    index = int(text)
    if not 0 <= index < 32:
        raise CommandError(f"registro fuera de rango: '{token}'")
    return index


def _signed(value: int) -> int:
    return value - (1 << 32) if value & 0x80000000 else value


def format_memory_row(address: int, data: bytes) -> str:
    """`0x0000 00 11 .. |texto|`, el formato de toda la vida."""
    hexa = " ".join(f"{byte:02X}" for byte in data).ljust(16 * 3 - 1)
    ascii_text = "".join(
        chr(byte) if 0x20 <= byte < 0x7F else "." for byte in data)
    return f"0x{address:08X}  {hexa}  |{ascii_text}|"


def _format_watch(data: bytes) -> str:
    """Hasta 8 bytes como número little-endian; más, como bytes en orden."""
    if len(data) <= 8:
        return f"0x{int.from_bytes(data, 'little'):0{2 * len(data)}X}"
    return " ".join(f"{byte:02X}" for byte in data)


#: Comandos con los que quien depura cambia memoria o estado a propósito.
_USER_WRITES = {"write", "w", "set", "reset"}


def mask_bits(active: int, live: int, lanes: int) -> str:
    """Una lane por carácter: `●` activa, `○` viva pero fuera de la ruta, `·` muerta."""
    return "".join(
        "●" if active >> lane & 1 else "○" if live >> lane & 1 else "·"
        for lane in range(lanes))


def format_warp_table(rows: list[WarpRow]) -> list[str]:
    lines = ["   W  estado    PC          lanes     SIMT   logico  arg"]
    for row in rows:
        lines.append(
            f"{'▶' if row.focused else ' '}  {row.number:<2} {row.state:<8}  "
            f"0x{row.pc:08X}  "
            f"{mask_bits(row.active_mask, row.live_mask, row.lanes)}  "
            f"r{row.region_depth} p{row.path_depth}   "
            f"{row.logical_id:<6}  0x{row.arg:08X}")
    return lines


def format_lane_grid(grid: LaneGrid) -> list[str]:
    """Registros por lane. Se omiten las filas que valen cero en todas."""
    lanes = len(grid.regs)
    lines = [f"warp {grid.warp}   lanes "
             + mask_bits(grid.active_mask, grid.live_mask, lanes)
             + f"   foco: lane {grid.lane}",
             "    " + " ".join(f"{'L' + str(lane):>8}" for lane in range(lanes))]
    hidden = 0
    for register in range(32):
        values = [grid.regs[lane][register] for lane in range(lanes)]
        if not any(values):
            hidden += 1
            continue
        lines.append(f"R{register:<2} "
                     + " ".join(f"{value:08X}" for value in values))
    if hidden:
        lines.append(f"({hidden} registros a cero en todas las lanes omitidos)")
    return lines


HELP: tuple[tuple[str, str], ...] = (
    ("step [N]", "ejecuta N instrucciones (por defecto 1)"),
    ("over", "un paso, saltando la llamada entera si es JAL/JALR"),
    ("finish", "ejecuta hasta retornar de la funcion actual"),
    ("run [N]", "ejecuta hasta breakpoint, HALT o error"),
    ("until X", "ejecuta hasta la direccion o etiqueta X"),
    ("break [X]", "pone un breakpoint, o los lista si no hay argumento"),
    ("delete [X]", "borra el breakpoint X, o todos"),
    ("watch [X N]", "para cuando cambie el valor de N bytes en X (4 por "
                    "defecto) y dice quien escribio; sin argumento, los lista"),
    ("unwatch [X]", "borra el watch de X, o todos"),
    ("regs [Rn]", "enseña los registros"),
    ("set X V", "escribe `set R5 0x10` o `set pc etiqueta`"),
    ("mem [X N]", "vuelca N bytes desde X"),
    ("write X V", "escribe la palabra V en la direccion X"),
    ("fb [X]", "ventana de framebuffer: front (por defecto), back, both, off; "
               "`fb screen` es la pantalla del simulador, con consola y teclado/ratón"),
    ("input", "estado de INPUT: teclas, botones y cola de eventos, sin consumirlos"),
    ("frame", "ejecuta hasta completar el siguiente intercambio de framebuffer"),
    ("core [cpu|gpu]", "cambia el nucleo con foco (sin argumento, alterna): "
                       "recibe step, regs, set y el listado"),
    ("warp [N]", "foco en el warp N de la GPU (sin argumento, el siguiente)"),
    ("lane [N]", "foco en la lane N del warp (sin argumento, la siguiente)"),
    ("round [N]", "una instruccion en cada warp que pueda avanzar, en orden "
                  "(el foco no se mueve); N rondas"),
    ("sched [N]", "N instrucciones del warp que elige el planificador; el "
                  "foco las sigue (es el STEP del hardware)"),
    ("warps", "tabla de warps: estado, PC, mascara de lanes, pilas SIMT"),
    ("lanes", "registros de todas las lanes del warp con foco"),
    ("reset [gpu]", "reinicia PC, registros y contadores sin borrar memoria; "
                    "con CPU+GPU, `reset` es el duro (RAM a cero e imagen "
                    "recargada) y `reset gpu` el blando"),
    ("quit", "sale"),
)

#: Cómo se agrupan los comandos en la ventana de ayuda. Un comando que no esté
#: aquí cae en «Otros»: no se pierde, pero se nota y se coloca.
HELP_SECTIONS: dict[str, frozenset[str]] = {
    "Ejecución": frozenset({"step", "over", "finish", "run", "until", "frame"}),
    "Breakpoints y watch": frozenset({"break", "delete", "watch", "unwatch"}),
    "Estado": frozenset({"regs", "set", "mem", "write"}),
    "CPU + GPU": frozenset({"core", "warp", "lane", "warps", "lanes",
                            "round", "sched"}),
    "Vídeo y entrada": frozenset({"fb", "input"}),
    "Sesión": frozenset({"reset", "quit"}),
}

_COMMANDS = {
    "step": DebugSession._cmd_step, "s": DebugSession._cmd_step,
    "over": DebugSession._cmd_over, "n": DebugSession._cmd_over,
    "finish": DebugSession._cmd_finish,
    "run": DebugSession._cmd_run, "c": DebugSession._cmd_run,
    "continue": DebugSession._cmd_run,
    "until": DebugSession._cmd_until, "u": DebugSession._cmd_until,
    "break": DebugSession._cmd_break, "b": DebugSession._cmd_break,
    "delete": DebugSession._cmd_delete, "d": DebugSession._cmd_delete,
    "breaks": DebugSession._cmd_breaks,
    "watch": DebugSession._cmd_watch,
    "unwatch": DebugSession._cmd_unwatch,
    "regs": DebugSession._cmd_regs, "r": DebugSession._cmd_regs,
    "set": DebugSession._cmd_set,
    "mem": DebugSession._cmd_mem, "x": DebugSession._cmd_mem,
    "write": DebugSession._cmd_write, "w": DebugSession._cmd_write,
    "fb": DebugSession._cmd_fb, "v": DebugSession._cmd_fb,
    "frame": DebugSession._cmd_frame, "f": DebugSession._cmd_frame,
    "input": DebugSession._cmd_input,
    "core": DebugSession._cmd_core,
    "warp": DebugSession._cmd_warp,
    "lane": DebugSession._cmd_lane,
    "round": DebugSession._cmd_round,
    "sched": DebugSession._cmd_sched,
    "warps": DebugSession._cmd_warps,
    "lanes": DebugSession._cmd_lanes,
    "reset": DebugSession._cmd_reset,
    "help": DebugSession._cmd_help, "?": DebugSession._cmd_help,
    "quit": DebugSession._cmd_quit, "q": DebugSession._cmd_quit,
}
