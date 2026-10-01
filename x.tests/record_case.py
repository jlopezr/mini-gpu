#!/usr/bin/env python3
"""Rellena el bloque `expect` de un caso con lo que el simulador observa.

Para convertir un programa que ya funciona en un caso sin teclear a mano cada
registro. El caso se escribe sin `expect` (o con `"expect": {}`): nombre,
programa, `requires`, `run_until`, `max_instructions`, y para GPU un
`warp_config`. Esto lo ejecuta en el simulador y escribe lo que ve.

    python record_case.py cases-cpu/demos/fastpath-hit/test.json
    python record_case.py cases-gpu/demos/smoke/test.json --frame

Lo grabado es una INSTANTANEA del simulador, no un oraculo independiente: dice
que el programa hace hoy lo que hacia ayer, no que lo que hace sea correcto. Su
valor llega al correrlo contra la placa (`--backend both` / `gpu-both`), donde
el RTL tiene que coincidir con el simulador. Revisa el resultado antes de
darlo por bueno; para los casos donde existe un modelo de referencia
independiente (`reference.py`), ese es el que manda.

`--tighten` ajusta `max_instructions` al doble de lo que el programa necesito de
verdad: un caso que se desboca se corta enseguida en vez de agotar el limite
holgado con el que se escribio.

`--frame` captura el frame tras `run_until.swap` y lo guarda en
`expected/frame.bin` junto al caso.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "x.tests")]

import run_tests as rt  # noqa: E402
from backends.gpu_simulator import GpuBackend  # noqa: E402
from backends.simulator import SimulatorBackend  # noqa: E402

CPU_REGISTERS = range(1, 32)


def _hex(value: int) -> str:
    return f"0x{value & 0xFFFFFFFF:08x}"


def record(path: Path, frame: bool, tighten: bool = False) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.setdefault("expect", {})
    architecture = raw["architecture"]
    if isinstance(architecture, list):
        raise SystemExit("un caso compartido no se graba: elige una familia")
    case = rt.load_case(path, architecture)
    video = None
    if case["run_until"] or frame:
        video = {"run_until_swap": (case["run_until"] or {}).get("swap"),
                 "capture_frame": frame}
    expect = dict(raw["expect"])

    if architecture == "cpu":
        result = SimulatorBackend(ROOT).run(
            program=case["program"], initial_memory=case["initial_memory"],
            register_numbers=set(CPU_REGISTERS), memory_ranges=[],
            max_instructions=case["max_instructions"],
            timeout_seconds=case["timeout_seconds"], stdin=case["stdin"],
            **({"video": video} if video else {}))
        expect.update(halted=result["halted"], error=result["error"],
                      error_code=f"0x{result['error_code']:02x}")
        if not case["run_until"]:
            expect["pc"] = result["pc"]
        expect["registers"] = {f"R{n}": _hex(v) for n, v in sorted(result["registers"].items())
                               if v}
    else:
        warps = case["warp_config"]["warps"]
        lanes = case["warp_config"].get("warp_size", 8)
        result = GpuBackend(ROOT).run(
            program=case["program"], initial_memory=case["initial_memory"],
            register_numbers=set(), memory_ranges=[],
            max_instructions=case["max_instructions"],
            timeout_seconds=case["timeout_seconds"], warp_config=case["warp_config"],
            stdin=case["stdin"], trace=False, trace_detail=False, trace_limit=None,
            trace_file=None, simulator_options=case["simulator_options"],
            **({"video": video} if video else {}))
        expect.update(halted=result["halted"], error=result["error"],
                      error_code=f"0x{result['error_code']:02x}")
        observed = result["observations"]
        expect["instructions_executed"] = observed["instructions_executed"]
        expect["warps"] = {}
        for w in warps:
            key = str(w["id"])
            prefix = f"warp[{key}]"
            # Los hilos 0 y el ultimo: bastan para ver una divergencia sin
            # volcar 8 hilos por warp.
            registros = {}
            for lane in sorted({0, lanes - 1}):
                registros[str(lane)] = {
                    f"R{n}": observed[f"{prefix}.lane[{lane}].R{n}"]
                    for n in CPU_REGISTERS if observed[f"{prefix}.lane[{lane}].R{n}"]}
            expect["warps"][key] = {
                "pc": observed[f"{prefix}.pc"],
                "active_mask": observed[f"{prefix}.active_mask"],
                "instructions_executed": observed[f"{prefix}.instructions_executed"],
                "registers": registros,
            }

    if frame:
        if result.get("video") is None or "frame" not in result["video"]:
            raise SystemExit("el simulador no devolvio frame: hace falta `video` en requires")
        destino = path.parent / "expected"
        destino.mkdir(exist_ok=True)
        (destino / "frame.bin").write_bytes(result["video"]["frame"])
        expect["frame"] = {"file": "expected/frame.bin"}
    raw["expect"] = expect
    if tighten:
        contadas = (result["instructions"] if architecture == "cpu"
                    else result["observations"]["instructions_executed"])
        raw["max_instructions"] = max(1000, 2 * contadas)
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("test_json", type=Path, nargs="+")
    parser.add_argument("--frame", action="store_true",
                        help="captura el frame tras run_until.swap")
    parser.add_argument("--tighten", action="store_true",
                        help="max_instructions = el doble de lo observado (minimo 1000)")
    args = parser.parse_args()
    for path in args.test_json:
        path = path.resolve()
        grabado = record(path, args.frame, args.tighten)
        path.write_text(json.dumps(grabado, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"grabado {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
