"""Compila un programa en C con CPU y GPU a una imagen para el simulador (y la placa).

    mini-cc programa.c [otro.c|otro.s|otro.inc ...] [-o salida.bin] [--outdir DIR] [-I DIR]...
                       [-D NOMBRE[=VALOR]]... [--data ETIQUETA=FICHERO]... [--board] [--load [PROTOTIPO]] [--no-run]

Se compila lo que se pide y nada mas. Cada .c pasa por mini-lcc --no-crt; luego una sola llamada a mini-opt con
todos los .s, que los junta en `<programa>.opt.s` y optimiza el programa entero (intrinsecos, kernels...). Los demas
ficheros (.s, .asm, .inc: el runtime de la GPU `runtime/src/gpu_runtime.inc` y `bench.inc`, ensamblador a mano) no
se optimizan: se `.include`n tal cual detras del codigo, en el orden de la linea de ordenes, y sus simbolos cuentan
como usados desde fuera. `gpu.c` (que lleva `gpu_launch` y la pila de los kernels, `__gpu_stack`) y `string.c` (la biblioteca C minima,
`runtime/src/string.c`) son .c como los demas: se piden.
Los `static` de cada unidad pasan a `<nombre>.<unidad>` (`scope_statics`): dos unidades pueden tener el mismo.
-D define una macro en todas las unidades; mini-lcc ya define __LCC__ y __MINIGPU__.
Lo unico que se pone solo es el arranque (runtime/src/crt0.s), primero, cuando hay algun .c. Todo se ensambla con
mini-asm y queda en `--outdir`.
Con --board: el runtime que lanza con RUN (la 36 no tiene WARP_START) y los ciclos de CPU reales en
`bench_now()`; la salida se llama `<nombre>_board.bin`.
--data pega un fichero binario tras el codigo, con `.incbin`, bajo una etiqueta que el C declara con
`extern unsigned etiqueta[]`. Quien lo genera es quien llama, no esta herramienta.
--load sube la imagen a la placa (implica --board; PROTOTIPO por defecto 36) con la misma carga que
`board-load`: no comprueba el bitstream. --no-run la carga sin arrancarla.
Necesita u.lcc/build/rcc y un preprocesador de C (MSVC en Windows: lo busca mini-lcc).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(ROOT / "1.isa"))
sys.path.insert(0, str(TOOLS))
from msvc_env import ensure_msvc_environment  # noqa: E402
from mini_asm import assemble_bytes, write_hex  # noqa: E402
from runtime_dirs import ASM_INCLUDE_DIRS, C_INCLUDE_DIRS, SRC  # noqa: E402

CRT0 = SRC / "crt0.s"
GPU_C = SRC / "gpu.c"
# El runtime de la GPU, para quien llama desde Python: se pasa en `sources` como cualquier otro fichero.
GPU_RUNTIME = (GPU_C, SRC / "gpu_runtime.inc", SRC / "bench.inc")
INCLUDE_DIRS = ASM_INCLUDE_DIRS                 # para ensamblar: runtime/include y runtime/src
DEFAULT_OUTDIR = ROOT / "_build" / "c"


class BuildError(RuntimeError):
    pass


def run(*command: str) -> None:
    done = subprocess.run([sys.executable, *map(str, command)], capture_output=True, text=True)
    if done.returncode != 0:
        raise BuildError(f"{' '.join(map(str, command))}\n{done.stdout}{done.stderr}")


def lower_c(source: Path, outdir: Path, includes: tuple[Path, ...] = (), defines: tuple[str, ...] = (),
            fp32: bool = False) -> Path:
    """C -> .s sin arranque. `fp32`: float con FADD/FSUB/FMUL/FDIV (mini-lcc --fp32)."""
    outdir.mkdir(parents=True, exist_ok=True)
    plain = outdir / f"{source.stem}.s"
    flags = [arg for folder in (*C_INCLUDE_DIRS, *includes) for arg in ("-I", folder)]
    flags += [arg for define in defines for arg in ("-D", define)]
    run(TOOLS / "mini-lcc", source, "--no-crt", *(["--fp32"] if fp32 else []), *flags, "-o", plain)
    scope_statics(plain)
    return plain


SYMBOL_RE = re.compile(r"[A-Za-z_.$@][A-Za-z0-9_.$@]*")
LABEL_RE = re.compile(r"^\s*([A-Za-z_.$@][A-Za-z0-9_.$@]*):")
COMMON_RE = re.compile(r"^\s*\.(?:l?comm)\s+([A-Za-z_.$@][A-Za-z0-9_.$@]*)", re.IGNORECASE)
COMPILER_LOCAL_RE = re.compile(r"^L\.\d+$")


def scope_statics(plain: Path) -> None:
    """Los `static` de C de una unidad pasan a `<nombre>.<unidad>`.

    El ensamblador junta los `.s` con `.include` y solo hace privadas de cada fichero las `L.n` de lcc: dos
    unidades con un `static` del mismo nombre (`min2`, `weight`...) chocarian, o en el caso de un `.comm`, se
    fundirian sin aviso. En C, lo que lcc no marca con `.globl` es `static`, y por tanto de la unidad: se le pone
    el nombre de la unidad, que es unico (`build` lo comprueba). El ensamblador escrito a mano no pasa por aqui:
    alli una etiqueta sin `.globl` si se usa desde otros ficheros."""
    lines = plain.read_text(encoding="utf-8").splitlines()
    exported, defined = set(), set()
    for line in lines:
        code = line.split(";", 1)[0]
        words = code.split()
        if len(words) >= 2 and words[0].lower() in (".globl", ".global"):
            exported.update(name.strip() for name in " ".join(words[1:]).split(","))
        match = LABEL_RE.match(code) or COMMON_RE.match(code)
        if match and not COMPILER_LOCAL_RE.match(match.group(1)):
            defined.add(match.group(1))
    private = defined - exported
    if not private:
        return
    tag = re.sub(r"[^A-Za-z0-9_]", "_", plain.stem)

    def rename(text: str) -> str:
        return SYMBOL_RE.sub(lambda m: f"{m.group(0)}.{tag}" if m.group(0) in private else m.group(0), text)

    out = []
    for line in lines:
        code, sep, comment = line.partition(";")
        label = LABEL_RE.match(code)
        head = ""
        if label:                                       # `nombre:` y lo que siga en la linea
            head, code = rename(code[:label.end()]), code[label.end():]
        stripped = code.lstrip()
        if stripped:                                    # la instruccion o directiva no se toca; sus operandos si
            word = stripped.split(None, 1)[0]
            start = len(code) - len(stripped) + len(word)
            code = code[:start] + rename(code[start:])
        out.append(head + code + sep + comment)
    plain.write_text("\n".join(out) + "\n", encoding="utf-8")


def share_runtime(plains: list[Path]) -> None:
    """Una sola copia del runtime del compilador entre todas las unidades.

    mini-lcc pega al final de cada `.s` las rutinas de runtime que usa (soft-float, 64 bits...) con `.globl`:
    con dos unidades que usan `float`, `__mulsf3` quedaria definido dos veces. Se queda la primera definicion;
    en las demas unidades la etiqueta pasa a `<nombre>.dup.<unidad>`, sin `.globl`, y las llamadas de esa
    unidad van a la primera. La copia ya no la nombra nadie y `mini-opt --whole-program` la borra. Solo los
    nombres que empiezan por `__`, reservados a la implementacion en C: dos unidades con la misma funcion de
    usuario siguen siendo un error del ensamblador."""
    seen: set[str] = set()
    for plain in plains:
        lines = plain.read_text(encoding="utf-8").splitlines()
        exported = set()
        for line in lines:
            words = line.split(";", 1)[0].split()
            if len(words) >= 2 and words[0].lower() in (".globl", ".global"):
                exported.update(name.strip() for name in " ".join(words[1:]).split(","))
        runtime = {name for name in exported if name.startswith("__")}
        repeated = runtime & seen
        seen |= runtime
        if not repeated:
            continue
        tag = re.sub(r"[^A-Za-z0-9_]", "_", plain.stem)
        out = []
        for line in lines:
            code = line.split(";", 1)[0]
            words = code.split()
            if len(words) >= 2 and words[0].lower() in (".globl", ".global"):
                names = [name.strip() for name in " ".join(words[1:]).split(",")]
                kept = [name for name in names if name not in repeated]
                if kept:
                    out.append(f"{words[0]} {', '.join(kept)}")
                continue
            label = LABEL_RE.match(code)
            if label and label.group(1) in repeated:
                line = line.replace(f"{label.group(1)}:", f"{label.group(1)}.dup.{tag}:", 1)
            out.append(line)
        plain.write_text("\n".join(out) + "\n", encoding="utf-8")


def optimize_s(plains: list[Path], foreign: list[Path], optimized: Path) -> Path:
    """Los .s de todas las unidades -> un solo .s con los pases de mini-opt, que los junta antes de optimizar.
    `foreign`: lo que se ensambla aparte y puede nombrar sus simbolos (el arranque, el runtime): un simbolo que
    nombran no se da por privado del programa, y las funciones que ninguna de esas raices alcanza se borran."""
    passes = os.environ.get("MINI_OPT_PASSES")       # para comparar (opt_stats.py); por defecto, todos
    # por defecto, mini-opt solo saca de un bucle la carga de una global que ningun puntero puede alcanzar. Con
    # MINI_OPT_NOALIAS=1 basta que el kernel no la escriba (--assume-noalias), aunque su direccion escape
    noalias = ["--assume-noalias"] if os.environ.get("MINI_OPT_NOALIAS") == "1" else []
    refs = [arg for path in foreign for arg in ("--extern-refs", path)]
    run(TOOLS / "mini-opt", *plains, "-o", optimized, "--whole-program", *noalias, *refs,
        *(["--passes", passes] if passes is not None else []))
    return optimized


def image_name(program: Path, board: bool = False) -> str:
    return program.stem + ("_board" if board else "")


def wrapper_path(program: Path, board: bool = False, outdir: Path | None = None) -> Path:
    """El .asm que une el arranque, el programa y los ficheros a mano: lo que `build` ensambla."""
    return (outdir or DEFAULT_OUTDIR) / f"{image_name(program, board)}.asm"


def build(program: Path, output: Path | None = None, board: bool = False,
          outdir: Path | None = None, includes: tuple[Path, ...] = (),
          data: tuple[tuple[str, Path], ...] = (), sources: tuple[Path, ...] = (),
          defines: tuple[str, ...] = (), fp32: bool = False) -> Path:
    """`data`: (etiqueta, fichero) de cada binario que se pega tras el codigo. `program` da el nombre a la
    imagen y suele llevar `main`. `sources`: el resto de ficheros, en orden: los .c se compilan y optimizan
    juntos, los demas (.s, .asm, .inc) se incluyen sin tocar tras el codigo. Con algun .c se pone el arranque."""
    program = program.resolve()
    outdir = (outdir or DEFAULT_OUTDIR).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    output = output or outdir / f"{image_name(program, board)}.bin"
    files = (program, *map(Path.resolve, sources))
    units = [path for path in files if path.suffix == ".c"]
    by_hand = [path for path in files if path.suffix != ".c"]
    stems = [unit.stem for unit in units]
    if len(set(stems)) != len(stems):     # cada unidad deja <stem>.s en outdir: no pueden repetirse
        raise BuildError(f"dos unidades con el mismo nombre: {', '.join(map(str, units))}")
    startup = [CRT0] if units else []
    compiled = []
    if units:
        # Cada unidad es un proceso aparte (cl + rcc): en paralelo. En Windows el entorno de MSVC se carga
        # aqui una vez; los mini-lcc hijos lo heredan en vez de lanzar vcvars32 cada uno (~1 s).
        if sys.platform == "win32":
            ensure_msvc_environment()
        with ThreadPoolExecutor(max_workers=min(len(units), os.cpu_count() or 1)) as pool:
            plains = list(pool.map(lambda unit: lower_c(unit, outdir, includes, defines, fp32), units))
        share_runtime(plains)
        compiled = [optimize_s(plains, startup + by_hand, outdir / f"{program.stem}.opt.s")]
    blobs = "".join(f'.align 4\n{label}:\n.incbin "{Path(path).resolve().as_posix()}"\n' for label, path in data)
    wrapper = wrapper_path(program, board, outdir)
    wrapper.write_text(
        "; generado por mini-cc\n" + (".define BOARD\n" if board else "")
        + "".join(f'.include "{path.as_posix()}"\n' for path in (*startup, *compiled, *by_hand)) + blobs,
        encoding="utf-8")
    image = assemble_bytes(wrapper.read_text(encoding="utf-8"), wrapper.parent, wrapper.name,
                           INCLUDE_DIRS)
    output.write_bytes(image)
    write_hex(image, output.with_suffix(".hex"))
    return output


def parse_data(text: str) -> tuple[str, Path]:
    label, separator, path = text.partition("=")
    if not separator or not label.isidentifier() or not path:
        raise argparse.ArgumentTypeError(f"--data espera ETIQUETA=FICHERO, no {text!r}")
    return label, Path(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("program", type=Path, help="el .c con main y los kernels (da el nombre a la imagen)")
    parser.add_argument("sources", nargs="*", type=Path, metavar="otro",
                        help=".c (se compilan y optimizan con el programa) o .s/.asm/.inc (se incluyen sin tocar, "
                             "detras del codigo y en este orden)")
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--outdir", type=Path, help=f"carpeta de los intermedios (por defecto {DEFAULT_OUTDIR})")
    parser.add_argument("-I", dest="includes", action="append", type=Path, default=[], metavar="DIR",
                        help="carpeta extra para #include (repetible); runtime/include va siempre")
    parser.add_argument("-D", dest="defines", action="append", default=[], metavar="NOMBRE[=VALOR]",
                        help="define una macro en todas las unidades (repetible)")
    parser.add_argument("--data", action="append", type=parse_data, default=[], metavar="ETIQUETA=FICHERO",
                        help="pega un binario tras el codigo con esa etiqueta (repetible)")
    parser.add_argument("--board", action="store_true", help="para la placa 36 (RUN y ciclos reales)")
    parser.add_argument("--load", nargs="?", const="36", metavar="PROTOTIPO",
                        help="sube la imagen a la placa tras compilar (implica --board; por defecto la 36)")
    parser.add_argument("--no-run", action="store_true", help="con --load, la carga pero no la arranca")
    parser.add_argument("--fp32", action="store_true",
                        help="float con FADD/FSUB/FMUL/FDIV (capability fp32, solo la 38) en vez de softfloat")
    args = parser.parse_args(argv)
    board = args.board or args.load is not None
    try:
        out = build(args.program, args.output, board, args.outdir, tuple(args.includes), tuple(args.data),
                    tuple(args.sources), tuple(args.defines), args.fp32)
    except BuildError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"{out} ({out.stat().st_size} bytes)")
    if args.load is None:
        return 0
    sys.path.insert(0, str(TOOLS))
    import run_board
    return run_board.main_load(["-p", args.load, "--program", str(out)] + (["--no-run"] if args.no_run else []))


if __name__ == "__main__":
    raise SystemExit(main())
