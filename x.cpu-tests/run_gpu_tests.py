#!/usr/bin/env python3
"""Ejecuta casos de conformidad sobre el simulador, la FPGA o ambos."""

from __future__ import annotations

import argparse
import importlib.util
import json
import struct
import sys
import time
from pathlib import Path
from types import ModuleType

from backends import board
from backends import fpga as fpga_backend
from backends import gpu_fpga as gpu_fpga_backend
from backends import simulator as simulator_backend
from backends import gpu_simulator as gpu_backend
from backends.gpu_simulator import GpuBackend
from backends.fpga import FpgaBackend
from backends.gpu_fpga import GpuFpgaBackend
from backends.simulator import SimulatorBackend

ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parent
# Límite común a todos los casos: que quepan en un espacio de 32 bits. Si el
# caso cabe en el mapa concreto de un backend lo decide `incompatibility()`.
ARCHITECTURAL_MEMORY_SIZE = 32 * 1024 * 1024
# Opciones de construcción que un caso GPU puede fijar sobre el simulador.
SIMULATOR_OPTIONS = ("simt_region_depth", "simt_path_depth")
# A partir de aquí se anota el tiempo junto al resultado del caso.
SLOW_CASE_SECONDS = 1.0
BACKEND_DEFINITIONS = {
    "gpu-simulator": {
        "class": GpuBackend,
        "module": gpu_backend,
        "architecture": GpuBackend.ARCHITECTURE,
        "versions": gpu_backend.VERSIONS,
        "default_version": gpu_backend.DEFAULT_VERSION,
    },
    "cpu-simulator": {
        "class": SimulatorBackend,
        "module": simulator_backend,
        "architecture": SimulatorBackend.ARCHITECTURE,
        "versions": simulator_backend.VERSIONS,
        "default_version": simulator_backend.DEFAULT_VERSION,
    },
    "cpu-fpga": {
        "class": FpgaBackend,
        "module": fpga_backend,
        "architecture": FpgaBackend.ARCHITECTURE,
        "versions": fpga_backend.VERSIONS,
        "default_version": fpga_backend.DEFAULT_VERSION,
    },
    "gpu-fpga": {
        "class": GpuFpgaBackend,
        "module": gpu_fpga_backend,
        "architecture": GpuFpgaBackend.ARCHITECTURE,
        "versions": gpu_fpga_backend.VERSIONS,
        "default_version": gpu_fpga_backend.DEFAULT_VERSION,
    },
}


