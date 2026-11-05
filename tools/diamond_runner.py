#!/usr/bin/env python3
"""Sintetiza un prototipo con Lattice Diamond (Synplify Pro) en `<proto>/.diamond/`.

Reutiliza los .v/.sv/.vh y el .lpf del prototipo y su `apio.ini` (top-module, board).
Todo lo de Diamond (proyecto .ldf, impl1/, logs, informes) queda dentro de `.diamond/`,
igual que apio deja lo suyo en `_build/`.\nEl nombre lleva punto a proposito: apio busca .v/.sv/.lpf con glob("**/..."), que salta las\ncarpetas ocultas; con `_diamond/` apio veria los .lpf y las copias .sv y fallaria. El proyecto se regenera en cada ejecucion.
"""
from __future__ import annotations

import argparse
import configparser
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.prototype import find_repo_root, resolve_prototype

DEFAULT_DIAMOND = Path(os.environ.get("DIAMOND_DIR", r"D:\diamond\3.14"))
DEVICES = {"ulx3s-85f": "LFE5U-85F-6BG381C"}
HDL_SUFFIXES = {".v", ".sv"}
IMPL = "impl1"
MODULE_RE = re.compile(r'^\s*module\b', re.MULTILINE)
INCLUDE_RE = re.compile(r'^\s*`include\s+"([^"]+)"', re.MULTILINE)


def source_files(proto: Path) -> list[Path]:
    """HDL sintetizable del prototipo: todo .v/.sv que no sea un testbench."""
    files = [p for p in sorted(proto.iterdir())
             if p.suffix in HDL_SUFFIXES and not p.stem.endswith("_tb")]
    # Un .v que otro incluye con `include (util.v: funciones fuera de modulo) no es una
    # fuente aparte: compilarlo solo da error de sintaxis. Yosys lo ve via el include.
    included = {m.group(1) for p in files
                for m in INCLUDE_RE.finditer(p.read_text(encoding="utf-8", errors="replace"))}
    return [p for p in files if p.name not in included]


def stage_sources(files: list[Path], out: Path) -> list[Path]:
    """Copia las fuentes a `.diamond/src/` con extension .sv.

    Yosys acepta SystemVerilog dentro de los .v (p. ej. funciones fuera de modulo en util.v),
    pero Synplify solo pasa a `-vlog_std sysv` por el tipo de fuente, que sale de la extension.
    Los ficheros sin `module` (util.v) van primero, porque los demas los usan.
    """
    dest = out / "src"
    dest.mkdir(exist_ok=True)
    texts = {p: p.read_text(encoding="utf-8", errors="replace") for p in files}
    ordered = sorted(files, key=lambda p: (MODULE_RE.search(texts[p]) is not None, p.name))
    staged = []
    for p in ordered:
        target = dest / (p.stem + ".sv")
        target.write_text(texts[p], encoding="utf-8")
        staged.append(target)
    return staged


def read_apio(proto: Path, env: str | None = None) -> dict[str, str]:
    """Opciones del `apio.ini`: `[common]` mas `[env:<env>]` (que sustituye a las de common).

    Sin `env` se usa `default-env` de `[apio]`; un prototipo sin entornos usa su unica
    seccion, como antes. El caso con entornos es 13.hdmi (tres tops en una carpeta)."""
    cfg = configparser.ConfigParser()
    cfg.read(proto / "apio.ini", encoding="utf-8")
    env = env or (cfg["apio"].get("default-env") if cfg.has_section("apio") else None)
    if env is None or not cfg.has_section(f"env:{env}"):
        section = cfg[cfg.sections()[0]]
        return {k: v for k, v in section.items()}
    merged: dict[str, str] = {}
    if cfg.has_section("common"):
        merged.update(cfg["common"])
    merged.update(cfg[f"env:{env}"])
    return merged


