#!/usr/bin/env python3
"""Genera entradas y resultados esperados independientes para rect.asm."""
from __future__ import annotations

import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORDS = 0x4000
GUARD = 0xDEADBEEF


def write(name: str, words: list[int]) -> None:
    path = HERE / "_build" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack(f"<{len(words)}I", *words))


def main() -> int:
    guard = [GUARD] * WORDS
    src1 = [0x1000 + n * 7 for n in range(7 * 15)]
    src2 = [0x9000 + n for n in range(3 * 8)]
    write("guard.bin", guard)
    write("src1.bin", src1)
    write("src2.bin", src2)

    rect1 = guard.copy()
    for row in range(7):
        rect1[row * 24:row * 24 + 13] = [0xAAAA5555] * 13
    write("rect1.bin", rect1)

    dst1 = guard.copy()
    for row in range(7):
        dst1[row * 28:row * 28 + 13] = src1[row * 15:row * 15 + 13]
    write("dst1.bin", dst1)

    rect2 = guard.copy()
    rect2[0] = 0x12345678
    write("rect2.bin", rect2)

    dst2 = guard.copy()
    for row in range(3):
        dst2[row * 16:row * 16 + 8] = src2[row * 8:row * 8 + 8]
    write("dst2.bin", dst2)
    write("results.bin", [0, 0, 0, 0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
