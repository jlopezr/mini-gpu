#!/usr/bin/env python3
"""Vectors for FTOI/ITOF in 38.fpga-cpu-pipelined/fp32_alu_tb.sv, from tools/fp32.py.

Each line: op (4 FTOI, 5 ITOF), fbits, operand, result -- 8 hex digits each.
    python3 tools/gen_fp32_convert_vectors.py > 38.fpga-cpu-pipelined/fp32_convert_vectors.hex
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.fp32 import fp32_to_int, int_to_fp32  # noqa: E402

EDGES = [0, 0x80000000, 1, 0x807FFFFF, 0x3F800000, 0xBF800000, 0x3F000000, 0x3FFFFFFF,
         0x4EFFFFFF, 0x4F000000, 0xCF000000, 0xCF000001, 0x7F800000, 0xFF800000,
         0x7FC00000, 0xFFFFFFFF, 0x7F800001, 0x00800000, 0x477FFFFF, 0x47000000]
INTS = [0, 1, 0xFFFFFFFF, 0x7FFFFFFF, 0x80000000, 0x80000001, 0x00FFFFFF, 0x01000001,
        0x01000003, 0x02000005, 0x7FFFFFC0, 0x7FFFFFBF, 0x10000]


def main() -> None:
    rng = random.Random(0x5EED)
    rows = []
    for a in EDGES:
        for fbits in (0, 1, 8, 16, 31):
            rows.append((4, fbits, a, fp32_to_int(a, fbits)))
    for a in INTS:
        for fbits in (0, 1, 16, 31):
            rows.append((5, fbits, a, int_to_fp32(a, fbits)))
    for _ in range(1500):
        fbits = rng.randrange(32)
        a = rng.getrandbits(32)
        if rng.random() < 0.6:
            a = (a & 0x807FFFFF) | (rng.randrange(100, 165) << 23)
        rows.append((4, fbits, a, fp32_to_int(a, fbits)))
        x = rng.getrandbits(32) >> rng.randrange(32)
        if rng.random() < 0.5:
            x = (0 - x) & 0xFFFFFFFF
        rows.append((5, fbits, x, int_to_fp32(x, fbits)))
    for op, fbits, a, r in rows:
        print(f"{op:08x} {fbits:08x} {a:08x} {r:08x}")


if __name__ == "__main__":
    main()
