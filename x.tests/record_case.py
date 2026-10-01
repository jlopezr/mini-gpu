#!/usr/bin/env python3
"""Rellena el bloque `expect` de un caso con lo que el simulador observa.

Para convertir un programa que ya funciona en un caso sin teclear a mano cada
registro. El caso se escribe sin `expect` (o con `"expect": {}`): nombre,
programa, `requires`, `run_until`, `max_instructions`, y para GPU un
`warp_config`. Esto lo ejecuta en el simulador y escribe lo que ve.

    python record_case.py cases-cpu/demos/fastpath-hit/test.json
    python record_case.py cases-gpu/demos/smoke/test.json --frame
    python record_case.py cases-gpu/simt/exit/x/test.json --all-lanes --zeros

En GPU solo graba, por defecto, las lanes 0 y la ultima de cada warp y omite los
registros a cero. `--all-lanes` y `--zeros` lo amplian cuando el caso trata de
QUE lane hace algo (un salto que solo toma la 4) o de que algo NO se ejecuto.

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


def record(path: Path, frame: bool, tighten: bool = False, allow_error: bool = False,
           all_lanes: bool = False, zeros: bool = False) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.setdefault("expect", {})
    architecture = raw["architecture"]
    if isinstance(architecture, list):
        raise SystemExit("un caso compartido no se graba: elige una familia")
    case = rt.load_case(path, architecture)
    video = None
    # Lo mismo que decide el runner: sin `run_until`, `expect.video` ni frame, el
    # simulador no lleva dispositivo de video y cualquier acceso MMIO es un error.
    if case["run_until"] or frame or case["expected"]["video"]:
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
        # Con `run_until` la parada es asincrona: la CPU se para donde pille, y el
        # PC y los registros de ese instante dependen de la velocidad del
        # arnes, no del programa. Lo unico estable es el frame. (El runner ya
        # prohibe `expect.pc` junto a `run_until` por lo mismo; los registros
        # tienen el mismo problema y no los comprueba nadie, asi que no se
        # graban: en la placa fallarian siempre.)
        if not case["run_until"]:
            expect["pc"] = result["pc"]
            expect["registers"] = {f"R{n}": _hex(v)
                                   for n, v in sorted(result["registers"].items()) if v}
        else:
            expect.pop("registers", None)
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
        # Mismo motivo que en CPU: con `run_until` la parada es asincrona y ni
        # las instrucciones ni el estado de los warps en ese instante son del
        # programa. En la placa fallarian siempre; el runner los rechaza.
        warps = [] if case["run_until"] else warps
        if not case["run_until"]:
            expect["instructions_executed"] = observed["instructions_executed"]
        expect["warps"] = {}
        for w in warps:
            key = str(w["id"])
            prefix = f"warp[{key}]"
            # Los hilos 0 y el ultimo: bastan para ver una divergencia sin
            # volcar 8 hilos por warp. Con --all-lanes se vuelcan todos, que es
            # lo que hace falta cuando solo una lane intermedia toma el salto.
            registros = {}
            volcadas = range(lanes) if all_lanes else sorted({0, lanes - 1})
            # Lo normal es omitir los ceros (casi todos los registros lo son).
            # Pero «R3 vale 0 en esta lane y 7 en las demas» es justo la prueba
            # de que una lane no ejecuto algo, y sin el cero no se comprueba.
            # Con --zeros se graban tambien los ceros de los registros que valen
            # algo en alguna lane del warp.
            usados = {n for n in CPU_REGISTERS
                      if any(observed[f"{prefix}.lane[{l}].R{n}"] for l in range(lanes))}
            for lane in volcadas:
                registros[str(lane)] = {
                    f"R{n}": observed[f"{prefix}.lane[{lane}].R{n}"]
                    for n in CPU_REGISTERS
                    if observed[f"{prefix}.lane[{lane}].R{n}"] or (zeros and n in usados)}
            expect["warps"][key] = {
                "pc": observed[f"{prefix}.pc"],
                "active_mask": observed[f"{prefix}.active_mask"],
                "instructions_executed": observed[f"{prefix}.instructions_executed"],
                "registers": registros,
            }
        if not expect["warps"]:
            del expect["warps"]

    if frame:
        if result.get("video") is None or "frame" not in result["video"]:
            raise SystemExit("el simulador no devolvio frame: hace falta `video` en requires")
        destino = path.parent / "expected"
        destino.mkdir(exist_ok=True)
        (destino / "frame.bin").write_bytes(result["video"]["frame"])
        expect["frame"] = {"file": "expected/frame.bin"}
    # Un error del simulador NO se graba como lo esperado: puede ser el simulador
    # el que no llega (no tiene el bloque de contadores GPU, ni la ventana de un
    # periferico), no el programa el que falla. `demo-mmio-selftest` se grabo
    # asi, con un ERROR_MEMORY_ACCESS del simulador, y la placa --que si tiene el
    # hardware-- lo ejecutaba limpio: el caso exigia el fallo.
    if expect["error"] and not allow_error:
        raise SystemExit(
            f"el simulador termino con error (codigo {expect['error_code']}); no se graba. "
            "Si el caso trata justo de ese error, usa --allow-error; si no, el programa "
            "necesita algo que el simulador no tiene: declara esa capacidad en `requires` "
            "y escribe `expect` a mano.")
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
    parser.add_argument("--allow-error", action="store_true",
                        help="grabar aunque el simulador termine con error")
    parser.add_argument("--all-lanes", action="store_true",
                        help="GPU: volcar todas las lanes de cada warp, no solo la 0 y la ultima")
    parser.add_argument("--zeros", action="store_true",
                        help="GPU: grabar tambien los ceros de los registros que valen algo "
                             "en alguna lane del warp")
    args = parser.parse_args()
    for path in args.test_json:
        path = path.resolve()
        grabado = record(path, args.frame, args.tighten, args.allow_error,
                         args.all_lanes, args.zeros)
        path.write_text(json.dumps(grabado, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"grabado {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
