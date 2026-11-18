#!/usr/bin/env python3
"""Barrido automatico de fase SDRAM para uno o varios bitstreams.

No programa nada sin --yes. --dry-run valida el plan sin abrir la placa.
Genera JSONL incremental y, al acabar, CSV, JSON y Markdown comparativos.

El prototipo de cada bitstream sale de su ruta (`38.fpga-.../reports/.../
hardware.bit` -> la 38), o de `--prototype` si el bitstream esta fuera del
repo. Hace falta por dos cosas: `board-upload` comprueba tras programar que el
monitor que responde es el de ese prototipo, y el protocolo serie se habla con
el `monitor.py` de ese prototipo, que no es igual en todos (la 38 va a
250 kbaudios y la 35-37 a 1 Mbaudio). Antes habia una copia de este script en
cada prototipo con el numero escrito a mano, y la de la 38 decia 35.
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
from tools.prototype import PrototypeResolutionError, resolve_prototype
from tools.run_board import load_monitor
from tools.mmio_map import MMIO_SDRAM_PHASES as PHASES
from tools.serial_ports import detect_port

STEP_PS = 625 / 3
ROOT = Path(__file__).resolve().parents[1]
BOARD_UPLOAD = ROOT / "tools" / "board-upload"


@dataclass(frozen=True)
class Bitstream:
    label: str
    path: Path
    prototype: Path | None = None


def bitstream_arg(value: str) -> Bitstream:
    """`NOMBRE=RUTA` o solo `RUTA`; sin nombre, el de la carpeta del build."""
    label, path = value.split("=", 1) if "=" in value else ("", value)
    if not path:
        raise argparse.ArgumentTypeError("RUTA no puede estar vacia")
    resolved = Path(path).expanduser().resolve()
    if resolved.is_dir():
        resolved = resolved / "hardware.bit"
    if "=" in value and not label:
        raise argparse.ArgumentTypeError("NOMBRE no puede estar vacio")
    return Bitstream(label or resolved.parent.name, resolved)


def prototype_of(path: Path, root: Path = ROOT) -> Path | None:
    """La carpeta de prototipo que contiene `path` (`N.nombre` justo bajo la raiz), o None."""
    try:
        parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return None
    if len(parts) < 2:
        return None
    top = root / parts[0]
    number = parts[0].split(".", 1)[0]
    return top if number.isdigit() and (top / "monitor.py").is_file() else None


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


def phase_status(client) -> dict[str, int | bool]:
    return client.phase_status()


def move(client, steps: int, timeout: float = 2.0) -> dict:
    return client.phase_move(steps, timeout)


def restore(client, target: int) -> None:
    """Mejor esfuerzo: no oculta una excepcion anterior durante el barrido."""
    try:
        current = phase_status(client)
        if current["locked"] and not current["busy"]:
            move_to(client, target)
    except Exception as error:
        print(f"AVISO: no se pudo restaurar la fase {target}: {error}",
              file=sys.stderr, flush=True)


def move_to(client, target: int) -> dict:
    return client.set_sdram_phase(target)


def test_patterns(address: int, length: int):
    yield "00", bytes(length)
    yield "ff", bytes([0xFF]) * length
    yield "address-xor-a5", bytes(((address + i) ^ 0xA5) & 0xFF for i in range(length))
    yield "55-aa", bytes(0x55 if i & 1 else 0xAA for i in range(length))


def probe(client, address: int, length: int,
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
    print(f"Programando {item.label} ({item.prototype.name}): {item.path}", flush=True)
    subprocess.run([sys.executable, str(BOARD_UPLOAD), "--prototype", str(item.prototype),
                    "--port", port, "--bitstream", str(item.path), "-y"],
                   cwd=ROOT, check=True)


def open_serial(port: str, timeout: float, baudrate: int):
    return serial.Serial(port, baudrate=baudrate, timeout=timeout,
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
        "prototypes": {item.label: item.prototype.name for item in items},
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="phase-sweep", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bitstream", action="append", type=bitstream_arg, required=True,
                        help="repetible: [NOMBRE=]RUTA al hardware.bit o a su carpeta de reports/")
    parser.add_argument("-p", "--prototype",
                        help="prototipo de los bitstreams que no esten dentro de una carpeta de prototipo")
    parser.add_argument("--port")
    parser.add_argument("--output", type=Path,
                        help="base de los informes (sin extension); por defecto "
                             "<prototipo>/reports/phase-sweep-<fecha> del primer bitstream")
    parser.add_argument("--address", type=lambda x: int(x, 0), default=0x0010_0000)
    parser.add_argument("--length", type=lambda x: int(x, 0), default=0x0001_0000)
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--phases", type=phases_arg, default=list(range(PHASES)),
                        help="p. ej. 0-20,44-47; por defecto 0-47")
    parser.add_argument("--restore-phase", type=int,
                        help="fase en la que se deja la placa al acabar (por defecto, la que "
                             "tenia el bitstream recien programado: la que lleva de fabrica)")
    parser.add_argument("--serial-timeout", type=float, default=2.0)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.length <= 0 or args.repetitions <= 0:
        parser.error("--length y --repetitions deben ser positivos")
    if args.restore_phase is not None and not 0 <= args.restore_phase < PHASES:
        parser.error("--restore-phase debe estar entre 0 y 47")
    labels = [item.label for item in args.bitstream]
    if len(labels) != len(set(labels)):
        parser.error("los nombres de bitstream deben ser unicos")
    missing = [str(item.path) for item in args.bitstream if not item.path.is_file()]
    if missing:
        parser.error("no existen: " + ", ".join(missing))
    fallback = None
    if args.prototype:
        try:
            fallback = resolve_prototype(args.prototype, ROOT)
        except PrototypeResolutionError as error:
            parser.error(str(error))
    items = []
    for item in args.bitstream:
        prototype = prototype_of(item.path) or fallback
        if prototype is None:
            parser.error(f"{item.path} no esta dentro de una carpeta de prototipo: usa --prototype")
        items.append(Bitstream(item.label, item.path, prototype))
    args.bitstream = items
    if args.output is None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        args.output = items[0].prototype / "reports" / f"phase-sweep-{stamp}"

    port = args.port or ("AUTO" if args.dry_run else detect_port())
    print(f"Puerto: {port}")
    print(f"Fases: {args.phases}; {args.repetitions} repeticion(es), "
          f"{args.length} bytes por patron")
    for item in args.bitstream:
        print(f"  {item.label} ({item.prototype.name}): {item.path}")
    print(f"Informes: {args.output}.*")
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
            monitor = load_monitor(item.prototype)
            with open_serial(port, args.serial_timeout, monitor.BAUDRATE) as connection:
                client = monitor.MonitorClient(connection)
                if not client.get_status().halted:
                    client.halt_cpu()
                    time.sleep(0.02)
                    if not client.get_status().halted:
                        raise RuntimeError("la CPU no se pudo detener")
                # Tras programar, el PLL puede tardar en enganchar y el primer
                # intento de aplicar la fase de version.json falla dejando `err`
                # pegajoso. Se espera al PLL y, si hace falta, un giro completo
                # (48 pasos, vuelve a la misma posicion) limpia el error.
                for _ in range(40):
                    initial = phase_status(client)
                    if initial["locked"] and initial["init_done"]:
                        break
                    time.sleep(0.25)
                if initial["err"] and not initial["busy"] and initial["locked"]:
                    client.write_word(monitor.PHASE_CTRL, 1 | (PHASES << 8))
                    for _ in range(40):
                        time.sleep(0.1)
                        initial = phase_status(client)
                        if not initial["busy"]:
                            break
                if (initial["busy"] or initial["err"] or not initial["locked"]
                        or not initial["init_done"]):
                    raise RuntimeError(f"estado inicial no valido: {initial}")
                # Sin --restore-phase se vuelve a la de fabrica de este bitstream.
                restore_to = initial["pos"] if args.restore_phase is None else args.restore_phase
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
                    restore(client, restore_to)

    reports(args.output, rows, args.bitstream, args)
    partial.unlink(missing_ok=True)
    print(f"Informes: {args.output.with_suffix('.json')}, "
          f"{args.output.with_suffix('.csv')}, {args.output.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
