"""`tools/mini_link.py`: el paso entre el `.s` de mini-lcc y mini-asm.

Los `.s` de entrada son salida real de `mini-lcc` (copiada), asi que no hace falta
MSVC para correr la suite. Se comprueba:

  - que el troceado en funciones es fiel (reensamblar el `.s` troceado da los mismos
    bytes que el original);
  - el grafo de flujo y la vida de registros;
  - el pase `intrinsics`: `LI r,__gpu_tid ; LOAD d,r,0` pasa a `GETTID d`, y se rechaza
    lo que no se puede reescribir con seguridad;
  - la union: una sola `_start`, un solo `.comm`, simbolos entre unidades, errores.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "1.isa"))

from mini_asm import assemble_bytes  # noqa: E402
from tools.mini_link import (  # noqa: E402
    LinkError, build_cfg, link, liveness, parse_unit, pass_intrinsics, render_unit, run)

# Salida real de mini-lcc para:
#   extern volatile int __gpu_tid;
#   void k_memset(int *dst, int value, int n) { int i; for (i = __gpu_tid; i < n; i += 64) dst[i] = value; }
#   int k_max(int a, int b) { return a > b ? a : b; }
KERNELS = """\
.text
.globl _start
_start:
LI R30, __stack+8192
JAL R31, main
HALT
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
.comm __stack,8192
"""

HOST = """\
.text
.globl _start
_start:
LI R30, __stack+8192
JAL R31, main
HALT
.globl main
.text
.align 4
main:
LI R1, k_memset
JR R31
.extern k_memset 4
.bss
.comm __stack,8192
"""


def functions(unit):
    return {f.name: f for f in unit.functions()}


class ParseTest(unittest.TestCase):
    def test_functions_are_split_with_their_headers(self):
        unit = parse_unit(KERNELS, "k.s", "gpu")
        fns = functions(unit)
        self.assertEqual(list(fns), ["_start", "k_memset", "k_max"])
        self.assertEqual([h.text for h in fns["k_memset"].header],
                         [".globl k_memset", ".text", ".align 4"])
        # las etiquetas internas de lcc se quedan dentro de la funcion
        labels = [l.name for l in fns["k_memset"].body if l.kind == "label"]
        self.assertEqual(labels, ["k_memset", "L.2", "L.3", "L.5", "L.1"])

    def test_declarations_are_not_part_of_the_last_function(self):
        unit = parse_unit(KERNELS, "k.s", "gpu")
        last = functions(unit)["k_max"].body[-1]
        self.assertEqual(last.render(), "JR R31")

    def test_reassembling_the_split_unit_gives_the_same_image(self):
        # autocontenido: sin `main` ni la variable especial, que solo el pase resuelve
        source = KERNELS.replace("JAL R31, main", "JAL R31, k_max").replace(
            "LI R12, __gpu_tid", "LI R12, __stack").replace(".extern __gpu_tid 4\n", "")
        unit = parse_unit(source, "k.s", "gpu")
        self.assertEqual(assemble_bytes(render_unit(unit)), assemble_bytes(source))


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.fn = functions(parse_unit(KERNELS, "k.s", "gpu"))["k_max"]

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
        unit = parse_unit(KERNELS, "k.s", "gpu")
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
        unit = parse_unit(source, "k.s", "gpu")
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
        with self.assertRaisesRegex(LinkError, "sigue vivo"):
            pass_intrinsics(parse_unit(source, "k.s", "gpu"), {})

    def test_taking_the_address_is_rejected(self):
        source = """\
.text
.globl k
k:
LI R1, __gpu_tid
JR R31
.extern __gpu_tid 4
"""
        with self.assertRaisesRegex(LinkError, "variable entera"):
            pass_intrinsics(parse_unit(source, "k.s", "gpu"), {})


class LinkTest(unittest.TestCase):
    def write(self, folder, name, text):
        path = Path(folder) / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_link_cpu_and_gpu(self):
        with tempfile.TemporaryDirectory() as temp:
            host = self.write(temp, "host.s", HOST)
            gpu = self.write(temp, "gpu.s", KERNELS)
            text = run([(host, "cpu"), (gpu, "gpu")])
        self.assertEqual(text.count("_start:"), 1)
        self.assertEqual(text.count(".comm __stack"), 1)
        self.assertNotIn(".extern", text)
        self.assertIn("GETTID R29", text)
        image = assemble_bytes(text)
        self.assertGreater(len(image), 0)

    def test_undefined_symbol_is_an_error(self):
        with tempfile.TemporaryDirectory() as temp:
            host = self.write(temp, "host.s", HOST)
            with self.assertRaisesRegex(LinkError, "k_memset"):
                run([(host, "cpu")])

    def test_duplicate_symbol_is_an_error(self):
        with tempfile.TemporaryDirectory() as temp:
            host = self.write(temp, "host.s", HOST)
            gpu = self.write(temp, "gpu.s", KERNELS)
            with self.assertRaisesRegex(LinkError, "repetido"):
                run([(host, "cpu"), (gpu, "gpu"), (gpu, "gpu")])

    def test_cpu_unit_without_passes_is_left_alone(self):
        with tempfile.TemporaryDirectory() as temp:
            gpu = self.write(temp, "gpu.s", KERNELS)
            text = run([(gpu, "cpu")], allow_undefined=True)
        self.assertIn("LI R12, __gpu_tid", text)    # sin el pase, el `.s` sigue igual


if __name__ == "__main__":
    unittest.main()
