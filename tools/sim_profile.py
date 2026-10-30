"""Perfil por función de un programa en los simuladores (`--profile`): sim-sys, sim-cpu y sim-gpu.

Cuenta cada instrucción ejecutada en la función que la contiene: la etiqueta de
código más cercana por debajo de su PC, sin las internas de lcc (`L.n`). Como
lcc da a cada función del `.asm` el nombre que tiene en C (también a las
`static`) y no expande en línea, son las funciones C del programa, más las del
runtime en ensamblador (`_start`, `gpu_run`...).

En la CPU, para cada función:
  - propias: las instrucciones que ejecuta ella misma;
  - llamadas: las veces que se entra con `JAL`/`JALR`;
  - total: las propias más las de todo lo que llama. La pila de llamadas se
    sigue por la dirección de retorno, así que un `JR` que vuelve más arriba de
    un nivel (una llamada final que `mini-opt` convirtió en `BRA`) cierra todos
    los marcos que salta: la función a la que se saltó cuenta dentro de la que
    hizo el salto, y su total es solo el propio. La recursión no se cuenta dos
    veces.
En la GPU, las instrucciones de warp de cada kernel (`__kernel_<nombre>`, que se
muestra como `<nombre> (kernel)`); un kernel no llama a funciones.

Los nombres salen del `.asm` del programa (lo ensambla el simulador) o de
`--symbols`, que es lo que hace falta para un `.bin`: `build-c` deja el `.asm`
que ensambla junto a los intermedios.
"""
from __future__ import annotations

import bisect
import re
import sys
from collections import Counter
from pathlib import Path

from tools.debug_source import from_program

ROOT = Path(__file__).resolve().parents[1]
INCLUDE_DIRS = (ROOT / "t.tests" / "inc", ROOT / "1.isa" / "runtime")

OPCODE_JAL, OPCODE_JALR, OPCODE_JR = 0x2C, 0x2D, 0x2E
KERNEL_PREFIX = "__kernel_"
# Etiquetas de bloque, no de función: las de lcc (`L.n`, que el ensamblador renombra a `L.<fichero>.n` al
# incluir varios `.s`), las del softfloat embebido y las anónimas.
LOCAL_RE = re.compile(r"^(?:L|__sf)(?:\.\d+)+$|^@")
TOP = 25        # filas en la salida estándar; en un fichero van todas
UNNAMED = "(sin nombre)"     # el código antes de la primera etiqueta (o de un programa sin ninguna)


def add_arguments(parser) -> None:
    group = parser.add_argument_group("perfil por función")
    group.add_argument("--profile", nargs="?", const="-", metavar="FICHERO",
                       help="al terminar, instrucciones de CPU y de warp por función (las de C y las "
                            "del runtime); en FICHERO en vez de en la salida estándar")
    group.add_argument("--symbols", type=Path, metavar="PROGRAMA.asm",
                       help="el .asm del que salen los nombres de función, si el programa es un .bin "
                            "o un .hex (build-c lo deja junto a los intermedios)")


class Symbols:
    """De un PC a la función que lo contiene."""

    def __init__(self, labels: dict[str, int]):
        functions = sorted((address, name) for name, address in labels.items()
                           if not LOCAL_RE.match(name))
        self.starts = [address for address, _ in functions]
        self.names = [name for _, name in functions]
        self.cache: dict[int, str] = {}

    @classmethod
    def from_program(cls, program: Path, symbols: Path | None = None) -> "Symbols":
        source = symbols or program
        if source.suffix.lower() != ".asm":
            raise ValueError(f"--profile necesita los nombres de función: {program.name} no es un .asm; "
                             "pasa el .asm con --symbols (build-c lo deja junto a los intermedios)")
        mapping = from_program(source, INCLUDE_DIRS)
        if mapping.empty:                       # sin texto: no ensambló (un .asm sin etiquetas sí vale)
            raise ValueError(f"--profile: no se pudo ensamblar {source} para sacar los nombres de función")
        return cls(mapping.labels)

    def function(self, pc: int) -> str:
        name = self.cache.get(pc)
        if name is None:
            index = bisect.bisect_right(self.starts, pc) - 1
            name = self.names[index] if index >= 0 else UNNAMED
            self.cache[pc] = name
        return name