def resolve_backend_versions(
    specifications: list[str], backend_names: tuple[str, ...]
) -> dict[str, str]:
    """Resolve repeatable VERSION or BACKEND=VERSION command-line values."""
    selected = {
        name: BACKEND_DEFINITIONS[name]["default_version"]
        for name in backend_names
    }
    for specification in specifications:
        if "=" in specification:
            backend_name, version = specification.split("=", 1)
            if backend_name not in backend_names:
                raise ValueError(
                    f"--version menciona el backend no seleccionado {backend_name!r}"
                )
        else:
            if len(backend_names) != 1:
                raise ValueError(
                    "Con varios backends usa --version BACKEND=VERSION"
                )
            backend_name = backend_names[0]
            version = specification

        versions = BACKEND_DEFINITIONS[backend_name]["versions"]
        if version not in versions:
            choices = ", ".join(sorted(versions))
            raise ValueError(
                f"Versión {version!r} no disponible para {backend_name}; "
                f"opciones: {choices}"
            )
        selected[backend_name] = version
    return selected


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se puede cargar el módulo {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def parse_integer(value: int | str, description: str) -> int:
    if type(value) is int:
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
        if field not in expected:
            continue
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

    for field, value in expected.get("observations", {}).items():
        actual = result.get("observations", {}).get(field, "<ausente>")
        if actual != value:
            errors.append(f"{backend_name}: {field}: esperado {value!r}, obtenido {actual!r}")
    return errors


def gpu_expectations(raw: dict, warp_size: int) -> dict:
    """Normaliza observaciones por warp/hilo sin inventar un PC global."""
    observations = {}
    if "fault" in raw:
        fault = raw["fault"]
        observations["fault.present"] = fault is not None
        if fault is not None:
            fields = {"pc", "warp_id", "core_id", "address"}
            if not isinstance(fault, dict) or fault.keys() != fields:
                raise ValueError("expect.fault requiere pc, warp_id, core_id y address")
            for field, value in fault.items():
                if value is None and field in ("core_id", "address"):
                    observations[f"fault.{field}"] = None
                else:
                    number = parse_integer(value, f"fault.{field}")
                    if field == "warp_id" and number >= 8:
                        raise ValueError("fault.warp_id fuera de rango")
                    if field == "core_id" and number >= warp_size:
                        raise ValueError("fault.core_id fuera de rango")
                    observations[f"fault.{field}"] = number
    if "instructions_executed" in raw:
        observations["instructions_executed"] = parse_integer(
            raw["instructions_executed"], "instructions_executed")
    warps = raw.get("warps", {})
    if not isinstance(warps, dict):
        raise ValueError("expect.warps debe ser un objeto indexado por ID")
    for warp_id, state in warps.items():
        if warp_id not in {str(i) for i in range(8)}:
            raise ValueError(f"ID de warp esperado inválido: {warp_id}")
        if not isinstance(state, dict) or state.keys() - {
            "pc", "active_mask", "instructions_executed", "registers"
        }:
            raise ValueError(f"Estado esperado inválido del warp {warp_id}")
        prefix = f"warp[{warp_id}]"
        for field in ("pc", "active_mask", "instructions_executed"):
            if field in state:
                observations[f"{prefix}.{field}"] = parse_integer(state[field], field)
        lanes = state.get("registers", {})
        if not isinstance(lanes, dict):
            raise ValueError("registers del warp debe estar indexado por hilo")
        for lane_id, registers in lanes.items():
            if lane_id not in {str(i) for i in range(warp_size)}:
                raise ValueError(f"ID de hilo esperado inválido: {lane_id}")
            if not isinstance(registers, dict):
                raise ValueError("Los registros del hilo deben ser un objeto")
            for name, value in registers.items():
                number = parse_register(name)
                observations[f"{prefix}.lane[{lane_id}].R{number}"] = parse_integer(value, name)
    return observations


def simulator_options(raw: dict, architecture: str) -> dict:
    """Opciones de construcción del simulador declaradas por el caso."""
    options = raw.get("simulator_options", {})
    if not options:
        return {}
    if architecture != "gpu":
        raise ValueError("simulator_options solo se admite en casos GPU")
    if not isinstance(options, dict):
        raise ValueError("simulator_options debe contener un objeto JSON")
    unknown = set(options) - set(SIMULATOR_OPTIONS)
    if unknown:
        raise ValueError(f"simulator_options desconocidas: {', '.join(sorted(unknown))}")
    for name, value in options.items():
        if type(value) is not int or value < 1:
            raise ValueError(f"simulator_options.{name} debe ser un entero positivo")
    return dict(options)


def case_architecture(raw: object) -> str:
    if not isinstance(raw, dict) or raw.get("architecture") not in ("cpu", "gpu"):
        raise ValueError("El caso requiere architecture: cpu o gpu")
    architecture = raw["architecture"]
    if ("warp_config" in raw) != (architecture == "gpu"):
        raise ValueError("warp_config es obligatorio para GPU y no se admite para CPU")
    return architecture


def validate_compatibility(architecture: str, backend_names: tuple[str, ...]) -> None:
    for name in backend_names:
        supported = BACKEND_DEFINITIONS[name]["architecture"]
        if architecture != supported:
            raise ValueError(f"Caso {architecture} incompatible con backend {name} ({supported})")


def load_case(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    directory = path.parent

    architecture = case_architecture(raw)
    gpu = architecture == "gpu"
    warp_config = None
    if gpu:
        warp_config = json.loads((directory / raw["warp_config"]).read_text(encoding="utf-8-sig"))

    if not isinstance(raw.get("name"), str) or not raw["name"]:
        raise ValueError("El caso necesita un nombre")

    program_path = directory / raw["program"]
    program = load_program(program_path)
    if len(program) > ARCHITECTURAL_MEMORY_SIZE:
        raise ValueError(
            f"El programa ocupa {len(program)} bytes; el máximo es "
            f"{ARCHITECTURAL_MEMORY_SIZE}"
        )
    expected_raw = raw["expect"]
    if gpu and ("pc" in expected_raw or "registers" in expected_raw):
        raise ValueError("GPU: PC y registros deben estar dentro de expect.warps")
    if not gpu and any(field in expected_raw for field in ("warps", "instructions_executed", "fault")):
        raise ValueError("warps e instructions_executed requieren --backend gpu-simulator")
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
        if address + len(data) > ARCHITECTURAL_MEMORY_SIZE:
            raise ValueError(f"Inicialización fuera del mapa de memoria: {item['file']}")
        initial_memory.append((address, data))

    expected_memory = {}
    for item in expected_raw.get("memory_dumps", []):
        address = parse_integer(item["address"], "dirección de dump")
        data = load_data_file(directory / item["file"])
        if not data:
            raise ValueError(f"El dump esperado {item['file']} está vacío")
        if address + len(data) > ARCHITECTURAL_MEMORY_SIZE:
            raise ValueError(f"Dump fuera del mapa de memoria: {item['file']}")
        expected_memory[(address, len(data))] = data

    max_instructions = raw.get("max_instructions", 1_000_000)
    timeout_seconds = raw.get("timeout_seconds", 5.0)
    if not isinstance(max_instructions, int) or max_instructions < 1:
        raise ValueError("max_instructions debe ser un entero positivo")
    if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds debe ser positivo")

    requires = raw.get('requires', [])
    if not isinstance(requires, list) or any(item != 'atomic_warp_faults' for item in requires):
        raise ValueError('requires solo admite atomic_warp_faults')
    if requires and not gpu:
        raise ValueError('requires solo esta disponible para casos GPU')
    case = {
        "requires": requires,
        "architecture": architecture,
        "name": raw["name"],
        "program": program,
        "initial_memory": initial_memory,
        "max_instructions": max_instructions,
        "timeout_seconds": float(timeout_seconds),
        "simulator_options": simulator_options(raw, architecture),
        "expected": {
            "halted": expected_raw.get("halted", True),
            "error": expected_raw.get("error", False),
            "error_code": parse_integer(
                expected_raw.get("error_code", 0), "error_code"
            ),
            "registers": registers,
            "memory": expected_memory,
        },
    }
    if gpu:
        if not isinstance(warp_config, dict):
            raise ValueError("warp_config debe contener un objeto JSON")
        size = parse_integer(warp_config.get("warp_size", 8), "warp_size")
        if size == 0:
            raise ValueError("warp_size debe ser positivo")
        case["warp_config"] = warp_config
        case["expected"]["observations"] = gpu_expectations(expected_raw, size)
    else:
        case["expected"]["pc"] = parse_integer(expected_raw["pc"], "PC")
    return case


def discover_cases(arguments: list[Path]) -> list[Path]:
    if arguments:
        return [path.resolve() for path in arguments]
    return sorted(path for folder in ("cases", "cases-gpu")
                  for path in (ROOT / folder).glob("**/test.json"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", nargs="*", type=Path, metavar="TEST_JSON")
    parser.add_argument(
        "--backend",
        choices=(
            "cpu-simulator", "cpu-fpga", "both",
            "gpu-simulator", "gpu-fpga", "gpu-both",
        ),
        default="gpu-simulator",
    )
    parser.add_argument("--port", default="COM3")
    parser.add_argument("--serial-timeout", type=float, default=1.0)
    parser.add_argument(
        "--version",
        action="append",
        default=[],
        metavar="[BACKEND=]VERSION",
        help="versión del backend; puede repetirse al usar varios backends",
    )
    parser.add_argument("--trace", action="store_true",
                        help="traza del scheduler GPU por instrucción de warp")
    parser.add_argument("--trace-detail", action="store_true",
                        help="incluye registros y memoria en la traza GPU")
    parser.add_argument("--trace-limit", type=int,
                        help="máximo de eventos mostrados; no limita la ejecución")
    parser.add_argument("--trace-file", type=Path,
                        help="guarda la traza GPU en este fichero")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="autoriza sin preguntar la carga del bitstream "
                             "si la placa tiene otra versión")
    parser.add_argument("--no-upload", action="store_true",
                        help="nunca cargar el bitstream: si la placa no tiene "
                             "la versión correcta, falla")
    parser.add_argument("--durations", type=int, nargs="?", const=10, default=0,
                        metavar="N",
                        help="lista las N ejecuciones más lentas al terminar "
                             "(10 si se omite el valor)")
    args = parser.parse_args()
    if args.trace_limit is not None and args.trace_limit < 0:
        parser.error("--trace-limit no puede ser negativo")
    if (args.trace or args.trace_detail or args.trace_limit is not None or args.trace_file is not None) and args.backend != "gpu-simulator":
        parser.error("las opciones --trace solo están disponibles con --backend gpu-simulator")
    if args.yes and args.no_upload:
        parser.error("--yes y --no-upload se contradicen")
    if args.durations < 0:
        parser.error("--durations no puede ser negativo")

    case_paths = discover_cases(args.cases)
    if not case_paths:
        print("No se encontraron casos", file=sys.stderr)
        return 2

    backend_groups = {
        "both": ("cpu-simulator", "cpu-fpga"),
        "gpu-both": ("gpu-simulator", "gpu-fpga"),
    }
    backend_names = backend_groups.get(args.backend, (args.backend,))
    try:
        backend_versions = resolve_backend_versions(args.version, backend_names)
    except ValueError as error:
        parser.error(str(error))

    # Valida todos los casos antes de construir backends o contactar hardware.
    cases = []
    skipped = 0
    try:
        for path in case_paths:
            raw = json.loads(path.read_text(encoding="utf-8"))
            architecture = case_architecture(raw)
            if not args.cases and any(
                BACKEND_DEFINITIONS[name]["architecture"] != architecture
                for name in backend_names
            ):
                skipped += 1
                continue
            validate_compatibility(architecture, backend_names)
            # Las profundidades SIMT son parámetros del simulador: la FPGA las
            # tiene fijadas en el hardware y no puede reproducir el caso.
            if simulator_options(raw, architecture) and backend_names != ("gpu-simulator",):
                if not args.cases:
                    print(f"SKIP {raw.get('name', path)}: simulator_options requiere gpu-simulator")
                    skipped += 1
                    continue
                raise ValueError("simulator_options requiere --backend gpu-simulator")
            case = load_case(path)
            # Cada backend decide si el caso cabe en su mapa; los que no
            # publican `incompatibility` aceptan todo lo que valide load_case.
            reason = None
            for name in backend_names:
                check = getattr(BACKEND_DEFINITIONS[name]["module"],
                                "incompatibility", None)
                reason = check(case, backend_versions[name]) if check else None
                if reason:
                    reason = f"[{name}]: {reason}"
                    break
            if reason:
                if args.cases:
                    raise ValueError(reason)
                print(f"SKIP {case['name']} {reason}")
                skipped += 1
                continue
            cases.append((path, case))
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"ERROR {path}: {error}", file=sys.stderr)
        return 2
    if not cases:
        print("No se encontraron casos compatibles", file=sys.stderr)
        return 2

    backends = {}
    if "gpu-simulator" in backend_names:
        backends["gpu-simulator"] = GpuBackend(REPOSITORY, version=backend_versions["gpu-simulator"])
    if "cpu-simulator" in backend_names:
        backends["cpu-simulator"] = SimulatorBackend(
            REPOSITORY,
            version=backend_versions["cpu-simulator"],
        )
    upload_policy = board.UploadPolicy(
        allowed=not args.no_upload, assume_yes=args.yes
    )
    # Construir un backend FPGA comprueba la placa y, si hace falta y se
    # autoriza, carga el bitstream. Es el fallo más habitual del flujo con
    # hardware, así que merece un mensaje y no un volcado de pila.
    try:
        if "cpu-fpga" in backend_names:
            backends["cpu-fpga"] = FpgaBackend(
                REPOSITORY,
                port=args.port,
                serial_timeout=args.serial_timeout,
                version=backend_versions["cpu-fpga"],
                upload_policy=upload_policy,
            )
        if "gpu-fpga" in backend_names:
            backends["gpu-fpga"] = GpuFpgaBackend(
                REPOSITORY,
                port=args.port,
                serial_timeout=args.serial_timeout,
                version=backend_versions["gpu-fpga"],
                upload_policy=upload_policy,
            )
    except (board.BoardNotConnected, board.MonitorSilent,
            board.BitstreamMismatch) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    failures = 0
    durations: list[tuple[float, str, str]] = []
    started = time.monotonic()
    for path, case in cases:
        try:
            results = {}
            for backend_name, backend in backends.items():
                begun = time.monotonic()
                result = backend.run(
                    program=case["program"],
                    initial_memory=case["initial_memory"],
                    register_numbers=set(case["expected"]["registers"]),
                    memory_ranges=list(case["expected"]["memory"]),
                    max_instructions=case["max_instructions"],
                    timeout_seconds=case["timeout_seconds"],
                    **({"warp_config": case["warp_config"]} if case["architecture"] == "gpu" else {}),
                    **({"observation_fields": set(case["expected"]["observations"])}
                       if backend_name == "gpu-fpga" else {}),
                    **({
                        "trace": args.trace,
                        "trace_detail": args.trace_detail,
                        "trace_limit": args.trace_limit,
                        "trace_file": args.trace_file,
                        "simulator_options": case["simulator_options"],
                    } if backend_name == "gpu-simulator" else {}),
                )
                elapsed = time.monotonic() - begun
                durations.append((elapsed, case["name"], backend_name))
                results[backend_name] = result
                errors = compare_result(case, result, backend_name)
                # El tiempo solo se anota junto al caso cuando es alto, para no
                # ensuciar la salida de los casos rápidos.
                slow = f" ({elapsed:.1f}s)" if elapsed >= SLOW_CASE_SECONDS else ""
                if errors:
                    failures += 1
                    print(f"FAIL {case['name']} [{backend_name}]{slow}")
                    for error in errors:
                        print(f"  {error}")
                else:
                    print(f"PASS {case['name']} [{backend_name}]{slow}")

            if args.backend == 'gpu-both':
                left, right = results['gpu-simulator'], results['gpu-fpga']
                fields = case['expected']['observations']
                mismatch = any(left[field] != right[field] for field in ('halted', 'error', 'error_code', 'memory'))
                mismatch |= any(left['observations'].get(key, '<ausente>') != right['observations'].get(key, '<ausente>') for key in fields)
                if mismatch:
                    failures += 1
                    print(f"FAIL {case['name']} [diferencial GPU]: los estados observados no coinciden")
            if args.backend == 'both' and results["cpu-simulator"] != results["cpu-fpga"]:
                failures += 1
                print(f"FAIL {case['name']} [diferencial]")
                print("  El estado observado del simulador y la FPGA no coincide")
        except Exception as error:
            failures += 1
            print(f"ERROR {path}: {error}", file=sys.stderr)

    if args.durations and durations:
        print(f"\n{min(args.durations, len(durations))} ejecución(es) más lentas:")
        for elapsed, name, backend_name in sorted(durations, reverse=True)[:args.durations]:
            print(f"  {elapsed:7.2f}s  {name} [{backend_name}]")

    total = time.monotonic() - started
    print(f"{len(cases)} caso(s), {failures} fallo(s), "
          f"{skipped} omitido(s) por arquitectura o capacidades, {total:.1f}s")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
