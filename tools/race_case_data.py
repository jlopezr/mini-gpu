"""Materializa la entrada de una carga de ``compare_race.py`` para incrustarla.

El blob contiene primero el bloque GPU (nwarps, nlanes y p[6]) y después la
única región de entrada del caso. El anfitrión C sustituye el puntero de esa
región por la etiqueta donde ``build-c --data`` haya colocado el blob.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPARE = ROOT / "32.cpu-gpu-func-sim" / "compare"
sys.path.insert(0, str(COMPARE))

import compare_race  # noqa: E402


def build_case(workload: str, value: int | None = None):
    spec = compare_race.WORKLOADS[workload]
    case = spec.case(spec.default if value is None else value)
    if case is None or len(case.memory) != 1:
        raise ValueError(f"{workload} must have exactly one input memory region")
    return case


def build_blob(workload: str, value: int | None = None) -> bytes:
    case = build_case(workload, value)
    _address, data = case.memory[0]
    return struct.pack("<8I", compare_race.WARPS, 8, *case.block) + data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("workload", choices=("blur", "life", "rotate"))
    parser.add_argument("output", type=Path)
    parser.add_argument("--value", type=int, help="semilla o fotograma; por defecto, el del comparador")
    parser.add_argument(
        "--expected-dir", type=Path,
        help="escribe expected-0.bin, expected-1.bin... para un test.json",
    )
    args = parser.parse_args(argv)
    case = build_case(args.workload, args.value)
    _address, data = case.memory[0]
    blob = struct.pack("<8I", compare_race.WARPS, 8, *case.block) + data
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(blob)
    print(f"{args.output} ({len(blob)} bytes)")
    if args.expected_dir is not None:
        args.expected_dir.mkdir(parents=True, exist_ok=True)
        for index, (_address, expected) in enumerate(case.expect):
            path = args.expected_dir / f"expected-{index}.bin"
            path.write_bytes(expected)
            print(f"{path} ({len(expected)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
