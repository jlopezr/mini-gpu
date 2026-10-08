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
    OptError, build_cfg, liveness, optimize, parse_unit, pass_intrinsics, pass_kernels, pass_ssy,
    render_unit)

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


KERNEL_S = """\
.text
.globl __kernel_k
.align 4
__kernel_k:
ADD R15, R1, R0
ADD R14, R3, R0
SHLI R12, R15, 2
ADD R12, R12, R14
STORE R15, R12, 0
JR R31
"""


def kernel_body(source, name="__kernel_k", **kwargs):
    unit = parse_unit(source, "k.s")
    pass_kernels(unit, {})
    return [l.render() for l in functions(unit)[name].body if l.kind == "instr"]


class KernelsTest(unittest.TestCase):
    def test_entry_loads_only_the_parameters_read(self):
        body = kernel_body(KERNEL_S)
        # lee R1 y R3 (parametros 0 y 2); R2 no se carga
        self.assertEqual(body[:3], ["GETARG R5", "LOAD R1, R5, 8", "LOAD R3, R5, 16"])

    def test_a_kernel_that_does_not_touch_the_stack_gets_no_stack(self):
        body = kernel_body(KERNEL_S)
        self.assertFalse(any("R30" in text or "__gpu_stack" in text for text in body))

    def test_the_frame_that_only_saved_preserved_registers_is_dropped(self):
        source = KERNEL_S.replace("ADD R15, R1, R0\n", """\
ADDI R30, R30, -16
STORE R28, R30, 0
STORE R29, R30, 4
ADD R15, R1, R0
""").replace("JR R31", "LOAD R28, R30, 0\nLOAD R29, R30, 4\nADDI R30, R30, 16\nJR R31")
        unit = parse_unit(source, "k.s")
        stats = {}
        pass_kernels(unit, stats)
        body = [l.render() for l in functions(unit)["__kernel_k"].body if l.kind == "instr"]
        self.assertEqual(stats["kernels.frames"], 1)
        self.assertFalse(any("R30" in text for text in body))
        self.assertEqual(body[-1], "EXIT")

    def test_a_kernel_that_really_uses_the_stack_keeps_it_and_gets_the_lane_stack(self):
        # un local en el marco (STORE de un registro que no es preservado): la pila se usa
        source = KERNEL_S.replace("ADD R15, R1, R0\n", """\
ADDI R30, R30, -16
STORE R1, R30, 4
ADD R15, R1, R0
""").replace("JR R31", "ADDI R30, R30, 16\nJR R31")
        body = kernel_body(source)
        self.assertEqual(body[:5], ["GETTID R5", "MOVI R6, 512", "MUL R5, R5, R6",
                                    "LI R30, __gpu_stack+512", "ADD R30, R30, R5"])
        self.assertIn("ADDI R30, R30, -16", body)
        self.assertEqual(body[-1], "EXIT")

    def test_return_becomes_exit(self):
        body = kernel_body(KERNEL_S)
        self.assertEqual(body[-1], "EXIT")
        self.assertNotIn("JR R31", body)

    def test_immediate_shifts_use_a_free_register(self):
        body = kernel_body(KERNEL_S)
        self.assertNotIn("SHLI", " ".join(body))
        index = next(i for i, text in enumerate(body) if text.startswith("SHL "))
        self.assertTrue(body[index - 1].startswith("MOVI R"))
        temp = body[index - 1].split()[1].rstrip(",")
        self.assertIn(f"R{temp[1:]}", body[index])
        self.assertNotIn(temp, ("R12", "R15"))         # ni el destino ni el origen

    def test_other_functions_are_left_alone(self):
        source = KERNEL_S + ".globl host\n.align 4\nhost:\nSHLI R1, R1, 2\nJR R31\n"
        body = kernel_body(source, "host")
        self.assertEqual(body, ["SHLI R1, R1, 2", "JR R31"])

    def test_an_instruction_the_gpu_lacks_is_an_error(self):
        for op in ("REM R1, R1, R2", "SLT R1, R1, R2", "MULHI R1, R1, R2", "JAL R31, other"):
            source = KERNEL_S.replace("STORE R15, R12, 0", op + "\nSTORE R15, R12, 0")
            with self.assertRaisesRegex(OptError, "no ejecuta"):
                pass_kernels(parse_unit(source, "k.s"), {})

    def test_more_than_four_parameters_is_an_error(self):
        source = """\
.text
.globl __kernel_k
__kernel_k:
ADDI R30, R30, -16
STORE R29, R30, 0
LOAD R5, R30, 16
STORE R5, R1, 0
LOAD R29, R30, 0
ADDI R30, R30, 16
JR R31
"""
        with self.assertRaisesRegex(OptError, "parametros como maximo"):
            pass_kernels(parse_unit(source, "k.s"), {})

    def test_nthreads_reads_the_block_and_multiplies(self):
        source = """\
.text
.globl __kernel_k
__kernel_k:
LI R12, __gpu_nthreads
LOAD R28, R12, 0
ADD R1, R28, R0
JR R31
.extern __gpu_nthreads 4
"""
        unit = parse_unit(source, "k.s")
        pass_intrinsics(unit, {})
        body = [l.render() for l in functions(unit)["__kernel_k"].body if l.kind == "instr"]
        self.assertEqual(body[:4], ["GETARG R28", "LOAD R12, R28, 0", "LOAD R28, R28, 4",
                                    "MUL R28, R28, R12"])
        assemble_bytes(render_unit(unit))


