"""De una dirección al trozo de programa que hay en ella.

Para un `.asm` no se desensambla nada: se ensambla con `mini_asm.first_pass` y
se empareja cada línea del fuente con el PC que le tocó, exactamente como hace
`format_listing`. Sale gratis y es mejor que un desensamblador, porque conserva
comentarios, nombres de etiqueta y las macros tal como se escribieron.

Para un `.bin` o un `.hex` no hay fuente que emparejar, así que la vista cae a
la palabra en crudo. Cuando el desensamblador del punto 13 del TODO esté hecho,
el único sitio que hay que tocar es `describe()`.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

_ISA = Path(__file__).resolve().parents[1] / "1.isa"
if str(_ISA) not in sys.path:
    sys.path.insert(0, str(_ISA))

_MEMORY_MNEMONICS = {
    "LOAD", "STORE", "LOADB", "LOADUB", "STOREB",
    "LOADH", "LOADUH", "STOREH",
}
_DIRECT_TARGET_OPERAND = {
    "BEQ": 2, "BNE": 2, "BLT": 2, "BGE": 2,
    "BLTU": 2, "BGEU": 2,
    "BRA": 0, "SSY": 0, "JAL": 1,
}


@dataclass
class SourceMap:
    """PC -> texto fuente, más la tabla de etiquetas en los dos sentidos."""

    #: Texto de la línea que ocupa cada PC.
    text: dict[int, str] = field(default_factory=dict)
    #: Etiquetas que caen en cada PC (puede haber varias).
    labels_at: dict[int, list[str]] = field(default_factory=dict)
    #: Nombre de etiqueta -> PC, para resolver `break bucle`.
    labels: dict[str, int] = field(default_factory=dict)
    #: Expansión real de una pseudoinstrucción, indexada por su primer PC.
    expansions: dict[int, tuple[str, ...]] = field(default_factory=dict)
    #: PC de continuación -> PC inicial de la pseudoinstrucción.
    continuations: dict[int, int] = field(default_factory=dict)
    #: PC -> (registro base, offset con signo) para accesos con offset simbólico.
    memory_operands: dict[int, tuple[int, int]] = field(default_factory=dict)
    #: Destinos de control conocidos estáticamente.
    jump_targets: dict[int, int] = field(default_factory=dict)
    #: PC -> (registro base, desplazamiento en palabras) para JALR/JR/RET.
    indirect_jumps: dict[int, tuple[int, int]] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.text

    def symbol(self, address: int) -> str | None:
        """La etiqueta exacta de una dirección, si la hay."""
        names = self.labels_at.get(address)
        return names[0] if names else None

    def nearest(self, address: int) -> tuple[str, int] | None:
        """Etiqueta anterior más cercana y su desplazamiento: `bucle+8`."""
        best = None
        for name, pc in self.labels.items():
            if pc <= address and (best is None or pc > best[1]):
                best = (name, pc)
        if best is None:
            return None
        return best[0], address - best[1]

    @property
    def addresses(self) -> set[int]:
        """Direcciones que deben conservar una fila en el listado."""
        return self.text.keys() | self.continuations.keys()

    def describe(self, address: int, word: int | None,
                 active_pc: int | None = None) -> str:
        """Lo que se enseña en la línea de desensamblado de esa dirección."""
        start = self.continuations.get(address, address)
        expansion = self.expansions.get(start)
        if expansion is not None:
            active_start = self.continuations.get(active_pc, active_pc)
            if active_start == start:
                source = self.text[start]
                continuation = "  (continuacion)"
                column = max(32, len(source), len(continuation))
                if address == start:
                    return (f"{source:<{column}} ──────▶ "
                            f"{expansion[0]}")
                return (f"{continuation:<{column}} └─────▶ "
                        f"{expansion[(address - start) // 4]}")
            if address != start:
                return "  (continuacion)"
        line = self.text.get(address)
        if line is not None:
            return line
        if word is None:
            return "????"
        return f".word 0x{word:08X}"

    def resolve(self, token: str) -> int | None:
        """Una etiqueta o `None`. Los números los resuelve quien llama."""
        return self.labels.get(token)

    def memory_annotation(self, address: int,
                          registers: list[int]) -> str | None:
        """Offset simbólico y dirección efectiva del acceso en `address`."""
        operands = self.memory_operands.get(address)
        if operands is None:
            return None
        base, offset = operands
        effective = (registers[base] + offset) & 0xFFFFFFFF
        return f"; {offset:+d} [0x{effective:08X}]"

    def target_annotation(self, address: int, registers: list[int]
                          ) -> tuple[str, str, int] | None:
        """Texto, tipo de viewport y destino clicable de una instrucción."""
        memory = self.memory_annotation(address, registers)
        if memory is not None:
            effective = int(memory.rsplit("[0x", 1)[1][:-1], 16)
            return memory, "memory", effective
        if address in self.jump_targets:
            target = self.jump_targets[address]
            return f"; → [0x{target:08X}]", "code", target
        indirect = self.indirect_jumps.get(address)
        if indirect is not None:
            base, words = indirect
            target = (registers[base] + words * 4) & 0xFFFFFFFC
            return f"; → [0x{target:08X}]", "code", target
        return None


def from_program(path: Path,
                 include_dirs: tuple[Path, ...] = ()) -> SourceMap:
    """Construye el mapa de un programa. Un `.bin`/`.hex` da un mapa vacío.

    Un fuente que no ensambla no es un error del depurador: el programa ya se
    cargó (el simulador lo ensambló por su cuenta), así que perder el mapa solo
    significa ver palabras en vez de texto. Mejor eso que no arrancar.
    """
    path = Path(path)
    if path.suffix.lower() != ".asm":
        return SourceMap()

    try:
        from mini_asm import first_pass, parse_reg, resolve_target, split_operands

        lines, labels, _, equates = first_pass(
            path.read_text(encoding="utf-8"), path.parent, path.name,
            tuple(include_dirs))
    except Exception:
        return SourceMap()

    source = SourceMap()
    for line in lines:
        # La primera línea de cada PC gana: una directiva multi-palabra ocupa
        # varias direcciones y solo la cabecera tiene texto propio.
        source.text.setdefault(line.pc, line.text.strip())
        parts = line.text.split(None, 1)
        mnemonic = parts[0].upper()
        operands = split_operands(parts[1] if len(parts) > 1 else "")
        if mnemonic in {"LI", "LA"}:
            if len(operands) == 2:
                register, value_text = operands
                value = resolve_target(value_text, labels) & 0xFFFFFFFF
                source.expansions[line.pc] = (
                    f"MOVHI {register}, 0x{value >> 16:04X}",
                    f"ORI {register}, {register}, 0x{value & 0xFFFF:04X}",
                )
                source.continuations[line.pc + 4] = line.pc
        elif mnemonic in _MEMORY_MNEMONICS:
            if len(operands) == 3 and operands[2] in labels:
                value = resolve_target(operands[2], labels) & 0xFFFF
                offset = value - 0x10000 if value & 0x8000 else value
                source.memory_operands[line.pc] = (
                    parse_reg(operands[1]), offset)
        elif mnemonic in _DIRECT_TARGET_OPERAND:
            index = _DIRECT_TARGET_OPERAND[mnemonic]
            if len(operands) > index:
                source.jump_targets[line.pc] = resolve_target(
                    operands[index], labels) & 0xFFFFFFFF
        elif mnemonic == "JALR" and len(operands) == 3:
            words = resolve_target(operands[2], labels) & 0xFFFF
            if words & 0x8000:
                words -= 0x10000
            source.indirect_jumps[line.pc] = (parse_reg(operands[1]), words)
        elif mnemonic == "JR" and len(operands) == 1:
            source.indirect_jumps[line.pc] = (parse_reg(operands[0]), 0)
        elif mnemonic == "RET":
            source.indirect_jumps[line.pc] = (31, 0)

    # Los `.equ` comparten espacio de nombres con las etiquetas pero no son
    # posiciones del programa; anotarlos llenaría cada PC de nombres de
    # `mmio.inc`. Mismo criterio que `format_listing`.
    for name, pc in labels.items():
        if name in equates:
            continue
        source.labels[name] = pc
        source.labels_at.setdefault(pc, []).append(name)
    for names in source.labels_at.values():
        names.sort()

    return source
