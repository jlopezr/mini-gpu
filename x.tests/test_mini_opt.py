"""`tools/mini_opt.py`: filtro entre el `.s` de mini-lcc y mini-asm.

Los `.s` de entrada son salida real de `mini-lcc --no-crt` (copiada), asi que no hace
falta MSVC para correr la suite. Se comprueba:

  - que el troceado en funciones es fiel (reensamblar el `.s` troceado da los mismos
    bytes que el original);
  - el grafo de flujo y la vida de registros;
  - el pase `intrinsics`: `LI r,__gpu_tid ; LOAD d,r,0` pasa a `GETTID d`, y se rechaza
    lo que no se puede reescribir con seguridad;
  - el filtro entero y su salida junto al `crt0` y un anfitrion, por `.include`.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "1.isa"))

from mini_asm import assemble_bytes  # noqa: E402
from tools.mini_opt import (  # noqa: E402
    OptError, build_cfg, liveness, optimize, parse_unit, pass_intrinsics, render_unit)

RUNTIME = ROOT / "1.isa" / "runtime"

# Salida real de `mini-lcc --no-crt` para:
#   extern volatile int __gpu_tid;
#   void k_memset(int *dst, int value, int n) { int i; for (i = __gpu_tid; i < n; i += 64) dst[i] = value; }
#   int k_max(int a, int b) { return a > b ? a : b; }
KERNELS = """\
.text
.globl k_memset
.text
.align 4
k_memset:
ADDI R30, R30, -16
STORE R29, R30, 0
ADD R15, R1, R0
ADD R14, R2, R0
ADD R13, R3, R0
LI R12, __gpu_tid
LOAD R29, R12, 0
BRA L.5
L.2:
SHLI R12, R29, 2
ADD R12, R12, R15
STORE R14, R12, 0
L.3:
ADDI R29, R29, 64
L.5:
BLT R29, R13, L.2
L.1:
LOAD R29, R30, 0
ADDI R30, R30, 16
JR R31
.globl k_max
.align 4
k_max:
ADD R15, R1, R0
ADD R14, R2, R0
BGE R14, R15, L.9
ADD R1, R15, R0
BRA L.10
L.9:
ADD R1, R14, R0
L.10:
JR R31
.extern __gpu_tid 4
.bss
"""

# Un anfitrion compilado con `--no-crt` que tambien usa L.1 y L.2
HOST = """\
.text
.globl main
.align 4
main:
LI R1, 7
LI R2, 3
BLT R1, R2, L.2
JR R31
L.2:
MOVI R1, 0
JR R31
.bss
"""


def functions(unit):
    return {f.name: f for f in unit.functions()}


class ParseTest(unittest.TestCase):
    def test_functions_are_split_with_their_headers(self):
        unit = parse_unit(KERNELS, "k.s")
        fns = functions(unit)
        self.assertEqual(list(fns), ["k_memset", "k_max"])
        self.assertEqual([h.text for h in fns["k_memset"].header],
                         [".text", ".globl k_memset", ".text", ".align 4"])
        self.assertEqual([h.text for h in fns["k_max"].header], [".globl k_max", ".align 4"])
        # las etiquetas internas de lcc se quedan dentro de la funcion
        labels = [l.name for l in fns["k_memset"].body if l.kind == "label"]
        self.assertEqual(labels, ["k_memset", "L.2", "L.3", "L.5", "L.1"])

    def test_declarations_are_not_part_of_the_last_function(self):
        unit = parse_unit(KERNELS, "k.s")
        last = functions(unit)["k_max"].body[-1]
        self.assertEqual(last.render(), "JR R31")

    def test_reassembling_the_split_unit_gives_the_same_image(self):
        # autocontenido: sin la variable especial, que solo el pase resuelve
        source = KERNELS.replace("LI R12, __gpu_tid", "LI R12, k_max").replace(
            ".extern __gpu_tid 4\n", "")
        unit = parse_unit(source, "k.s")
        self.assertEqual(assemble_bytes(render_unit(unit)), assemble_bytes(source))


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.fn = functions(parse_unit(KERNELS, "k.s"))["k_max"]

    def test_basic_blocks_and_edges(self):
        blocks = build_cfg(self.fn)
        # entrada | BRA L.10 | L.9 | L.10
        self.assertEqual(len(blocks), 4)
        self.assertEqual(blocks[0].succ, [2, 1])        # BGE: salto a L.9 y caida
        self.assertEqual(blocks[1].succ, [3])           # BRA L.10
        self.assertEqual(blocks[2].succ, [3])

    def test_return_value_is_live_at_the_end(self):
        blocks = build_cfg(self.fn)
        live_out = liveness(blocks)
        # R1 se lee en el JR (valor de retorno): vivo a la salida de las ramas
        self.assertIn(1, live_out[1])
        self.assertIn(1, live_out[2])
        self.assertNotIn(15, live_out[3])


class IntrinsicsTest(unittest.TestCase):
    def test_gettid_replaces_the_load_of_the_magic_variable(self):
        unit = parse_unit(KERNELS, "k.s")
        stats = {}
        pass_intrinsics(unit, stats)
        text = render_unit(unit)
        self.assertEqual(stats["intrinsics"], 1)
        self.assertIn("GETTID R29", text)
        self.assertNotIn("__gpu_tid", text)         # tampoco el `.extern`

    def test_each_getid_and_bar(self):
        source = """\