def ssy_body(source):
    unit = parse_unit(source, "k.s")
    pass_ssy(unit, {})
    return [l.render() for l in functions(unit)["__kernel_k"].body]


IF_ELSE = """\
.text
.globl __kernel_k
__kernel_k:
GETTID R5
ANDI R6, R5, 1
BEQ R6, R0, L.1
ADDI R7, R5, 3
BRA L.2
L.1:
ADDI R7, R5, 100
L.2:
STORE R7, R5, 0
EXIT
"""

LOOP = """\
.text
.globl __kernel_k
__kernel_k:
GETTID R5
BRA L.5
L.2:
STORE R5, R5, 0
ADDI R5, R5, 64
L.5:
BLT R5, R3, L.2
L.1:
EXIT
"""


class SsyTest(unittest.TestCase):
    def test_if_else_gets_an_ssy_before_the_branch_with_the_merge_point_as_join(self):
        body = ssy_body(IF_ELSE)
        branch = body.index("BEQ R6, R0, L.1")
        self.assertEqual(body[branch - 1], "SSY L.2")
        self.assertEqual(sum(l.startswith("SSY") for l in body), 1)

    def test_loop_opens_its_region_once_before_the_loop(self):
        body = ssy_body(LOOP)
        self.assertEqual(body.index("SSY L.1") + 1, body.index("BRA L.5"))   # en el preheader
        self.assertEqual(sum(l.startswith("SSY") for l in body), 1)          # ninguno dentro

    def test_a_branch_on_uniform_values_needs_no_ssy(self):
        # R3 sale de los parametros (nunca de GETTID/GETLANE): todas las lanes lo ven igual
        source = LOOP.replace("GETTID R5", "MOVI R5, 0")
        self.assertFalse(any(l.startswith("SSY") for l in ssy_body(source)))

    def test_what_is_defined_under_a_divergent_branch_varies_afterwards(self):
        # R7 vale cosas distintas segun la lane; el segundo salto, que solo mira R7, tambien diverge
        source = IF_ELSE.replace("STORE R7, R5, 0", "BEQ R7, R0, L.3\nSTORE R7, R5, 0\nL.3:")
        body = ssy_body(source)
        self.assertEqual(sum(l.startswith("SSY") for l in body), 2)

    def test_ssy_all_treats_every_conditional_branch_as_divergent(self):
        import tools.mini_opt as opt
        source = LOOP.replace("GETTID R5", "MOVI R5, 0")
        opt.SSY_ALL = True
        try:
            body = ssy_body(source)
        finally:
            opt.SSY_ALL = False
        self.assertTrue(any(l.startswith("SSY") for l in body))

    def test_functions_that_are_not_kernels_are_left_alone(self):
        source = IF_ELSE.replace("__kernel_k", "host")
        unit = parse_unit(source, "k.s")
        pass_ssy(unit, {})
        self.assertFalse(any(l.render().startswith("SSY") for l in unit.lines()))

    def test_output_assembles(self):
        for source in (IF_ELSE, LOOP):
            unit = parse_unit(source, "k.s")
            pass_ssy(unit, {})
            assemble_bytes(render_unit(unit))


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
