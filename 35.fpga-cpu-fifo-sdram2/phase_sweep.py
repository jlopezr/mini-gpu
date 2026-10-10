#!/usr/bin/env python3
"""Barrido automatico de fase SDRAM para uno o varios bitstreams.

No programa nada sin --yes. --dry-run valida el plan sin abrir la placa.
Genera JSONL incremental y, al acabar, CSV, JSON y Markdown comparativos.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import serial
from monitor import BAUDRATE, MonitorClient, detect_port

PHASE_CTRL = 0x8002_0000
PHASE_STATUS = 0x8002_0004
PHASES = 48
STEP_PS = 625 / 3
ROOT = Path(__file__).resolve().parents[1]
BOARD_UPLOAD = ROOT / "tools" / "board-upload"


@dataclass(frozen=True)
class Bitstream:
    label: str
    path: Path


def bitstream_arg(value: str) -> Bitstream:
    if "=" not in value:
        raise argparse.ArgumentTypeError("usa NOMBRE=RUTA")
    label, path = value.split("=", 1)
    if not label or not path:
        raise argparse.ArgumentTypeError("NOMBRE y RUTA no pueden estar vacios")
    return Bitstream(label, Path(path).expanduser().resolve())


def phases_arg(value: str) -> list[int]:
    phases: set[int] = set()
    for item in value.split(","):
        if "-" in item:
            first, last = (int(part, 0) for part in item.split("-", 1))
            if first > last:
                raise argparse.ArgumentTypeError(f"rango descendente: {item}")
            phases.update(range(first, last + 1))
        else:
            phases.add(int(item, 0))
    if not phases or min(phases) < 0 or max(phases) >= PHASES:
        raise argparse.ArgumentTypeError("las fases deben estar entre 0 y 47")
    return sorted(phases)


def phase_status(client: MonitorClient) -> dict[str, int | bool]:
    value = client.read_word(PHASE_STATUS)
    return {"busy": bool(value & 1), "err": bool(value & 2),
            "locked": bool(value & 4), "init_done": bool(value & 8),
            "pos": (value >> 8) & 0x3F}


def move(client: MonitorClient, steps: int, timeout: float = 2.0) -> dict:
    if not 1 <= steps <= PHASES:
        raise ValueError("steps debe estar entre 1 y 48")
    before = phase_status(client)
    expected_pos = (int(before["pos"]) + steps) % PHASES
    client.write_word(PHASE_CTRL, 1 | (steps << 8))
    deadline = time.monotonic() + timeout
    saw_busy = False
    while time.monotonic() < deadline:
        current = phase_status(client)
        saw_busy |= bool(current["busy"])
        # Un movimiento dura microsegundos y una consulta por UART tarda mucho
        # mas: es normal no llegar a observar BUSY=1. POS es Gray en el CDC y
        # solo cambia al completar cada paso, asi que tambien sirve de ack.
        completed = (saw_busy or int(current["pos"]) == expected_pos)
        if completed and not current["busy"]:
            if current["err"] or not current["locked"] or not current["init_done"]:
                raise RuntimeError(f"fallo al mover fase: {current}")
            return current
        time.sleep(0.002)
    raise TimeoutError("el cambio de fase no termino")


def restore(client: MonitorClient, target: int) -> None:
    """Mejor esfuerzo: no oculta una excepcion anterior durante el barrido."""
    try:
        current = phase_status(client)
        if current["locked"] and not current["busy"]:
            move_to(client, target)
    except Exception as error:
        print(f"AVISO: no se pudo restaurar la fase {target}: {error}",
              file=sys.stderr, flush=True)


def move_to(client: MonitorClient, target: int) -> dict:
    current = phase_status(client)
    if current["busy"] or current["err"] or not current["locked"]:
        raise RuntimeError(f"estado de fase no valido: {current}")
    delta = (target - int(current["pos"])) % PHASES
    return move(client, delta) if delta else current


def test_patterns(address: int, length: int):
    yield "00", bytes(length)
    yield "ff", bytes([0xFF]) * length
    yield "address-xor-a5", bytes(((address + i) ^ 0xA5) & 0xFF for i in range(length))
    yield "55-aa", bytes(0x55 if i & 1 else 0xAA for i in range(length))


def probe(client: MonitorClient, address: int, length: int,
          repetitions: int) -> dict:
    errors = 0
    failures = []
    for repetition in range(repetitions):
        for name, expected in test_patterns(address, length):
            client.write_memory(address, expected)
            actual = client.read_memory(address, length)
            for offset, (wanted, got) in enumerate(zip(expected, actual)):
                if wanted != got:
                    errors += 1
                    if len(failures) < 8:
                        failures.append({"repetition": repetition, "pattern": name,
                                         "address": address + offset,
                                         "expected": wanted, "actual": got})
    return {"errors": errors, "failures": failures}


def program(item: Bitstream, port: str) -> None:
    print(f"Programando {item.label}: {item.path}", flush=True)
    subprocess.run([sys.executable, str(BOARD_UPLOAD), "--prototype", "35",
                    "--port", port, "--bitstream", str(item.path), "-y"],
                   cwd=ROOT, check=True)


def open_serial(port: str, timeout: float):
    return serial.Serial(port, baudrate=BAUDRATE, timeout=timeout,
                         write_timeout=timeout, xonxoff=False, rtscts=False,
                         dsrdtr=False)


def cyclic_windows(valid: set[int]) -> list[list[int]]:
    if not valid:
        return []
    if len(valid) == PHASES:
        return [list(range(PHASES))]
    outside = next(pos for pos in range(PHASES) if pos not in valid)
    windows, current = [], []
    for offset in range(1, PHASES + 1):
        pos = (outside + offset) % PHASES
        if pos in valid:
            current.append(pos)
        elif current:
            windows.append(current)
            current = []
    if current:
        windows.append(current)
    return windows


def recommendation(common: set[int]) -> int | None:
    windows = cyclic_windows(common)
    if not windows:
        return None
    best = max(windows, key=len)
    return best[(len(best) - 1) // 2]


def reports(base: Path, rows: list[dict], items: list[Bitstream], args) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    with base.with_suffix(".jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    fields = ("bitstream", "phase", "delay_ps", "errors", "passed")
    with base.with_suffix(".csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row[key] for key in fields} for row in rows)

    valid = {item.label: {row["phase"] for row in rows
                          if row["bitstream"] == item.label and row["passed"]}
             for item in items}
    common = set.intersection(*valid.values()) if valid else set()
    complete = args.phases == list(range(PHASES))
    chosen = recommendation(common) if complete else None
    document = {
        "parameters": {"address": args.address, "length": args.length,
                       "repetitions": args.repetitions, "phases": args.phases,
                       "restore_phase": args.restore_phase},
        "bitstreams": {item.label: str(item.path) for item in items},
        "valid_phases": {key: sorted(value) for key, value in valid.items()},
        "common_valid_phases": sorted(common), "sweep_complete": complete,
        "recommended_phase": chosen,
        "rows": rows,
    }
    base.with_suffix(".json").write_text(json.dumps(document, indent=2,
                                                     sort_keys=True), encoding="utf-8")
    lines = ["# Barrido de fase SDRAM", "", "## Parametros", "",
             f"- Direccion: `0x{args.address:08x}`", f"- Longitud: {args.length} bytes",
             f"- Repeticiones: {args.repetitions}", "", "## Resultados", "",
             "| Bitstream | Fase | Retardo (ps) | Errores | Resultado |",
             "|---|---:|---:|---:|:---:|"]
    for row in rows:
        verdict = "PASS" if row["passed"] else "FAIL"
        lines.append(f"| {row['bitstream']} | {row['phase']} | {row['delay_ps']:.1f} "
                     f"| {row['errors']} | {verdict} |")
    lines += ["", "## Ventana comun", "", f"Fases comunes: `{sorted(common)}`.", ""]
    if not complete:
        lines.append("Barrido parcial: no se calcula una fase recomendada.")
    elif chosen is None:
        lines.append("No hay fase valida comun.")
    else:
        lines.append(f"Fase recomendada: **{chosen}** ({chosen * STEP_PS:.1f} ps).")
    base.with_suffix(".md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bitstream", action="append", type=bitstream_arg, required=True,
                        help="repetible: NOMBRE=RUTA_AL_HARDWARE.BIT")
    parser.add_argument("--port")
    parser.add_argument("--output", type=Path, default=Path("phase-sweep"))
    parser.add_argument("--address", type=lambda x: int(x, 0), default=0x0010_0000)
    parser.add_argument("--length", type=lambda x: int(x, 0), default=0x0001_0000)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--phases", type=phases_arg, default=list(range(PHASES)),
                        help="p. ej. 0-20,44-47; por defecto 0-47")
    parser.add_argument("--restore-phase", type=int, default=12)
    parser.add_argument("--serial-timeout", type=float, default=2.0)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.length <= 0 or args.repetitions <= 0:
        parser.error("--length y --repetitions deben ser positivos")
    if not 0 <= args.restore_phase < PHASES:
        parser.error("--restore-phase debe estar entre 0 y 47")
    labels = [item.label for item in args.bitstream]
    if len(labels) != len(set(labels)):
        parser.error("los nombres de bitstream deben ser unicos")
    missing = [str(item.path) for item in args.bitstream if not item.path.is_file()]
    if missing:
        parser.error("no existen: " + ", ".join(missing))

    port = args.port or ("AUTO" if args.dry_run else detect_port())
    print(f"Puerto: {port}")
    print(f"Fases: {args.phases}; {args.repetitions} repeticion(es), "
          f"{args.length} bytes por patron")
    for item in args.bitstream:
        print(f"  {item.label}: {item.path}")
    if args.dry_run:
        print("DRY-RUN: no se programa ni se abre el puerto serie")
        return 0
    if not args.yes:
        parser.error("falta --yes; no se programara la placa")

    rows = []
    partial = args.output.with_suffix(".partial.jsonl")
    partial.parent.mkdir(parents=True, exist_ok=True)
    with partial.open("w", encoding="utf-8") as raw:
        for item in args.bitstream:
            program(item, port)
            with open_serial(port, args.serial_timeout) as connection:
                client = MonitorClient(connection)
                if not client.get_status().halted:
                    client.halt_cpu()
                    time.sleep(0.02)
                    if not client.get_status().halted:
                        raise RuntimeError("la CPU no se pudo detener")
                initial = phase_status(client)
                if (initial["busy"] or initial["err"] or not initial["locked"]
                        or not initial["init_done"]):
                    raise RuntimeError(f"estado inicial no valido: {initial}")
                try:
                    for phase in args.phases:
                        current = move_to(client, phase)
                        started = time.monotonic()
                        try:
                            result = probe(client, args.address, args.length,
                                           args.repetitions)
                            exception = None
                        except Exception as error:  # conserva el resto del barrido
                            result = {"errors": -1, "failures": []}
                            exception = f"{type(error).__name__}: {error}"
                        row = {"bitstream": item.label, "bitstream_path": str(item.path),
                               "phase": phase, "delay_ps": phase * STEP_PS,
                               "errors": result["errors"],
                               "passed": result["errors"] == 0 and exception is None,
                               "failures": result["failures"], "exception": exception,
                               "status": current,
                               "elapsed_seconds": time.monotonic() - started}
                        rows.append(row)
                        raw.write(json.dumps(row, sort_keys=True) + "\n")
                        raw.flush()
                        print(f"{item.label} fase {phase:02d}: "
                              f"{'PASS' if row['passed'] else 'FAIL'} "
                              f"({row['errors']} errores)", flush=True)
                finally:
                    restore(client, args.restore_phase)

    reports(args.output, rows, args.bitstream, args)
    partial.unlink(missing_ok=True)
    print(f"Informes: {args.output.with_suffix('.json')}, "
          f"{args.output.with_suffix('.csv')}, {args.output.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