class Profile:
    def __init__(self, symbols: Symbols):
        self.symbols = symbols
        self.own: Counter[str] = Counter()
        self.total: Counter[str] = Counter()
        self.calls: Counter[str] = Counter()
        self.gpu: Counter[str] = Counter()
        self.executed = 0
        self.entry: str | None = None                   # la primera función que se ejecuta (_start)
        self.stack: list[tuple[str, int, int]] = []     # (función, dirección de retorno, `executed` al entrar)
        self.open: Counter[str] = Counter()             # marcos abiertos de cada función (recursión)

    def cpu(self, pc: int, word: int | None, next_pc: int) -> None:
        """Una instrucción de CPU retirada en `pc`; `next_pc` es a donde va."""
        self.executed += 1
        name = self.symbols.function(pc)
        if self.entry is None:
            self.entry = name
        self.own[name] += 1
        if word is None:
            return
        opcode = word >> 26
        if opcode in (OPCODE_JAL, OPCODE_JALR):
            callee = self.symbols.function(next_pc)
            self.calls[callee] += 1
            self.stack.append((callee, pc + 4, self.executed))
            self.open[callee] += 1
        elif opcode == OPCODE_JR:
            for depth in range(len(self.stack) - 1, -1, -1):
                if self.stack[depth][1] == next_pc:
                    while len(self.stack) > depth:
                        self._close()
                    break

    def _close(self) -> None:
        name, _, entered = self.stack.pop()
        self.open[name] -= 1
        if not self.open[name]:
            self.total[name] += self.executed - entered

    def gpu_event(self, event) -> None:
        """Un evento de la traza de la GPU (`TraceEvent`): una instrucción de warp."""
        if event.instruction is not None:
            self.gpu[self.symbols.function(event.pc)] += 1

    def finish(self) -> None:
        """Cierra los marcos que siguen abiertos (un `main` que no vuelve). Al punto de entrada nadie lo llama:
        su total es todo lo ejecutado."""
        while self.stack:
            self._close()
        if self.entry is not None:
            self.total[self.entry] = self.executed

    def report(self, stream, top: int | None = None) -> None:
        """Las funciones de más a menos instrucciones propias; con `top`, solo las primeras."""
        self.finish()
        if self.executed:
            print(f"\nPerfil de CPU: {self.executed} instrucciones", file=stream)
            print(f"  {'función':<28} {'propias':>12} {'%':>6} {'llamadas':>10} {'total':>12} {'%':>6}",
                  file=stream)
            rows = self.own.most_common()
            for name, own in rows[:top]:
                total = max(self.total[name], own)
                print(f"  {display(name):<28} {own:>12} {100 * own / self.executed:>5.1f}% "
                      f"{self.calls[name]:>10} {total:>12} {100 * total / self.executed:>5.1f}%",
                      file=stream)
            rest(stream, rows, top, self.executed)
        warp = sum(self.gpu.values())
        if warp:
            print(f"\nPerfil de GPU: {warp} instrucciones de warp", file=stream)
            print(f"  {'función':<28} {'instrucciones':>13} {'%':>6}", file=stream)
            rows = self.gpu.most_common()
            for name, count in rows[:top]:
                print(f"  {display(name):<28} {count:>13} {100 * count / warp:>5.1f}%", file=stream)
            rest(stream, rows, top, warp)


class GpuEvents:
    """El consumidor de eventos de la GPU de `11` (`System.trace`) cuando hay perfil: cada instrucción de warp va
    al perfil y, si la hay, a la traza (`trace()` la devuelve, o None). La GPU mira `detail` y `recording` para
    decidir si guarda los registros de antes, y `finish` cierra la traza: son los de la traza, y sin ella no hace
    falta nada."""

    def __init__(self, profile: Profile, trace=lambda: None):
        self.profile = profile
        self.trace = trace

    @property
    def detail(self) -> bool:
        trace = self.trace()
        return trace is not None and trace.detail

    @property
    def recording(self) -> bool:
        trace = self.trace()
        return trace is not None and trace.recording

    def __call__(self, event) -> None:
        self.profile.gpu_event(event)
        trace = self.trace()
        if trace is not None:
            trace(event)

    def finish(self, text: str) -> None:
        trace = self.trace()
        if trace is not None:
            trace.finish(text)


def rest(stream, rows, top: int | None, total: int) -> None:
    if top is not None and len(rows) > top:
        hidden = sum(count for _, count in rows[top:])
        print(f"  ... {len(rows) - top} funciones más: {hidden} instrucciones "
              f"({100 * hidden / total:.1f}%); todas con --profile FICHERO", file=stream)


def display(name: str) -> str:
    return f"{name[len(KERNEL_PREFIX):]} (kernel)" if name.startswith(KERNEL_PREFIX) else name


def from_arguments(args) -> Profile | None:
    if args.profile is None:
        if args.symbols is not None:
            raise ValueError("--symbols solo sirve con --profile")
        return None
    return Profile(Symbols.from_program(args.program, args.symbols))


def write_report(args, profile: Profile | None) -> None:
    if profile is None:
        return
    if args.profile == "-":
        profile.report(sys.stdout, TOP)
    else:
        with open(args.profile, "w", encoding="utf-8") as stream:
            profile.report(stream)