.text
.globl k
.align 4
k:
LI R5, __gpu_lane
LOAD R6, R5, 0
LI R5, __gpu_lwarp
LOAD R7, R5, 0
LI R5, __gpu_arg
LOAD R8, R5, 0
LI R5, __gpu_bar
STORE R0, R5, 0
EXIT
.extern __gpu_lane 4
.extern __gpu_lwarp 4
.extern __gpu_arg 4
.extern __gpu_bar 4
"""
        unit = parse_unit(source, "k.s")
        pass_intrinsics(unit, {})
        body = [l.render() for l in functions(unit)["k"].body if l.kind == "instr"]
        self.assertEqual(body, ["GETLANE R6", "GETLWARP R7", "GETARG R8", "BAR", "EXIT"])
        assemble_bytes(render_unit(unit))               # y el ensamblador lo acepta

    def test_address_register_still_live_is_rejected(self):
        source = """\
.text
.globl k
k:
LI R5, __gpu_tid
LOAD R6, R5, 0
ADD R1, R5, R6
JR R31
.extern __gpu_tid 4
"""
        with self.assertRaisesRegex(OptError, "sigue vivo"):
            pass_intrinsics(parse_unit(source, "k.s"), {})

    def test_taking_the_address_is_rejected(self):
        source = """\
.text
.globl k
k:
LI R1, __gpu_tid
JR R31
.extern __gpu_tid 4
"""
        with self.assertRaisesRegex(OptError, "variable entera"):
            pass_intrinsics(parse_unit(source, "k.s"), {})


class FilterTest(unittest.TestCase):
    def test_optimize_applies_the_default_pass(self):
        stats = {}
        text = optimize(KERNELS, stats=stats)
        self.assertEqual(stats["intrinsics"], 1)
        self.assertIn("GETTID R29", text)

    def test_no_passes_leaves_the_text_alone(self):
        text = optimize(KERNELS, passes=[])
        self.assertIn("LI R12, __gpu_tid", text)

    def test_unknown_pass_is_an_error(self):
        with self.assertRaisesRegex(OptError, "desconocido"):
            optimize(KERNELS, passes=["no-existe"])

    def test_output_assembles_with_crt0_and_a_host_that_reuses_the_labels(self):
        """crt0 + anfitrion + kernels, por `.include`: sin `_start` ni `.comm` repetidos
        y con las mismas `L.n` en los dos ficheros."""
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            (temp / "host.s").write_text(HOST, encoding="utf-8")
            (temp / "kernels.s").write_text(optimize(KERNELS), encoding="utf-8")
            source = '.include "crt0.s"\n.include "host.s"\n.include "kernels.s"\n'
            image = assemble_bytes(source, temp, "prog.asm", (RUNTIME,))
        self.assertGreater(len(image), 0)

    def test_command_line_writes_the_output_file(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            (temp / "k.s").write_text(KERNELS, encoding="utf-8")
            done = subprocess.run([sys.executable, str(ROOT / "tools" / "mini-opt"), str(temp / "k.s"),
                                   "-o", str(temp / "k.opt.s"), "--stats"],
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("GETTID R29", (temp / "k.opt.s").read_text(encoding="utf-8"))
            self.assertIn("intrinsics", done.stderr)


if __name__ == "__main__":
    unittest.main()
