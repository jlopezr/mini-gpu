#!/usr/bin/env python3
"""Ejecuta casos de conformidad sobre el simulador, la FPGA o ambos."""

from __future__ import annotations

import argparse
import importlib.util
import json
import struct
import sys
from pathlib import Path
from types import ModuleType

from backends.fpga import FpgaBackend
from backends.simulator import SimulatorBackend

ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parent
FPGA_MEMORY_SIZE = 16 * 1024


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se puede cargar el módulo {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def parse_integer(value: int | str, description: str) -> int:
    if isinstance(value, int):
        result = value
    elif isinstance(value, str):
        try:
            result = int(value, 0)
        except ValueError as error:
            raise ValueError(f"{description} inválido: {value}") from error
    else:
        raise TypeError(f"{description} debe ser un entero o una cadena")

    if not 0 <= result <= 0xFFFF_FFFF:
        raise ValueError(f"{description} fuera de 32 bits: {result}")
    return result


def load_program(path: Path) -> bytes:
    suffix = path.suffix.lower()
    if suffix == ".bin":
        data = path.read_bytes()
    elif suffix == ".hex":
        words = [
            int(line.strip(), 16)
            for line in path.read_text(encoding="ascii").splitlines()
            if line.strip()
        ]
        data = b"".join(struct.pack("<I", word) for word in words)
    elif suffix == ".asm":
        assembler = load_module(
            "miniisa_asm_for_tests",
            REPOSITORY / "1.isa" / "miniisa_asm.py",
        )
        words = assembler.assemble(path.read_text(encoding="utf-8"))
        data = b"".join(struct.pack("<I", word) for word in words)
    else:
        raise ValueError(f"Formato de programa no soportado: {path}")

    if not data or len(data) % 4:
        raise ValueError("El programa debe contener palabras completas de 32 bits")
    return data


def load_data_file(path: Path) -> bytes:
    """Load raw bytes, or little-endian 32-bit words from a textual .hex file."""
    if path.suffix.lower() != ".hex":
        return path.read_bytes()
    words = [
        int(line.split("#", 1)[0].strip(), 16)
        for line in path.read_text(encoding="ascii").splitlines()
        if line.split("#", 1)[0].strip()
    ]
    if any(not 0 <= word <= 0xFFFF_FFFF for word in words):
        raise ValueError(f"Palabra fuera de 32 bits en {path}")
    return b"".join(struct.pack("<I", word) for word in words)


def parse_register(name: str) -> int:
    if not isinstance(name, str) or not name.upper().startswith("R"):
        raise ValueError(f"Registro inválido: {name!r}")
    try:
        number = int(name[1:])
    except ValueError as error:
        raise ValueError(f"Registro inválido: {name!r}") from error
    if not 0 <= number < 32:
        raise ValueError(f"Registro fuera de rango: {name}")
    return number


def first_memory_difference(expected: bytes, actual: bytes) -> int | None:
    for offset, (expected_byte, actual_byte) in enumerate(zip(expected, actual)):
        if expected_byte != actual_byte:
            return offset
    return None if len(expected) == len(actual) else min(len(expected), len(actual))


def compare_result(case: dict, result: dict, backend_name: str) -> list[str]:
    expected = case["expected"]
    errors: list[str] = []

    for field in ("halted", "error"):
        if result[field] != expected[field]:
            errors.append(
                f"{backend_name}: {field}: esperado {expected[field]!r}, "
                f"obtenido {result[field]!r}"
            )

    for field in ("error_code", "pc"):
        if result[field] != expected[field]:
            errors.append(
                f"{backend_name}: {field}: esperado 0x{expected[field]:08x}, "
                f"obtenido 0x{result[field]:08x}"
            )

    for register, expected_value in expected["registers"].items():
        actual = result["registers"][register]
        if actual != expected_value:
            errors.append(
                f"{backend_name}: R{register}: esperado 0x{expected_value:08x}, "
                f"obtenido 0x{actual:08x}"
            )

    for memory_range, expected_data in expected["memory"].items():
        actual_data = result["memory"][memory_range]
        difference = first_memory_difference(expected_data, actual_data)
        if difference is not None:
            address, _ = memory_range
            expected_byte = expected_data[difference] if difference < len(expected_data) else None
            actual_byte = actual_data[difference] if difference < len(actual_data) else None
            errors.append(
                f"{backend_name}: memoria 0x{address + difference:08x}: "
                f"esperado {expected_byte!r}, obtenido {actual_byte!r} "
                f"(offset 0x{difference:x})"
            )

    return errors


def load_case(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    directory = path.parent

    if not isinstance(raw.get("name"), str) or not raw["name"]:
        raise ValueError("El caso necesita un nombre")

    program_path = directory / raw["program"]
    program = load_program(program_path)
    if len(program) > FPGA_MEMORY_SIZE:
        raise ValueError(
            f"El programa ocupa {len(program)} bytes; la FPGA admite "
            f"{FPGA_MEMORY_SIZE}"
        )
    expected_raw = raw["expect"]
    registers = {
        parse_register(name): parse_integer(value, name)
        for name, value in expected_raw.get("registers", {}).items()
    }

    initial_memory = []
    for item in raw.get("initial_memory", []):
        address = parse_integer(item["address"], "dirección inicial")
        data = load_data_file(directory / item["file"])
        if not data:
            raise ValueError(f"El fichero inicial {item['file']} está vacío")
        if address + len(data) > FPGA_MEMORY_SIZE:
            raise ValueError(f"Inicialización fuera de la RAM de datos: {item['file']}")
        initial_memory.append((address, data))

    expected_memory = {}
    for item in expected_raw.get("memory_dumps", []):
        address = parse_integer(item["address"], "dirección de dump")
        data = load_data_file(directory / item["file"])
        if not data:
            raise ValueError(f"El dump esperado {item['file']} está vacío")
        if address + len(data) > FPGA_MEMORY_SIZE:
            raise ValueError(f"Dump fuera de la RAM de datos: {item['file']}")
        expected_memory[(address, len(data))] = data

    max_instructions = raw.get("max_instructions", 1_000_000)
    timeout_seconds = raw.get("timeout_seconds", 5.0)
    if not isinstance(max_instructions, int) or max_instructions < 1:
        raise ValueError("max_instructions debe ser un entero positivo")
    if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds debe ser positivo")

    return {
        "name": raw["name"],
        "program": program,
        "initial_memory": initial_memory,
        "max_instructions": max_instructions,
        "timeout_seconds": float(timeout_seconds),
        "expected": {
            "halted": expected_raw.get("halted", True),
            "error": expected_raw.get("error", False),
            "error_code": parse_integer(
                expected_raw.get("error_code", 0), "error_code"
            ),
            "pc": parse_integer(expected_raw["pc"], "PC"),
            "registers": registers,
            "memory": expected_memory,
        },
    }


def discover_cases(arguments: list[Path]) -> list[Path]:
    if arguments:
        return [path.resolve() for path in arguments]
    return sorted((ROOT / "cases").glob("**/test.json"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", nargs="*", type=Path, metavar="TEST_JSON")
    parser.add_argument(
        "--backend",
        choices=("sim", "fpga", "both"),
        default="sim",
    )
    parser.add_argument("--port", default="COM3")
    parser.add_argument("--serial-timeout", type=float, default=1.0)
    args = parser.parse_args()

    case_paths = discover_cases(args.cases)
    if not case_paths:
        print("No se encontraron casos", file=sys.stderr)
        return 2

    backend_names = ("sim", "fpga") if args.backend == "both" else (args.backend,)
    backends = {}
    if "sim" in backend_names:
        backends["sim"] = SimulatorBackend(REPOSITORY)
    if "fpga" in backend_names:
        backends["fpga"] = FpgaBackend(
            REPOSITORY,
            port=args.port,
            serial_timeout=args.serial_timeout,
        )

    failures = 0
    for path in case_paths:
        try:
            case = load_case(path)
            results = {}
            for backend_name, backend in backends.items():
                result = backend.run(
                    program=case["program"],
                    initial_memory=case["initial_memory"],
                    register_numbers=set(case["expected"]["registers"]),
                    memory_ranges=list(case["expected"]["memory"]),
                    max_instructions=case["max_instructions"],
                    timeout_seconds=case["timeout_seconds"],
                )
                results[backend_name] = result
                errors = compare_result(case, result, backend_name)
                if errors:
                    failures += 1
                    print(f"FAIL {case['name']} [{backend_name}]")
                    for error in errors:
                        print(f"  {error}")
                else:
                    print(f"PASS {case['name']} [{backend_name}]")

            if len(results) == 2 and results["sim"] != results["fpga"]:
                failures += 1
                print(f"FAIL {case['name']} [diferencial]")
                print("  El estado observado del simulador y la FPGA no coincide")
        except Exception as error:
            failures += 1
            print(f"ERROR {path}: {error}", file=sys.stderr)

    print(f"{len(case_paths)} caso(s), {failures} fallo(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
