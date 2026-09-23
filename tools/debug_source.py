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


@dataclass
class SourceMap:
    """PC -> texto fuente, más la tabla de etiquetas en los dos sentidos."""

    #: Texto de la línea que ocupa cada PC.
    text: dict[int, str] = field(default_factory=dict)
    #: Etiquetas que caen en cada PC (puede haber varias).
    labels_at: dict[int, list[str]] = field(default_factory=dict)
    #: Nombre de etiqueta -> PC, para resolver `break bucle`.
    labels: dict[str, int] = field(default_factory=dict)

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

    def describe(self, address: int, word: int | None) -> str:
        """Lo que se enseña en la línea de desensamblado de esa dirección."""
        line = self.text.get(address)
        if line is not None:
            return line
        if word is None:
            return "????"
        return f".word 0x{word:08X}"

    def resolve(self, token: str) -> int | None:
        """Una etiqueta o `None`. Los números los resuelve quien llama."""
        return self.labels.get(token)


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
        from mini_asm import first_pass

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