def tcl_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def write_tcl(proto: Path, out: Path, top: str, device: str, sources: list[Path],
              lpf: Path, name: str, synth: str, strategy: list[str]) -> Path:
    strategy_cmds = "\n".join(
        f"prj_strgy set_value -strategy Strategy1 {{{item}}}" for item in strategy)
    src =" ".join(f'"{tcl_path(p)}"' for p in sources)
    steps = [
        ("Synthesis", ""),
        ("Translate", ""),
        ("Map", ""),
        ("PAR", ""),
        ("PAR", " -task PARTrace"),
        ("Export", " -task Bitgen"),
    ]
    run = "\n".join(
        f'puts "== prj_run {s}"\nprj_run {s} -impl {IMPL}{extra}' for s, extra in steps)
    text = f"""# Generado por tools/diamond_runner.py; no editar (se regenera).
if {{[catch {{
prj_project new -name "{name}" -impl "{IMPL}" -dev {device} -synthesis "{synth}"
prj_src add {src}
# prj_project new crea un {name}.lpf vacio que deshabilita cualquier otro y no se
# deja quitar: se sobrescribe con el del prototipo.
file copy -force "{tcl_path(lpf)}" "{tcl_path(lpf.parent / (name + '.lpf'))}"
prj_impl option top "{top}"
# apio define SYNTHESIZE (el RTL lo usa para elegir PLL real frente a modelo de simulacion).
prj_impl option VERILOG_DIRECTIVES "SYNTHESIZE"
{strategy_cmds}
prj_impl option {{include path}} "{tcl_path(proto)}"
prj_project save
{run}
prj_project save
}} err]}} {{
    puts "ERROR: $err"
    exit 1
}}
exit 0
"""
    script = out / "build.tcl"
    script.write_text(text, encoding="utf-8")
    return script


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prototype", required=True, help="numero, nombre o ruta")
    parser.add_argument("--synth", choices=("synplify", "lse"), default="synplify")
    parser.add_argument("--diamond", type=Path, default=DEFAULT_DIAMOND,
                        help="raiz de Diamond (o variable DIAMOND_DIR)")
    parser.add_argument("--strategy", action="append", default=[], metavar="CLAVE=VALOR",
                        help="propiedad de Strategy1 (repetible), p. ej. par_place_iterator=10; "
                             "los nombres son los tclid de Diamond (data/base.stf)")
    parser.add_argument("--env", help="entorno del apio.ini (por defecto, su default-env)")
    parser.add_argument("--tcl-only", action="store_true", help="genera build.tcl y no lo lanza")
    parser.add_argument("--keep", action="store_true", help="no borrar .diamond/ antes de generar")
    args = parser.parse_args()

    root = find_repo_root()
    proto = resolve_prototype(args.prototype, root)
    apio = read_apio(proto, args.env)
    board = apio.get("board", "")
    if board not in DEVICES:
        print(f"error: board '{board}' sin dispositivo Diamond conocido ({', '.join(DEVICES)})")
        return 2
    top = apio.get("top-module", "top")
    lpfs = sorted(proto.glob("*.lpf"))
    if len(lpfs) != 1:
        print(f"error: se esperaba un .lpf en {proto}, hay {len(lpfs)}")
        return 2

    out = proto / ".diamond"
    if out.exists() and not args.keep:
        shutil.rmtree(out)
    out.mkdir(exist_ok=True)
    lpf = out / lpfs[0].name
    shutil.copyfile(lpfs[0], lpf)  # Diamond puede reescribir el .lpf: nunca el original

    name = "hardware"
    staged = stage_sources(source_files(proto), out)
    script = write_tcl(proto, out, top, DEVICES[board], staged, lpf, name, args.synth,
                      args.strategy)
    print(f"{proto.name}: {len(source_files(proto))} fuentes, top={top}, {args.synth}")
    if args.tcl_only:
        print(script)
        return 0

    pnmainc = args.diamond / "bin" / "nt64" / "pnmainc.exe"
    if not pnmainc.is_file():
        print(f"error: no existe {pnmainc}")
        return 2
    env = os.environ.copy()
    env["FOUNDRY"] = str(args.diamond / "ispfpga")
    env["PATH"] = str(args.diamond / "bin" / "nt64") + os.pathsep + env["PATH"]
    log = out / "diamond.log"
    started = datetime.now()
    t0 = time.monotonic()
    pnr_started = None  # el tcl imprime "== prj_run Translate" al acabar Synplify
    with log.open("w", encoding="utf-8") as fh:
        proc = subprocess.Popen([str(pnmainc), script.name], cwd=out, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace")
        for line in proc.stdout:
            if pnr_started is None and line.startswith("== prj_run Translate"):
                pnr_started = time.monotonic()
            sys.stdout.write(line)
            fh.write(line)
        code = proc.wait()
    # pnmainc sale con 0 aunque un prj_* haya dado "ERROR - ..." sin lanzar excepcion.
    errors = [l for l in log.read_text(encoding="utf-8").splitlines() if l.startswith("ERROR")]
    if errors and code == 0:
        code = 1

    elapsed = (datetime.now() - started).total_seconds()
    phases = None
    if pnr_started is not None:
        from tools.build_report import phase_times
        phases = phase_times(pnr_started - t0, elapsed)

    bit = out / IMPL / f"{name}_{IMPL}.bit"
    if code == 0 and bit.is_file():
        shutil.copyfile(bit, out / "hardware.bit")
    if (out / IMPL).is_dir():
        from tools.diamond_report import archive
        folder = archive(proto, out, started, elapsed, code,
                         [str(pnmainc), script.name], args.strategy, phases=phases)
        print(f"Informe: {folder / 'summary.txt'}")
    if code == 0 and bit.is_file():
        print(f"OK: {out / 'hardware.bit'}")
        return 0
    print(f"FALLO (codigo {code}); ver {log}")
    return code or 1


if __name__ == "__main__":
    sys.exit(main())
