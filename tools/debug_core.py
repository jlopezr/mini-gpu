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
from dataclasses import dataclass

from tools.debug_source import SourceMap
from tools.debug_target import (
    CAPS_FREE_RUN, CAPS_RESET, CAPS_WRITE_MEMORY, CAPS_WRITE_PC,
    CAPS_WRITE_REGISTER, DebugTarget, TargetError,
)

# Por qué se paró la ejecución. La TUI los traduce a un color y un mensaje.
STOP_BREAKPOINT = "breakpoint"
STOP_HALT = "halt"
STOP_ERROR = "error"
STOP_LIMIT = "limit"
STOP_STEPPED = "stepped"
STOP_ALREADY = "already-halted"

ERROR_NAMES = {
    0x00: "sin error",
    0x01: "opcode invalido",
    0x02: "acceso a memoria",
    0x03: "trap explicito",
    0x04: "division por cero",
    0x05: "encoding invalido",
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


class DebugSession:
    """Una máquina parada, un mapa de fuente y un puñado de comandos."""

    def __init__(self, target: DebugTarget, source: SourceMap | None = None,
                 run_limit: int = DEFAULT_RUN_LIMIT) -> None:
        self.target = target
        self.source = source or SourceMap()
        self.run_limit = run_limit
        self.breakpoints: set[int] = set()
        self.quit = False
        # La ventana de framebuffer se crea al primer `fb`: quien no la use no
        # paga ni un proceso ni el import.
        self._video = None
        # Ventana del panel de memoria; los comandos `mem`/`x` la mueven.
        self.memory_address = 0
        self.memory_length = 128
        self._known_pcs = sorted(self.source.text)

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
                return StopReason(
                    STOP_ALREADY if executed == 0 else self._halt_kind(),
                    executed)
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
        budget = self.run_limit if max_instructions is None else max_instructions

        if self.target.state().halted:
            return StopReason(STOP_ALREADY, 0)

        if not marks and self.target.supports(CAPS_FREE_RUN):
            # Sin ninguna marca no hay nada que comprobar entre instrucción e
            # instrucción, así que se deja correr al objetivo. El contador sale
            # de su propio estado, no de contar pasos aquí.
            before = self.target.state().instructions
            self.target.free_run()
            after = self.target.state()
            return StopReason(self._halt_kind(),
                              max(0, after.instructions - before))

        executed = 0
        while executed < budget:
            self.target.step()
            executed += 1
            state = self.target.state()
            if state.halted:
                return StopReason(self._halt_kind(), executed)
            if state.pc in marks:
                return StopReason(STOP_BREAKPOINT, executed)
        return StopReason(STOP_LIMIT, executed)

    def step_over(self) -> StopReason:
        """Un paso, pero una llamada cuenta como una sola instrucción."""
        state = self.target.state()
        if state.halted:
            return StopReason(STOP_ALREADY, 0)
        word = self.word_at(state.pc)
        if word is None or ((word >> 26) & 0x3F) not in _CALL_OPCODES:
            return self.step()
        return self.resume(stop_at={(state.pc + 4) & 0xFFFFFFFF})

    def _halt_kind(self) -> str:
        return STOP_ERROR if self.target.state().error else STOP_HALT

    # -- lectura de estado -------------------------------------------------

    def word_at(self, address: int) -> int | None:
        try:
            data = self.target.read_memory(address, 4)
        except TargetError:
            return None
        return int.from_bytes(data, "little")

    def listing(self, before: int = 8, after: int = 16) -> list[ListingRow]:
        """Las instrucciones alrededor del PC, para el panel de código.

        Con mapa de fuente se recorren los PC que el ensamblador asignó de
        verdad --así una directiva de 40 bytes ocupa una línea, no diez--; sin
        él, de cuatro en cuatro, que es lo único que se puede suponer.
        """
        pc = self.target.state().pc
        if self._known_pcs:
            index = bisect.bisect_left(self._known_pcs, pc)
            if index >= len(self._known_pcs) or self._known_pcs[index] != pc:
                # El PC no está en el mapa (datos, o programa distinto del
                # fuente): se enseña igualmente, encajado donde le toca.
                addresses = self._known_pcs[max(0, index - before):index]
                addresses = addresses + [pc] + self._known_pcs[index:index + after]
            else:
                start = max(0, index - before)
                addresses = self._known_pcs[start:index + after + 1]
        else:
            start = max(0, pc - 4 * before)
            addresses = list(range(start, pc + 4 * (after + 1), 4))

        rows = []
        for address in addresses:
            word = self.word_at(address)
            rows.append(ListingRow(
                address=address,
                word=word,
                text=self.source.describe(address, word),
                is_pc=address == pc,
                has_breakpoint=address in self.breakpoints,
                labels=tuple(self.source.labels_at.get(address, ())),
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
        return "  ".join(parts)

    def describe_stop(self, stop: StopReason) -> str:
        state = self.target.state()
        if stop.kind == STOP_ALREADY:
            return "la maquina ya estaba parada (usa `reset`)"
        suffix = f" ({stop.executed} instrucciones)"
        if stop.kind == STOP_STEPPED:
            return f"0x{state.pc:08X}" + suffix
        if stop.kind == STOP_BREAKPOINT:
            return f"parada en 0x{state.pc:08X}" + suffix
        if stop.kind == STOP_ERROR:
            name = ERROR_NAMES.get(state.error_code, "desconocido")
            return (f"ERROR 0x{state.error_code:02X} ({name}) en "
                    f"0x{state.error_pc:08X}" + suffix)
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

            self._video = VideoViewer(self.target)
        return self._video

    def close_video(self) -> None:
        """Cierra la ventana si llegó a abrirse. Idempotente."""
        if self._video is not None:
            self._video.close()

    def refresh_video(self) -> None:
        """Repinta la ventana si está abierta y toca. Barato si no lo está."""
        if self._video is not None:
            self._video.refresh()

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

        handler = _COMMANDS.get(name)
        if handler is None:
            raise CommandError(
                f"comando desconocido: '{name}' (prueba `help`)")
        lines = handler(self, args)
        # Tras cualquier comando, la ventana de vídeo enseña el estado nuevo.
        # Aquí y no en la TUI: así el modo línea la refresca igual, sin repetir
        # la llamada en dos sitios.
        self.refresh_video()
        return lines

    # Cada comando devuelve las líneas a enseñar. Registrados abajo en
    # _COMMANDS para que `help` y la TUI puedan listarlos sin duplicar nada.

    def _cmd_step(self, args: list[str]) -> list[str]:
        count = self._parse_count(args[0]) if args else 1
        return [self.describe_stop(self.step(count))]

    def _cmd_over(self, args: list[str]) -> list[str]:
        if args:
            raise CommandError("`over` no lleva argumentos")
        return [self.describe_stop(self.step_over())]

    def _cmd_run(self, args: list[str]) -> list[str]:
        limit = self._parse_count(args[0]) if args else None
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
        if args and args[0] == "off":
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

    def _cmd_reset(self, args: list[str]) -> list[str]:
        self.target.require(CAPS_RESET)
        self.target.reset()
        return ["reset"]

    def _cmd_quit(self, args: list[str]) -> list[str]:
        self.quit = True
        # Sin esto la ventana sobrevive al depurador que la abrió.
        self.close_video()
        return []

    def _cmd_help(self, args: list[str]) -> list[str]:
        return [f"{name:<10} {text}" for name, text in HELP]


def _parse_register(token: str) -> int:
    text = token.upper()
    if not text.startswith("R") or not text[1:].isdigit():
        raise CommandError(f"no es un registro: '{token}'")
    index = int(text[1:])
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


HELP: tuple[tuple[str, str], ...] = (
    ("step [N]", "ejecuta N instrucciones (por defecto 1)"),
    ("over", "un paso, saltando la llamada entera si es JAL/JALR"),
    ("run [N]", "ejecuta hasta breakpoint, HALT o error"),
    ("until X", "ejecuta hasta la direccion o etiqueta X"),
    ("break [X]", "pone un breakpoint, o los lista si no hay argumento"),
    ("delete [X]", "borra el breakpoint X, o todos"),
    ("regs [Rn]", "enseña los registros"),
    ("set X V", "escribe `set R5 0x10` o `set pc etiqueta`"),
    ("mem [X N]", "vuelca N bytes desde X"),
    ("write X V", "escribe la palabra V en la direccion X"),
    ("fb [X]", "ventana de framebuffer: front (por defecto), back, both, off"),
    ("reset", "reinicia PC, registros y contadores sin borrar memoria"),
    ("quit", "sale"),
)

_COMMANDS = {
    "step": DebugSession._cmd_step, "s": DebugSession._cmd_step,
    "over": DebugSession._cmd_over, "n": DebugSession._cmd_over,
    "run": DebugSession._cmd_run, "c": DebugSession._cmd_run,
    "continue": DebugSession._cmd_run,
    "until": DebugSession._cmd_until, "u": DebugSession._cmd_until,
    "break": DebugSession._cmd_break, "b": DebugSession._cmd_break,
    "delete": DebugSession._cmd_delete, "d": DebugSession._cmd_delete,
    "breaks": DebugSession._cmd_breaks,
    "regs": DebugSession._cmd_regs, "r": DebugSession._cmd_regs,
    "set": DebugSession._cmd_set,
    "mem": DebugSession._cmd_mem, "x": DebugSession._cmd_mem,
    "write": DebugSession._cmd_write, "w": DebugSession._cmd_write,
    "fb": DebugSession._cmd_fb, "v": DebugSession._cmd_fb,
    "reset": DebugSession._cmd_reset,
    "help": DebugSession._cmd_help, "?": DebugSession._cmd_help,
    "quit": DebugSession._cmd_quit, "q": DebugSession._cmd_quit,
}
