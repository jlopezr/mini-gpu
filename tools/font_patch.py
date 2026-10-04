#!/usr/bin/env python3
"""Cambia la fuente de la consola en un bitstream ya construido, sin resintetizar.

La Font RAM de `text_console.v` (256 glifos de 128 bits) acaba en cuatro EBR de
512x36 con contenido inicial en `hardware.config`. Este modulo localiza esos
cuatro EBR por su contenido (reconoce cual de las fuentes de `fonts/` lleva el
bitstream), reescribe sus lineas `.bram_init` con la fuente pedida y vuelve a
empaquetar con `ecppack`. Con `--upload` ademas lo programa con `fujprog`.

Reparto, deducido y comprobado contra una sintesis completa (el bitstream
parcheado salio identico byte a byte): el bit b de un glifo vive en la posicion
b mod 36 de la palabra del EBR que guarda la porcion b div 36, y la direccion
es el codigo del glifo. En `.bram_init` cada palabra son cuatro tokens de 9 bits,
el menos significativo primero.

Solo vale para el netlist con el que se construyo el `.config`: cambiar el RTL
obliga a reconstruir, y entonces la fuente entra por `FONT_FILE`."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.prototype import (PrototypeResolutionError, ToolchainError,
                             find_toolchain_binary, oss_cad_suite_env,
                             resolve_prototype)

GLYPHS = 256
GLYPH_BITS = 128
WORD_BITS = 36
SLICES = -(-GLYPH_BITS // WORD_BITS)  # 4 EBR
LINES_PER_FONT = GLYPHS * WORD_BITS // 9 // 8  # 128 lineas de 8 tokens


class FontPatchError(RuntimeError):
    pass


def load_font(path: Path) -> list[int]:
    words = [int(token, 16) for token in path.read_text().split()]
    if len(words) != GLYPHS:
        raise FontPatchError(f"{path.name}: {len(words)} glifos, se esperaban {GLYPHS}")
    return words


def encode(font: list[int], slice_index: int) -> list[int]:
    """Tokens de 9 bits que lleva un EBR para la porcion `slice_index` de la fuente."""
    flat = []
    for glyph in font:
        for position in range(WORD_BITS):
            bit = WORD_BITS * slice_index + position
            flat.append((glyph >> bit) & 1 if bit < GLYPH_BITS else 0)
    return [sum(flat[9 * t + j] << j for j in range(9)) for t in range(len(flat) // 9)]


def bram_sections(lines: list[str]) -> dict[int, list[int]]:
    """EBR -> indices de las lineas de datos de su `.bram_init`."""
    sections: dict[int, list[int]] = {}
    current = None
    for index, line in enumerate(lines):
        if line.startswith(".bram_init"):
            current = int(line.split()[1])
            sections[current] = []
        elif line.startswith("."):
            current = None
        elif current is not None and line.strip():
            sections[current].append(index)
    return sections


def _row_tokens(lines: list[str], indices: list[int]) -> list[int]:
    return [int(token, 16) for index in indices[:LINES_PER_FONT] for token in lines[index].split()]


def locate(lines: list[str], font: list[int]) -> dict[int, int] | None:
    """{porcion: EBR} si el config lleva exactamente esta fuente, o None."""
    sections = bram_sections(lines)
    found: dict[int, int] = {}
    for slice_index in range(SLICES):
        wanted = encode(font, slice_index)
        for ebr, indices in sections.items():
            if ebr not in found.values() and len(indices) >= LINES_PER_FONT \
                    and _row_tokens(lines, indices) == wanted:
                found[slice_index] = ebr
                break
        else:
            return None
    return found


def rewrite(lines: list[str], mapping: dict[int, int], font: list[int]) -> list[str]:
    sections = bram_sections(lines)
    result = list(lines)
    for slice_index, ebr in mapping.items():
        tokens = encode(font, slice_index)
        for row, index in enumerate(sections[ebr][:LINES_PER_FONT]):
            line = lines[index]
            tail = line[len(line.rstrip()):]  # conserva el final de linea original
            result[index] = " ".join(f"{t:03x}" for t in tokens[8 * row:8 * row + 8]) + tail
    return result


def _ecppack(config: Path, bitstream: Path) -> None:
    completed = subprocess.run([str(find_toolchain_binary("ecppack")), str(config), str(bitstream)],
                               capture_output=True, text=True, env=oss_cad_suite_env())
    if completed.returncode != 0:
        raise FontPatchError(f"ecppack fallo:\n{completed.stdout}{completed.stderr}")


def _candidates(prototype_dir: Path) -> dict[str, Path]:
    fonts = prototype_dir / "fonts"
    return {path.stem.removeprefix("font8x16_"): path for path in sorted(fonts.glob("*.hex"))}


def patch(prototype_dir: Path, target: str) -> tuple[Path, str]:
    """Devuelve (bitstream parcheado, nombre de la fuente que llevaba)."""
    candidates = _candidates(prototype_dir)
    if target in candidates:
        target_name = target
    elif Path(target).is_file():
        target_name = Path(target).stem.removeprefix("font8x16_")
        candidates = {**candidates, target_name: Path(target).resolve()}
    else:
        raise FontPatchError(f"fuente desconocida: {target}. Disponibles: {', '.join(candidates)}")

    build = prototype_dir / "_build" / "default"
    config = build / "hardware.config"
    if not config.is_file():
        raise FontPatchError(f"no hay {config}: construye antes el prototipo (`build`)")
    text = config.read_text(newline="")
    lines = text.split("\n")

    fonts = {name: load_font(path) for name, path in candidates.items()}
    for name, font in fonts.items():
        mapping = locate(lines, font)
        if mapping is not None:
            current = name
            break
    else:
        raise FontPatchError("el bitstream no lleva ninguna de las fuentes conocidas "
                             f"({', '.join(fonts)}); no se sabe que sustituir")

    patched = rewrite(lines, mapping, fonts[target_name])
    out_config, out_bit = build / f"font-{target_name}.config", build / f"font-{target_name}.bit"
    out_config.write_text("\n".join(patched), newline="")
    _ecppack(out_config, out_bit)
    return out_bit, current


def upload(bitstream: Path, project: Path) -> None:
    sys.path.insert(0, str(ROOT / "x.tests"))
    from backends import board  # noqa: E402  (necesita pyserial)
    print(f"--- `fujprog` directo con {bitstream} ---", flush=True)
    completed = subprocess.run([board._find_fujprog(), "-l", "2", str(bitstream)], cwd=project)
    if completed.returncode != 0:
        raise FontPatchError(f"`fujprog` fallo con codigo {completed.returncode}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cambia la fuente de la consola en el bitstream construido, sin resintetizar.")
    parser.add_argument("-p", "--prototype", required=True)
    parser.add_argument("font", help="nombre en fonts/ (pc, cpc464...) o ruta a un .hex")
    parser.add_argument("--upload", action="store_true", help="programa la placa (SRAM)")
    args = parser.parse_args(argv)
    try:
        project = resolve_prototype(args.prototype, root=ROOT)
        print(f"Using prototype: {project.name}")
        bitstream, current = patch(project, args.font)
        print(f"fuente actual del bitstream: {current}; parcheado a {args.font}: {bitstream}")
        if args.upload:
            upload(bitstream, project)
            print("programada. La CPU arranca vacia: recarga el programa (board-load).")
    except (PrototypeResolutionError, ToolchainError, FontPatchError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
