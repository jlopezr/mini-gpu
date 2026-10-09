"""`tools/mini_opt/` (paquete): filtro entre el `.s` de mini-lcc y mini-asm.

Los `.s` de entrada son salida real de `mini-lcc --no-crt` (copiada), asi que no hace
falta MSVC para correr la suite. Se comprueba:

  - que el troceado en funciones es fiel (reensamblar el `.s` troceado da los mismos
    bytes que el original);
  - el grafo de flujo y la vida de registros;
  - el pase `intrinsics`: `LI r,__gpu_tid ; LOAD d,r,0` pasa a `GETTID d`, y se rechaza
    lo que no se puede reescribir con seguridad;
  - el filtro entero y su salida junto al `crt0` y un anfitrion, por `.include`.
"""

import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "1.isa"))
sys.path.insert(0, str(ROOT / "2.cpu-sim-func"))

from mini_asm import assemble_bytes  # noqa: E402
from minicpu_sim import CPU  # noqa: E402
from tools.mini_opt import (  # noqa: E402
    OptError, build_cfg, liveness, optimize, parse_unit, pass_intrinsics, pass_kernels, pass_ssy,
    render_unit)
from tools.mini_opt.cli import main as optimize_main  # noqa: E402
from tools.mini_opt.passes import licm as licm_module  # noqa: E402

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

    def test_softfloat_renamed_local_labels_stay_in_the_function(self):
        source = """\
.text
.globl __addsf3
__addsf3:
BEQ R1, R0, __sf.2
MOVI R1, 42
BRA __sf.1
__sf.2:
MOVI R1, 7
__sf.1:
JR R31
"""
        unit = parse_unit(source, "softfloat.s")
        fns = functions(unit)
        self.assertEqual(list(fns), ["__addsf3"])
        labels = [line.name for line in fns["__addsf3"].body if line.kind == "label"]
        self.assertEqual(labels, ["__addsf3", "__sf.2", "__sf.1"])
        optimized = optimize(source, ["constprop", "copyprop"])
        self.assertIn("MOVI R1, 42", optimized)
        self.assertIn("MOVI R1, 7", optimized)

    def test_backend_at_labels_stay_inside_opaque_helper(self):
        source = """\
.text
__mini_memcpy:
BEQ R7, R0, @fin
@bucle:
ADDI R7, R7, -1
BNE R7, R0, @bucle
@fin:
JR R31
"""
        unit = parse_unit(source, "runtime.s")
        fns = functions(unit)
        self.assertEqual(list(fns), ["__mini_memcpy"])
        self.assertTrue(fns["__mini_memcpy"].opaque)
        self.assertEqual(optimize(source), source)

    def test_private_abi_call_makes_the_caller_opaque(self):
        for call in ("JAL R31, __mini_memcpy", "JAL R15, __mini_udivmod64"):
            source = f".text\nf:\nMOVI R7, 12\n{call}\nADD R1, R7, R0\nJR R31\n"
            fn = functions(parse_unit(source, "runtime-caller.s"))["f"]
            self.assertTrue(fn.opaque)
            self.assertEqual(optimize(source), source)

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
        temp = body[1].split()[1].rstrip(",")                  # el registro libre que se haya elegido
        self.assertNotIn(temp, ("R28", "R1"))
        self.assertEqual(body[:4], ["GETARG R28", f"LOAD {temp}, R28, 0", "LOAD R28, R28, 4",
                                    f"MUL R28, R28, {temp}"])
        assemble_bytes(render_unit(unit))

    def test_one_loaded_address_serves_several_reads_even_across_blocks(self):
        """lcc carga la direccion de la variable una vez y la reutiliza (a veces antes de un bucle)."""
        source = """\
.text
.globl __kernel_k
__kernel_k:
LI R15, __gpu_arg
LOAD R14, R15, 0
BRA L.2
L.1:
LOAD R13, R15, 0
ADD R14, R14, R13
L.2:
BLT R14, R3, L.1
EXIT
.extern __gpu_arg 4
"""
        unit = parse_unit(source, "k.s")
        stats = {}
        pass_intrinsics(unit, stats)
        body = [l.render() for l in functions(unit)["__kernel_k"].body if l.kind == "instr"]
        self.assertEqual(stats["intrinsics"], 2)
        self.assertEqual(body.count("GETARG R14") + body.count("GETARG R13"), 2)
        self.assertFalse(any("R15" in text or "__gpu_arg" in text for text in body))   # y el LI desaparece
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
        from tools.mini_opt.passes import ssy as opt
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


def lines_of(text: str) -> list[str]:
    return [l.strip() for l in text.splitlines() if l.strip()]


class JumpsTest(unittest.TestCase):
    def test_a_branch_to_a_label_that_only_jumps_goes_straight_to_the_target(self):
        out = optimize(".text\nf:\nBEQ R1, R0, L.3\nADDI R2, R2, 1\nL.3:\nBRA L.4\nL.4:\nJR R31\n", ["jumps"])
        self.assertIn("BEQ R1, R0, L.4", lines_of(out))

    def test_a_jump_to_the_next_line_is_dropped(self):
        stats = {}
        out = optimize(".text\nf:\nADDI R2, R2, 1\nBRA L.1\nL.1:\nJR R31\n", ["jumps"], stats=stats)
        self.assertNotIn("BRA L.1", lines_of(out))
        self.assertEqual(stats["jumps.removed"], 1)


LICM_LOOP = """.text
.globl f
f:
MOVI R16, 0
BRA L.2
L.1:
{body}
ADDI R16, R16, 1
L.2:
MOVI R7, 10
BLT R16, R7, L.1
JR R31
"""


class LicmTest(unittest.TestCase):
    def licm(self, body: str):
        stats = {}
        out = lines_of(optimize(LICM_LOOP.format(body=body), ["licm"], stats=stats))
        return out, stats

    def test_constants_leave_the_loop_and_the_uses_follow_them(self):
        out, stats = self.licm("MOVI R8, 100\nADD R9, R16, R8\nSTORE R9, R1, 0")
        self.assertIn("MOVI R5, 100", out[:out.index("BRA L.2")])        # en el preheader
        loop = out[out.index("L.1:"):]
        self.assertFalse(any(l.startswith("MOVI") for l in loop), loop)
        self.assertIn("ADD R9, R16, R5", loop)
        self.assertEqual(stats["licm.loops"], 1)

    def test_a_computation_with_fixed_operands_leaves_too(self):
        out, _ = self.licm("MOVI R8, 3\nSHL R9, R1, R8\nADD R10, R16, R9\nSTORE R10, R2, 0")
        loop = out[out.index("L.1:"):]
        self.assertFalse(any(l.startswith(("MOVI", "SHL")) for l in loop), loop)
        self.assertTrue(any(l.startswith("SHL") for l in out[:out.index("BRA L.2")]))

    def test_a_value_that_changes_in_the_loop_stays(self):
        out, _ = self.licm("ADD R9, R16, R16\nSTORE R9, R1, 0")
        self.assertIn("ADD R9, R16, R16", out[out.index("L.1:"):])

    def test_a_use_reached_by_two_definitions_stays(self):
        body = "BEQ R1, R0, L.7\nMOVI R8, 1\nBRA L.8\nL.7:\nMOVI R8, 2\nL.8:\nADD R9, R16, R8\nSTORE R9, R2, 0"
        out, _ = self.licm(body)
        loop = out[out.index("L.1:"):]
        self.assertIn("MOVI R8, 1", loop)
        self.assertIn("MOVI R8, 2", loop)

    def test_a_zero_uses_r0_and_no_register(self):
        out, stats = self.licm("MOVI R8, 0\nSTORE R8, R1, 0")
        self.assertIn("STORE R0, R1, 0", out)
        self.assertEqual(stats["licm.registers"], 1)                    # solo el `10` de la comparacion

    def test_a_loop_with_a_call_is_left_alone(self):
        out, stats = self.licm("MOVI R8, 100\nJAL R31, g\nADD R9, R16, R8")
        self.assertIn("MOVI R8, 100", out[out.index("L.1:"):])
        self.assertNotIn("licm.loops", stats)


NESTED_LOOP = """.text
.globl f
f:
MOVI R16, 0
BRA L.4
L.1:
{outer}
MOVI R17, 0
BRA L.3
L.2:
STORE R10, R1, 0
ADDI R17, R17, 1
L.3:
BLT R17, R8, L.2
ADDI R16, R16, 1
L.4:
MOVI R11, 10
BLT R16, R11, L.1
JR R31
"""


class LicmNestedTest(unittest.TestCase):
    """Un bucle que tiene otro dentro tambien saca lo suyo: lo que el interior deja en su preheader sigue siendo
    invariante para el exterior si nada de lo que lo calcula cambia en el."""

    def licm(self, outer: str):
        stats = {}
        out = lines_of(optimize(NESTED_LOOP.format(outer=outer), ["licm"], stats=stats))
        return out, stats

    def test_what_does_not_depend_on_the_outer_variable_leaves_both_loops(self):
        out, stats = self.licm("MOVI R8, 160\nMUL R9, R2, R3\nADD R10, R9, R16")
        before = out[:out.index("BRA L.4")]
        loop = out[out.index("L.1:"):]
        self.assertTrue(any(l.startswith("MUL") for l in before), out)        # el producto, una vez
        self.assertFalse(any(l.startswith(("MUL", "MOVI R8")) for l in loop), loop)
        self.assertEqual(stats["licm.loops"], 1)                              # el interior no tiene nada propio

    def test_what_depends_on_the_outer_variable_stays_in_the_outer_loop(self):
        out, _ = self.licm("MOVI R8, 160\nMUL R9, R2, R3\nADD R10, R9, R16")
        loop = out[out.index("L.1:"):out.index("L.2:")]
        self.assertTrue(any(l.startswith("ADD R10") for l in loop), loop)      # lleva R16 (y)

    def test_a_value_carried_from_one_iteration_to_the_next_is_not_invariant(self):
        # R12 se lee antes de escribirse: cada vuelta ve lo de la anterior
        out, _ = self.licm("MOVI R8, 160\nADD R12, R12, R3\nMOVI R9, 0\nADD R10, R12, R9")
        self.assertIn("ADD R12, R12, R3", out[out.index("L.1:"):])

    def test_a_constant_defined_in_the_loop_and_redefined_later_in_it_is_not_merged(self):
        # R8 vale 160 en el interior y 5 al acabar la vuelta: la del final no puede ocupar el lugar de la primera
        out, _ = self.licm("MOVI R8, 160\nADD R10, R16, R8")
        self.assertFalse(any(l.startswith("MOVI R8, 160") for l in out[out.index("L.1:"):]), out)

    def test_an_inner_loop_that_runs_zero_times_still_reads_the_right_bound(self):
        out, _ = self.licm("MOVI R8, 160\nADD R10, R16, R16")
        hoisted = [l for l in out[:out.index("BRA L.4")] if l.startswith("MOVI")]
        self.assertTrue(any(l.endswith(", 160") for l in hoisted), out)
        compare = next(l for l in out if l.startswith("BLT R17,"))
        self.assertNotEqual(compare, "BLT R17, R8, L.2")                       # lee el registro nuevo


LOAD_LOOP = """.text
.globl {name}
{name}:
LI R7, cube_faces
MOVI R16, 0
BRA L.2
L.1:
{body}
ADDI R16, R16, 1
L.2:
MOVI R10, 10
BLT R16, R10, L.1
{end}
"""


class LicmLoadsTest(unittest.TestCase):
    """Con `--assume-noalias`, en un kernel, las cargas por la direccion de un simbolo que el kernel solo lee salen del bucle."""

    def run_pass(self, body: str, noalias: bool = True, name: str = "__kernel_k"):
        stats = {}
        source = LOAD_LOOP.format(name=name, body=body, end="EXIT" if name.startswith("__kernel_") else "JR R31")
        licm_module.NOALIAS = noalias
        try:
            out = lines_of(optimize(source, ["licm"], stats=stats))
        finally:
            licm_module.NOALIAS = False
        return out, stats

    BODY = "LOAD R12, R7, 4\nADD R9, R16, R12\nSTORE R9, R1, 0"

    def test_a_load_through_a_symbol_the_kernel_only_reads_leaves_the_loop(self):
        out, _ = self.run_pass(self.BODY)
        before = out[:out.index("BRA L.2")]
        self.assertTrue(any(l.startswith("LOAD") and l.endswith("R7, 4") for l in before), out)
        self.assertFalse(any(l.startswith("LOAD") for l in out[out.index("L.1:"):]), out)

    def test_the_hoisted_load_comes_after_its_base_and_the_loop_no_longer_reads_it(self):
        out, stats = self.run_pass(self.BODY)
        load = next(i for i, l in enumerate(out) if l.startswith("LOAD"))
        self.assertLess(out.index("LI R7, cube_faces"), load)
        self.assertLess(load, out.index("BRA L.2"))
        self.assertFalse(any("R7" in l for l in out[out.index("L.1:"):]), out)
        self.assertEqual(stats["licm.registers"], 2)                 # la carga y el `10` de la comparacion

    def test_without_the_option_the_load_stays(self):
        out, _ = self.run_pass(self.BODY, noalias=False)
        self.assertIn("LOAD R12, R7, 4", out[out.index("L.1:"):])

    def test_a_function_that_is_not_a_kernel_keeps_its_loads(self):
        out, _ = self.run_pass(self.BODY, name="f")
        self.assertIn("LOAD R12, R7, 4", out[out.index("L.1:"):])

    def test_the_load_stays_if_the_symbol_address_is_used_for_anything_else(self):
        for use in ("ADD R9, R7, R16", "STORE R9, R7, 8", "STORE R7, R1, 4", "ADDI R13, R7, 8"):
            with self.subTest(use=use):
                out, _ = self.run_pass(f"{use}\n{self.BODY}")
                self.assertIn("LOAD R12, R7, 4", out[out.index("L.1:"):])

    def test_a_load_through_another_pointer_stays(self):
        out, _ = self.run_pass("LOAD R12, R2, 4\nADD R9, R16, R12\nSTORE R9, R1, 0")
        self.assertIn("LOAD R12, R2, 4", out[out.index("L.1:"):])

    def test_a_load_whose_base_changes_in_the_loop_stays(self):
        out, _ = self.run_pass("LOAD R12, R7, 4\nADDI R7, R7, 4\nADD R9, R16, R12\nSTORE R9, R1, 0")
        self.assertIn("LOAD R12, R7, 4", out[out.index("L.1:"):])


PROVED_UNIT = """{facts}.text
.globl __kernel_k
__kernel_k:
LI R7, cube_faces
MOVI R16, 0
BRA L.2
L.1:
LOAD R12, R7, 4
ADD R9, R16, R12
STORE R9, R1, 0
ADDI R16, R16, 1
L.2:
MOVI R10, 10
BLT R16, R10, L.1
EXIT
{other}
.data
.align 4
cube_faces:
.word 1
.word 2
{data}
"""


class LicmProvedLoadsTest(unittest.TestCase):
    """Sin `--assume-noalias`, una carga sale del bucle de un kernel si el simbolo es de la unidad, su direccion no
    escapa de ella, no es `volatile` y ningun fichero ajeno lo nombra: ningun puntero puede alcanzarlo."""

    def hoisted(self, other: str = "", data: str = "", facts: str = "", noalias: bool = False,
                external: tuple[str, ...] = ()) -> bool:
        source = PROVED_UNIT.format(facts=facts, other=other, data=data)
        licm_module.NOALIAS, licm_module.EXTERNAL = noalias, frozenset(external)
        try:
            out = lines_of(optimize(source, ["licm"]))
        finally:
            licm_module.NOALIAS, licm_module.EXTERNAL = False, frozenset()
        return "LOAD R12, R7, 4" not in out[out.index("L.1:"):out.index("EXIT")]

    def test_a_symbol_nobody_takes_the_address_of_is_hoisted_without_any_option(self):
        self.assertTrue(self.hoisted())

    def test_another_function_that_writes_or_reads_it_directly_does_not_stop_it(self):
        other = ".globl g\ng:\nLI R8, cube_faces\nSTORE R9, R8, 4\nLOAD R10, R8, 0\nJR R31"
        self.assertTrue(self.hoisted(other))

    def test_a_load_that_overwrites_its_own_base_is_not_an_escape(self):
        # el patron de lcc: `LI R9, sim+12 ; LOAD R9, R9, 0`
        other = ".globl g\ng:\nLI R9, cube_faces+12\nLOAD R9, R9, 0\nJR R31"
        self.assertTrue(self.hoisted(other))

    def test_a_pointer_computed_from_the_address_and_used_only_as_a_base_is_not_an_escape(self):
        # `&tabla[i]` en C: `ADD p, base, offset` y accesos por p
        other = ".globl g\ng:\nLI R8, cube_faces\nADD R9, R8, R2\nADDI R9, R9, 8\nLOAD R10, R9, 0\nSTORE R10, R9, 4\nJR R31"
        self.assertTrue(self.hoisted(other))

    def test_a_computed_pointer_that_is_stored_passed_or_returned_is_an_escape(self):
        for other in (".globl g\ng:\nLI R8, cube_faces\nADD R9, R8, R2\nSTORE R9, R3, 0\nJR R31",
                      ".globl g\ng:\nLI R8, cube_faces\nADDI R9, R8, 4\nADD R1, R9, R0\nJR R31",
                      ".globl g\ng:\nLI R8, cube_faces\nADD R9, R8, R2\nADDI R4, R9, 4\nJAL R31, h\nJR R31",
                      ".globl g\ng:\nLI R8, cube_faces\nSHL R9, R8, R2\nLOAD R10, R9, 0\nJR R31"):
            with self.subTest(other=other):
                self.assertFalse(self.hoisted(other))

    def test_storing_the_address_itself_is_an_escape(self):
        other = ".globl g\ng:\nLI R9, cube_faces\nSTORE R9, R9, 0\nJR R31"
        self.assertFalse(self.hoisted(other))

    def test_a_symbol_this_unit_does_not_define_is_not_hoisted(self):
        source = PROVED_UNIT.format(facts="", other="", data="").replace("cube_faces:\n", "other_name:\n")
        out = lines_of(optimize(source, ["licm"]))
        self.assertIn("LOAD R12, R7, 4", out[out.index("L.1:"):])

    def test_the_address_passed_to_a_function_or_returned_makes_it_escape(self):
        for other in (".globl g\ng:\nLI R1, cube_faces\nJR R31",
                      ".globl g\ng:\nLI R1, cube_faces\nADDI R2, R1, 8\nSTORE R3, R2, 0\nJR R31",
                      ".globl g\ng:\nLI R4, cube_faces\nJAL R31, h\nJR R31"):
            with self.subTest(other=other):
                self.assertFalse(self.hoisted(other))

    def test_an_address_in_a_data_table_makes_it_escape(self):
        self.assertFalse(self.hoisted(data="table:\n.word cube_faces"))

    def test_a_volatile_symbol_is_never_hoisted_not_even_with_the_option(self):
        facts = "; @miniopt volatile cube_faces\n"
        self.assertFalse(self.hoisted(facts=facts))
        self.assertFalse(self.hoisted(facts=facts, noalias=True))

    def test_a_symbol_that_foreign_code_names_is_not_provable(self):
        self.assertFalse(self.hoisted(external=("cube_faces",)))

    def test_the_option_assumes_what_the_analysis_cannot_prove(self):
        other = ".globl g\ng:\nLI R1, cube_faces\nJR R31"
        self.assertFalse(self.hoisted(other))
        self.assertTrue(self.hoisted(other, noalias=True))
        self.assertTrue(self.hoisted(external=("cube_faces",), noalias=True))

    def test_the_command_line_takes_the_files_that_are_assembled_apart(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            source, foreign = Path(folder, "k.s"), Path(folder, "crt.s")
            source.write_text(PROVED_UNIT.format(facts="", other="", data=""), encoding="utf-8")
            foreign.write_text("start:\nLI R1, cube_faces\nJR R31\n", encoding="utf-8")
            for refs, hoisted in (([], True), (["--extern-refs", str(foreign)], False)):
                with self.subTest(refs=refs):
                    target = Path(folder, "out.s")
                    try:
                        self.assertEqual(optimize_main([str(source), "-o", str(target), "--passes", "licm", *refs]), 0)
                    finally:
                        licm_module.EXTERNAL = frozenset()
                    out = lines_of(target.read_text(encoding="utf-8"))
                    self.assertEqual("LOAD R12, R7, 4" not in out[out.index("L.1:"):out.index("EXIT")], hoisted)

    def test_the_fact_comment_does_not_reach_the_output(self):
        source = PROVED_UNIT.format(facts="; @miniopt volatile cube_faces\n", other="", data="")
        self.assertNotIn("@miniopt", optimize(source, ["licm"]))


class CopyPropTest(unittest.TestCase):
    def run_pass(self, body: str):
        stats = {}
        source = ".text\n.globl f\nf:\n" + body + "\nJR R31\n"
        return lines_of(optimize(source, ["copyprop", "dce"], stats=stats)), stats

    def test_a_use_reads_the_original_and_the_copy_disappears(self):
        out, stats = self.run_pass("ADD R13, R28, R0\nBGEU R13, R6, L.1\nL.1:")
        self.assertIn("BGEU R28, R6, L.1", out)
        self.assertNotIn("ADD R13, R28, R0", out)
        self.assertEqual(stats["dce.removed"], 1)

    def test_if_the_original_changes_in_between_the_copy_stays(self):
        out, _ = self.run_pass("ADD R13, R28, R0\nADDI R28, R28, 1\nSTORE R13, R1, 0")
        self.assertIn("ADD R13, R28, R0", out)
        self.assertIn("STORE R13, R1, 0", out)

    def test_a_copy_that_does_not_reach_by_every_path_is_not_used(self):
        body = "BEQ R1, R0, L.2\nADD R13, R28, R0\nL.2:\nSTORE R13, R2, 0"
        out, _ = self.run_pass(body)
        self.assertIn("STORE R13, R2, 0", out)

    def test_a_call_cuts_the_copies_of_temporaries(self):
        out, _ = self.run_pass("ADD R13, R7, R0\nJAL R31, g\nSTORE R13, R2, 0")
        self.assertIn("STORE R13, R2, 0", out)

    def test_a_copy_that_ends_up_copying_a_register_to_itself_goes(self):
        out, stats = self.run_pass("ADD R31, R14, R0\nADD R14, R31, R0\nSTORE R14, R1, 0")
        self.assertNotIn("ADD R14, R14, R0", out)
        self.assertIn("STORE R14, R1, 0", out)
        self.assertEqual(stats["copyprop.removed"], 1)

    def test_dead_pure_code_goes_but_a_load_stays(self):
        out, _ = self.run_pass("MOVI R8, 5\nLOAD R9, R1, 0")
        self.assertNotIn("MOVI R8, 5", out)
        self.assertIn("LOAD R9, R1, 0", out)

    def test_the_value_returned_is_not_dead(self):
        out, _ = self.run_pass("ADD R1, R7, R0")
        self.assertIn("ADD R1, R7, R0", out)


class ConstPropTest(unittest.TestCase):
    def run_pass(self, body: str):
        stats = {}
        source = ".text\n.globl f\nf:\n" + body + "\nJR R31\n"
        return lines_of(optimize(source, ["constprop", "dce"], stats=stats)), stats

    def test_a_subtraction_of_a_constant_becomes_an_addi(self):
        out, stats = self.run_pass("MOVI R7, 256\nSUB R13, R28, R7\nSTORE R13, R1, 0")
        self.assertIn("ADDI R13, R28, -256", out)
        self.assertNotIn("MOVI R7, 256", out)                    # y la constante ya no se lee
        self.assertEqual(stats["constprop.folded"], 1)

    def test_and_or_xor_take_the_unsigned_immediate(self):
        out, _ = self.run_pass("MOVI R7, 252\nAND R13, R28, R7\nOR R14, R7, R28\nSTORE R13, R1, 0\nSTORE R14, R1, 4")
        self.assertIn("ANDI R13, R28, 252", out)
        self.assertIn("ORI R14, R28, 252", out)

    def test_a_shift_by_one_is_an_add(self):
        out, _ = self.run_pass("MOVI R9, 1\nSHL R14, R14, R9\nSTORE R14, R1, 0")
        self.assertIn("ADD R14, R14, R14", out)
        self.assertNotIn("MOVI R9, 1", out)

    def test_a_constant_that_does_not_fit_stays_in_its_register(self):
        out, _ = self.run_pass("LI R7, 100000\nADD R13, R28, R7\nSTORE R13, R1, 0")
        self.assertIn("ADD R13, R28, R7", out)

    def test_a_register_that_is_a_constant_on_one_path_only_is_not_folded(self):
        body = "MOVI R7, 5\nBEQ R1, R0, L.2\nMOVI R7, 6\nL.2:\nSUB R13, R28, R7\nSTORE R13, R2, 0"
        out, _ = self.run_pass(body)
        self.assertIn("SUB R13, R28, R7", out)

    def test_a_copy_from_r0_is_left_as_a_copy(self):
        out, stats = self.run_pass("ADD R13, R28, R0\nSTORE R13, R1, 0")
        self.assertIn("ADD R13, R28, R0", out)
        self.assertNotIn("constprop.identities", stats)            # una copia ya es la forma canonica

    # -- cargas que ya estan hechas --------------------------------------------------------------

    def test_a_constant_load_that_is_already_there_goes(self):
        body = "MOVI R5, 3\nSHL R21, R14, R5\nMOVI R5, 3\nSHL R20, R15, R5\nSTORE R21, R1, 0\nSTORE R20, R1, 4"
        out, stats = self.run_pass(body)
        self.assertEqual(out.count("MOVI R5, 3"), 1)
        self.assertEqual(stats["constprop.redundant"], 1)

    def test_a_constant_load_stays_if_the_value_differs_on_one_path(self):
        body = "MOVI R5, 3\nBEQ R1, R0, L.2\nMOVI R5, 4\nL.2:\nMOVI R5, 3\nSHL R21, R14, R5\nSTORE R21, R2, 0"
        out, _ = self.run_pass(body)
        self.assertIn("MOVI R5, 3", out[out.index("L.2:"):])

    def test_a_call_makes_the_caller_saved_constants_unknown(self):
        out, _ = self.run_pass("MOVI R5, 3\nJAL R31, g\nMOVI R5, 3\nSHL R21, R14, R5\nSTORE R21, R2, 0")
        self.assertIn("MOVI R5, 3", out[out.index("JAL R31, g"):])

    # -- los dos operandos son constantes --------------------------------------------------------

    def test_an_operation_on_two_constants_is_done_here(self):
        cases = [("MUL", 6, 7, "MOVI R9, 42"),
                 ("MUL", 300, 300, "LI R9, 90000"),                    # no cabe en 16 bits: LI
                 ("SUB", 0, 1, "MOVI R9, -1"),
                 ("ADD", 0x7FFFFFFF, 1, "LI R9, -2147483648"),           # se da la vuelta, como en la maquina
                 ("AND", 0xFF00, 0x0FF0, "MOVI R9, 3840"),
                 ("SHR", -1, 28, "MOVI R9, 15"),                       # logico
                 ("SAR", -16, 2, "MOVI R9, -4"),                       # aritmetico
                 ("SHL", 1, 33, "MOVI R9, 2"),                         # la cantidad usa 5 bits
                 ("SLT", -1, 1, "MOVI R9, 1"),
                 ("SLTU", -1, 1, "MOVI R9, 0")]
        for op, a, b, expected in cases:
            with self.subTest(op=op, a=a, b=b):
                stats = {}
                out, stats = self.run_pass(f"LI R7, {a}\nLI R8, {b}\n{op} R9, R7, R8\nSTORE R9, R1, 0")
                self.assertIn(expected, out)
                self.assertFalse(any(l.startswith(op) for l in out), out)
                self.assertEqual(stats["constprop.evaluated"], 1)

    def test_an_immediate_operation_on_a_constant_is_done_here(self):
        cases = [("ADDI R9, R7, 5", "MOVI R9, 15"), ("ADDI R9, R7, -20", "MOVI R9, -10"),
                 ("ANDI R9, R7, 6", "MOVI R9, 2"), ("SHLI R9, R7, 4", "MOVI R9, 160"),
                 ("XORI R9, R7, 0xFFFF", "LI R9, 65525")]
        for instruction, expected in cases:
            with self.subTest(instruction=instruction):
                out, _ = self.run_pass(f"MOVI R7, 10\n{instruction}\nSTORE R9, R1, 0")
                self.assertIn(expected, out)

    def test_the_logic_immediate_is_zero_extended(self):
        out, _ = self.run_pass("MOVI R7, -1\nANDI R9, R7, 255\nSTORE R9, R1, 0")
        self.assertIn("MOVI R9, 255", out)

    def test_a_copy_of_a_constant_is_a_constant_for_the_uses_but_stays(self):
        out, stats = self.run_pass("MOVI R7, 8\nADD R9, R7, R0\nADD R14, R14, R9\nSTORE R14, R1, 0")
        self.assertIn("ADDI R14, R14, 8", out)
        self.assertNotIn("ADD R9, R7, R0", out)                  # nadie la lee ya: se va con el codigo muerto
        out, _ = self.run_pass("ADD R9, R0, R0\nADD R14, R14, R9\nSTORE R14, R1, 0\nSTORE R9, R1, 4")
        self.assertIn("ADD R9, R0, R0", out)                     # un cero copiado de R0 sigue siendo esa copia
        self.assertNotIn("ADD R14, R14, R9", out)                # y su uso ya no hace falta

    def test_a_copy_is_left_for_copyprop_even_if_its_source_is_a_constant(self):
        """lcc escribe un cero como `ADD d, R0, R0` y copia un cero con `ADD d, s, R0`: convertirlos en
        `MOVI d, 0` le quita a `copyprop` los usos que ya podian leer R0 (diverge.c perdia 5 instrucciones)."""
        out, stats = self.run_pass("ADD R28, R0, R0\nMOVI R15, 0\nADD R4, R15, R0\nSTORE R28, R1, 0\nSTORE R4, R1, 4")
        self.assertIn("ADD R28, R0, R0", out)
        self.assertIn("ADD R4, R15, R0", out)
        self.assertNotIn("constprop.evaluated", stats)

    def test_an_operation_with_one_unknown_operand_is_not_evaluated(self):
        out, stats = self.run_pass("MOVI R7, 6\nMUL R9, R7, R28\nSTORE R9, R1, 0")
        self.assertIn("MUL R9, R7, R28", out)
        self.assertNotIn("constprop.evaluated", stats)

    # -- identidades -----------------------------------------------------------------------------

    def test_an_identity_becomes_a_copy_and_a_zero_a_zero(self):
        cases = [("MOVI R7, 0", "ADD R9, R28, R7", "ADD R9, R28, R0"),
                 ("MOVI R7, 0", "SUB R9, R28, R7", "ADD R9, R28, R0"),
                 ("MOVI R7, 0", "OR R9, R7, R28", "ADD R9, R28, R0"),
                 ("MOVI R7, 0", "XOR R9, R28, R7", "ADD R9, R28, R0"),
                 ("MOVI R7, 1", "MUL R9, R28, R7", "ADD R9, R28, R0"),
                 ("MOVI R7, 1", "MUL R9, R7, R28", "ADD R9, R28, R0"),
                 ("MOVI R7, 32", "SHL R9, R28, R7", "ADD R9, R28, R0"),         # 32 son 0 bits
                 ("MOVI R7, -1", "AND R9, R28, R7", "ADD R9, R28, R0"),
                 ("", "ADDI R9, R28, 0", "ADD R9, R28, R0"),
                 ("", "ORI R9, R28, 0", "ADD R9, R28, R0"),
                 ("", "SHLI R9, R28, 0", "ADD R9, R28, R0"),
                 ("MOVI R7, 0", "MUL R9, R28, R7", "MOVI R9, 0"),
                 ("MOVI R7, 0", "AND R9, R7, R28", "MOVI R9, 0"),
                 ("", "SUB R9, R28, R28", "MOVI R9, 0"),
                 ("", "XOR R9, R28, R28", "MOVI R9, 0"),
                 ("", "ANDI R9, R28, 0", "MOVI R9, 0")]
        for setup, instruction, expected in cases:
            with self.subTest(instruction=instruction, setup=setup):
                out, stats = self.run_pass(f"{setup}\n{instruction}\nSTORE R9, R1, 0")
                self.assertIn(expected, out)
                self.assertNotIn(instruction, out)
                self.assertEqual(stats["constprop.identities"], 1)

    def test_an_identity_that_copies_a_register_to_itself_disappears(self):
        for instruction in ("ADD R28, R28, R7", "ADDI R28, R28, 0", "SHL R28, R28, R7"):
            with self.subTest(instruction=instruction):
                out, _ = self.run_pass(f"MOVI R7, 0\n{instruction}\nSTORE R28, R1, 0")
                self.assertEqual([l for l in out if l.startswith(("ADD", "SHL"))], [])

    def test_a_value_that_is_not_the_identity_is_left_alone(self):
        for setup, instruction in (("MOVI R7, 2", "MUL R9, R28, R7"), ("MOVI R7, 1", "SUB R9, R7, R28"),
                                   ("MOVI R7, 1", "SHL R9, R7, R28"), ("MOVI R7, 255", "AND R9, R28, R7")):
            with self.subTest(instruction=instruction):
                out, stats = self.run_pass(f"{setup}\n{instruction}\nSTORE R9, R1, 0")
                self.assertNotIn("constprop.identities", stats)
                self.assertNotIn("constprop.evaluated", stats)

    # -- MUL por una constante seguido de SHL por otra -------------------------------------------

    MUL_SHL = "MOVI R11, 320\nMUL R14, R11, R14\nMOVI R5, 2\nSHL R14, R14, R5\nADD R14, R14, R1\nSTORE R14, R2, 0"

    def test_a_mul_followed_by_a_shift_multiplies_by_the_shifted_constant(self):
        out, stats = self.run_pass(self.MUL_SHL)
        self.assertEqual(out[out.index("f:") + 1:],
                         ["MOVI R11, 1280", "MUL R14, R11, R14", "ADD R14, R14, R1", "STORE R14, R2, 0", "JR R31"])
        self.assertEqual(stats["constprop.fused"], 1)

    def test_it_also_works_with_the_constant_as_the_first_operand(self):
        out, _ = self.run_pass(self.MUL_SHL.replace("MUL R14, R11, R14", "MUL R14, R14, R11"))
        self.assertIn("MOVI R11, 1280", out)
        self.assertIn("MUL R14, R14, R11", out)
        self.assertFalse(any(l.startswith("SHL") for l in out))

    def test_the_constant_is_wrapped_to_32_bits(self):
        out, _ = self.run_pass(self.MUL_SHL.replace("MOVI R11, 320", "MOVI R11, 3").replace("MOVI R5, 2", "MOVI R5, 31"))
        self.assertIn("LI R11, -2147483648", out)                         # 3 << 31 = 0x80000000

    def test_the_mul_is_not_touched_if_the_constant_is_read_afterwards(self):
        out, stats = self.run_pass(self.MUL_SHL + "\nSTORE R11, R2, 4")
        self.assertIn("MOVI R11, 320", out)
        self.assertIn("SHL R14, R14, R5", out)
        self.assertNotIn("constprop.fused", stats)

    def test_the_mul_is_not_touched_if_its_result_is_read_before_the_shift(self):
        body = "MOVI R11, 320\nMUL R14, R11, R14\nSTORE R14, R2, 8\nMOVI R5, 2\nSHL R14, R14, R5\nSTORE R14, R2, 0"
        out, stats = self.run_pass(body)
        self.assertIn("SHL R14, R14, R5", out)
        self.assertNotIn("constprop.fused", stats)

    def test_the_mul_is_not_touched_if_the_shift_amount_is_unknown(self):
        out, stats = self.run_pass(self.MUL_SHL.replace("MOVI R5, 2\n", "").replace("SHL R14, R14, R5", "SHL R14, R14, R6"))
        self.assertIn("SHL R14, R14, R6", out)
        self.assertNotIn("constprop.fused", stats)

    def test_the_shift_of_another_register_is_not_fused(self):
        body = "MOVI R11, 320\nMUL R14, R11, R14\nMOVI R5, 2\nSHL R15, R14, R5\nSTORE R15, R2, 0\nSTORE R14, R2, 4"
        out, stats = self.run_pass(body)
        self.assertNotIn("constprop.fused", stats)
        self.assertIn("MOVI R11, 320", out)


class HandwrittenAsmTest(unittest.TestCase):
    """Trozos del ensamblador a mano (`examples/asm/race/cube.inc`, con etiquetas `L.n` para que el
    filtro los trate como una sola funcion). Lo que ya esta bien escrito no debe cambiar, y las
    formas que lcc no genera pero a mano se escriben tienen que entenderse."""

    def run_pass(self, body: str):
        stats = {}
        source = ".text\n.globl f\nf:\n" + body + "\nJR R31\n"
        out = lines_of(optimize(source, ["constprop"], stats=stats))
        return out[out.index("f:") + 1:], stats                   # solo la funcion, sin la cabecera

    def test_constants_multiplied_by_a_shared_register_are_left_alone(self):
        body = ("MOVI R31, 8\nLOAD R13, R6, 12\nMUL R13, R13, R31\nLOAD R14, R6, 16\nMUL R14, R14, R31\n"
                "STORE R13, R2, 0\nSTORE R14, R2, 4")
        out, stats = self.run_pass(body)
        self.assertEqual(out[:-1], lines_of(body))
        self.assertEqual({k: v for k, v in stats.items() if v}, {})

    def test_a_row_address_with_the_shift_already_folded_is_left_alone(self):
        body = "MOVI R28, 1280\nMUL R23, R25, R28\nADD R23, R23, R5\nADD R23, R23, R2\nSTORE R23, R1, 0"
        out, stats = self.run_pass(body)
        self.assertEqual(out[:-1], lines_of(body))
        self.assertEqual({k: v for k, v in stats.items() if v}, {})

    def test_the_hand_written_cell_loop_is_left_alone(self):
        body = """MOVI R27, 5
MOVI R22, 8704
MOVI R24, 20
L.1:
BGEU R7, R22, L.2
BGEU R8, R22, L.2
ADDI R28, R8, -256
ADD R28, R28, R28
ANDI R28, R28, 0x3F00
ADDI R29, R7, -256
SHR R29, R29, R27
ANDI R29, R29, 0xFC
ADD R28, R28, R29
ADD R28, R28, R19
LOAD R29, R28, 0
STORE R29, R23, 0
L.2:
ADDI R23, R23, 32
ADDI R24, R24, -1
BNE R24, R0, L.1"""
        out, stats = self.run_pass(body)
        self.assertEqual(out[:-1], lines_of(body))
        self.assertEqual({k: v for k, v in stats.items() if v}, {})

    def test_addi_with_a_zero_is_a_copy(self):
        out, _ = self.run_pass("ADDI R29, R30, 0\nSTORE R29, R1, 0")
        self.assertIn("ADD R29, R30, R0", out)


class SharebaseTest(unittest.TestCase):
    def run_pass(self, body: str, name: str = "f"):
        stats = {}
        source = f".text\n.globl {name}\n{name}:\n" + body + ("\nEXIT\n" if name.startswith("__kernel_") else "\nJR R31\n")
        out = lines_of(optimize(source, ["sharebase"], stats=stats))
        return out[out.index(f"{name}:") + 1:], stats

    PAIRS = ("LI R12, cube_faces+4\nLOAD R12, R12, 0\nLI R11, cube_faces+20\nLOAD R11, R11, 0\n"
             "MUL R11, R12, R11\nLI R12, cube_faces+12\nLOAD R12, R12, 0\nADD R11, R11, R12\nSTORE R11, R1, 0")

    def test_the_loads_of_one_table_share_a_base_and_add_the_offset_themselves(self):
        out, stats = self.run_pass(self.PAIRS)
        self.assertEqual(out, ["LI R5, cube_faces", "LOAD R12, R5, 4", "LOAD R11, R5, 20", "MUL R11, R12, R11",
                               "LOAD R12, R5, 12", "ADD R11, R11, R12", "STORE R11, R1, 0", "JR R31"])
        self.assertEqual(stats["sharebase.groups"], 1)
        self.assertEqual(stats["sharebase.removed"], 3)

    def test_a_single_address_is_left_alone(self):
        out, stats = self.run_pass("LI R12, cube_faces+4\nLOAD R12, R12, 0\nSTORE R12, R1, 0")
        self.assertIn("LI R12, cube_faces+4", out)
        self.assertNotIn("sharebase.groups", stats)

    def test_the_existing_offset_of_the_access_is_added(self):
        body = "LI R12, t+4\nLOAD R9, R12, 8\nLI R11, t+16\nLOAD R10, R11, 0\nSTORE R9, R1, 0\nSTORE R10, R1, 4"
        out, _ = self.run_pass(body)
        self.assertIn("LOAD R9, R5, 12", out)
        self.assertIn("LOAD R10, R5, 16", out)

    def test_a_store_through_the_address_is_rewritten_too(self):
        out, _ = self.run_pass("LI R12, t+4\nSTORE R9, R12, 0\nLI R11, t+8\nSTORE R9, R11, 0")
        self.assertIn("STORE R9, R5, 4", out)
        self.assertIn("STORE R9, R5, 8", out)

    def test_two_tables_get_a_base_each(self):
        body = ("LI R12, a+4\nLOAD R9, R12, 0\nLI R11, b+4\nLOAD R10, R11, 0\n"
                "LI R12, a+8\nLOAD R13, R12, 0\nLI R11, b+8\nLOAD R14, R11, 0\n"
                "ADD R9, R9, R10\nADD R13, R13, R14\nSTORE R9, R1, 0\nSTORE R13, R1, 4")
        out, stats = self.run_pass(body)
        self.assertEqual(stats["sharebase.groups"], 2)
        self.assertEqual(sum(l.startswith("LI") for l in out), 2)

    def test_an_address_that_is_used_for_anything_else_stays(self):
        for use in ("ADD R9, R12, R1", "STORE R12, R1, 0", "STORE R12, R12, 0", "JAL R31, g"):
            with self.subTest(use=use):
                body = f"LI R12, t+4\n{use}\nLI R11, t+8\nLOAD R10, R11, 0\nSTORE R10, R1, 4"
                out, stats = self.run_pass(body)
                self.assertIn("LI R12, t+4", out)
                self.assertNotIn("sharebase.groups", stats)

    def test_an_address_that_is_still_live_at_the_end_of_the_block_stays(self):
        body = "LI R12, t+4\nLOAD R9, R12, 0\nLI R11, t+8\nLOAD R10, R11, 0\nBEQ R1, R0, L.2\nL.2:\nSTORE R12, R2, 0"
        out, stats = self.run_pass(body)
        self.assertIn("LI R12, t+4", out)
        self.assertNotIn("sharebase.groups", stats)

    def test_a_number_or_an_offset_that_does_not_fit_is_not_an_address(self):
        body = "LI R12, 100000\nLOAD R9, R12, 0\nLI R11, t+40000\nLOAD R10, R11, 0\nLI R8, t+4\nLOAD R7, R8, 0"
        out, stats = self.run_pass(body)
        self.assertIn("LI R12, 100000", out)
        self.assertIn("LI R11, t+40000", out)
        self.assertNotIn("sharebase.groups", stats)

    def test_without_a_free_register_in_the_stretch_nothing_changes(self):
        busy = "\n".join(f"ADD R{a}, R{a}, R{b}" for a, b in ((1, 2), (3, 4), (5, 6), (7, 8), (9, 10), (13, 14), (15, 15)))
        body = f"LI R12, t+4\nLOAD R12, R12, 0\n{busy}\nLI R11, t+8\nLOAD R11, R11, 0\nSTORE R11, R2, 0\nSTORE R12, R2, 4"
        out, stats = self.run_pass(body)
        self.assertIn("LI R12, t+4", out)
        self.assertNotIn("sharebase.groups", stats)

    def test_the_base_register_is_not_one_that_is_alive_around_the_stretch(self):
        out, _ = self.run_pass("MOVI R5, 7\n" + self.PAIRS + "\nSTORE R5, R2, 0")
        self.assertIn("LI R6, cube_faces", out)                 # R5 vale 7 y se lee despues

    def test_a_kernel_may_use_its_unused_preserved_registers(self):
        body = "GETTID R16\n" + self.PAIRS + "\nSTORE R16, R2, 0"
        out, stats = self.run_pass(body, name="__kernel_k")
        self.assertEqual(stats["sharebase.groups"], 1)

    def test_a_table_loaded_once_by_hand_is_left_alone(self):
        body = "LI R6, cube_faces\nLOAD R19, R6, 0\nLOAD R20, R6, 32\nLOAD R13, R6, 12\nSTORE R13, R2, 0"
        out, stats = self.run_pass(body)
        self.assertEqual(out[:-1], lines_of(body))
        self.assertNotIn("sharebase.groups", stats)


KERNEL_STACK = """GETTID R5
MOVI R6, 512
MUL R5, R5, R6
LI R30, __gpu_stack+512
ADD R30, R30, R5
ADDI R30, R30, -16
GETLWARP R14
STORE R14, R30, -4+16
BRA L.2
L.1:
LOAD R14, R30, -4+16
STORE R14, R1, 0
ADDI R14, R14, 1
STORE R14, R30, -4+16
L.2:
LOAD R14, R30, -4+16
MOVI R13, 100
BLT R14, R13, L.1
ADDI R30, R30, 16"""

LEAF_STACK = """ADDI R30, R30, -16
MOVI R14, 0
STORE R14, R30, -4+16
BRA L.2
L.1:
LOAD R14, R30, -4+16
ADDI R14, R14, 1
STORE R14, R30, -4+16
L.2:
LOAD R14, R30, -4+16
MOVI R13, 100
BLT R14, R13, L.1
LOAD R1, R30, -4+16
ADDI R30, R30, 16"""


class StackSlotsTest(unittest.TestCase):
    def run_pass(self, body: str, name: str = "f"):
        stats = {}
        end = "\nEXIT\n" if name.startswith("__kernel_") else "\nJR R31\n"
        # con `dce` detras, como en el pipeline: el pase deja las copias y la preparacion de pila que ya no se leen
        out = lines_of(optimize(f".text\n.globl {name}\n{name}:\n" + body + end, ["stackslots", "dce"], stats=stats))
        return out[out.index(f"{name}:") + 1:], stats

    def test_a_kernel_loop_counter_goes_to_a_register_and_the_stack_setup_disappears(self):
        out, stats = self.run_pass(KERNEL_STACK, "__kernel_k")
        self.assertFalse(any("R30" in l for l in out), out)                      # ni accesos ni preparacion
        self.assertFalse(any(l.startswith(("GETTID", "MUL")) for l in out), out)
        self.assertIn("ADD R31, R14, R0", out)                                   # el STORE de la fila
        self.assertIn("ADD R14, R31, R0", out)
        self.assertEqual((stats["stackslots.slots"], stats["stackslots.frames"]), (1, 1))

    def test_a_normal_function_uses_a_caller_saved_register_and_loses_only_the_frame_adjusts(self):
        out, stats = self.run_pass(LEAF_STACK)
        self.assertFalse(any("R30" in l for l in out), out)
        self.assertIn("ADD R4, R14, R0", out)                                    # R4: el primer libre
        self.assertEqual(stats["stackslots.frames"], 1)

    def test_the_whole_pipeline_cleans_up_the_copies(self):
        out = lines_of(optimize(f".text\n.globl __kernel_k\n__kernel_k:\n{KERNEL_STACK}\nEXIT\n"))
        loop = out[out.index("L.1:"):]
        self.assertFalse(any("R30" in l for l in loop), loop)
        copies = [l for l in loop if l.startswith("ADD") and l.endswith("R0")]
        self.assertEqual(copies, ["ADD R31, R14, R0"], loop)       # queda la del contador, ninguna sobre si misma

    def test_the_row_variables_of_the_cube_kernel_as_old_lcc_left_them(self):
        # Forma del `__kernel_cube_good` cuando lcc dejaba `y`, `cstart` y `rstep` en la pila porque las 14
        # variables del bucle interno se quedaban R16-R29. lcc ya las pone en temporales (mini.md:local), asi
        # que este .s es lo unico que mantiene probado el pase para ese patron si lcc deja de hacerlo.
        inner = "\n".join(f"ADDI R{r}, R{r}, 1" for r in range(16, 30))
        body = f"""GETTID R5
MOVI R6, 512
MUL R5, R5, R6
LI R30, __gpu_stack+512
ADD R30, R30, R5
ADDI R30, R30, -80
LI R14, __gpu_lane
LOAD R14, R14, 0
STORE R14, R30, -8+80
MOVI R14, 8
STORE R14, R30, -12+80
GETLWARP R14
STORE R14, R30, -4+80
BRA L.130
L.127:
LOAD R14, R30, -4+80
LOAD R13, R30, -8+80
ADD R26, R13, R0
BRA L.164
L.161:
{inner}
L.162:
ADDI R26, R26, 8
L.164:
MOVI R14, 160
BLT R26, R14, L.161
LOAD R14, R30, -4+80
LOAD R13, R30, -12+80
ADD R14, R14, R13
STORE R14, R30, -4+80
L.130:
LOAD R14, R30, -4+80
MOVI R13, 104
BLT R14, R13, L.127
ADDI R30, R30, 80"""
        out, stats = self.run_pass(body, "__kernel_cube_good")
        self.assertFalse(any("R30" in l for l in out), out)
        self.assertEqual((stats["stackslots.slots"], stats["stackslots.frames"]), (3, 1))
        self.assertEqual(stats["stackslots.accesses"], 9)

    def test_a_slot_that_is_only_touched_outside_loops_stays_if_it_does_not_fit_with_the_others(self):
        busy = "\n".join(f"ADDI R{r}, R{r}, 0" for r in (3, *range(5, 13), 15))
        body = ("ADDI R30, R30, -16\nSTORE R9, R30, -8+16\n" + busy + "\nMOVI R14, 0\nSTORE R14, R30, -4+16\nBRA L.2\n"
                "L.1:\nLOAD R14, R30, -4+16\nADDI R14, R14, 1\nSTORE R14, R30, -4+16\nL.2:\nLOAD R14, R30, -4+16\n"
                "MOVI R13, 100\nBLT R14, R13, L.1\nLOAD R1, R30, -8+16\nADDI R30, R30, 16")
        out, stats = self.run_pass(body)
        self.assertEqual(stats["stackslots.slots"], 1)                          # solo el del bucle: R4 es el unico libre
        self.assertIn("STORE R9, R30, -8+16", out)
        self.assertNotIn("stackslots.frames", stats)

    def test_the_hotter_slot_gets_the_only_free_register(self):
        busy = "\n".join(f"ADDI R{r}, R{r}, 0" for r in (3, *range(5, 13), 15))
        body = ("ADDI R30, R30, -16\nSTORE R9, R30, -8+16\nSTORE R9, R30, -4+16\n" + busy + "\nBRA L.2\nL.1:\n"
                "LOAD R14, R30, -4+16\nLOAD R12, R30, -4+16\nADD R14, R14, R12\nSTORE R14, R30, -4+16\n"
                "LOAD R13, R30, -8+16\nL.2:\nLOAD R14, R30, -4+16\nMOVI R13, 100\nBLT R14, R13, L.1\n"
                "LOAD R1, R30, -8+16\nADDI R30, R30, 16")
        out, stats = self.run_pass(body)
        self.assertEqual(stats["stackslots.slots"], 1)
        self.assertIn("ADD R4, R14, R0", out)                                    # la de -4: 5 accesos en el bucle contra 1
        self.assertIn("LOAD R13, R30, -8+16", out)

    def test_nothing_changes_if_the_address_of_a_slot_is_taken(self):
        for use in ("ADDI R7, R30, -4+16", "LOADB R7, R30, -3+16", "STORE R30, R1, 0", "LOAD R7, R30, -3+16"):
            with self.subTest(use=use):
                out, stats = self.run_pass(KERNEL_STACK.replace("ADDI R14, R14, 1", f"{use}\nADDI R14, R14, 1"), "__kernel_k")
                self.assertTrue(any("R30" in l for l in out), out)
                self.assertNotIn("stackslots.slots", stats)

    def test_nothing_changes_if_there_is_no_register_left(self):
        busy = "\n".join(f"ADDI R{r}, R{r}, 0" for r in (*range(1, 16), *range(16, 30), 31))
        out, stats = self.run_pass(busy + "\n" + KERNEL_STACK, "__kernel_k")
        self.assertNotIn("stackslots.slots", stats)

    def test_a_function_with_calls_is_left_alone(self):
        out, stats = self.run_pass(LEAF_STACK.replace("ADDI R14, R14, 1", "JAL R31, g\nADDI R14, R14, 1"))
        self.assertNotIn("stackslots.slots", stats)

    def test_two_paths_that_disagree_on_the_frame_leave_the_function_alone(self):
        body = ("BEQ R1, R0, L.3\nADDI R30, R30, -8\nL.3:\n" + LEAF_STACK)
        out, stats = self.run_pass(body)
        self.assertNotIn("stackslots.slots", stats)

    def test_a_slot_outside_loops_goes_too_if_everything_fits_and_the_frame_vanishes(self):
        body = LEAF_STACK.replace("ADDI R30, R30, 16", "STORE R9, R30, -8+16\nLOAD R2, R30, -8+16\nADDI R30, R30, 16")
        body = body.replace("MOVI R14, 0", "MOVI R14, 0\nSTORE R9, R30, -8+16")
        out, stats = self.run_pass(body)
        self.assertEqual(stats["stackslots.slots"], 2)
        self.assertFalse(any("R30" in l for l in out), out)

    def test_an_unused_preserved_register_can_hold_a_slot_in_a_kernel(self):
        busy = "\n".join(f"ADDI R{r}, R{r}, 0" for r in (*range(1, 16), 31, *range(17, 30)))
        out, stats = self.run_pass(busy + "\n" + KERNEL_STACK, "__kernel_k")          # solo R16 queda
        self.assertIn("ADD R16, R14, R0", out)

    def test_a_function_without_a_stack_is_untouched(self):
        out, stats = self.run_pass("ADD R9, R1, R2\nSTORE R9, R1, 0")
        self.assertEqual(out, ["ADD R9, R1, R2", "STORE R9, R1, 0", "JR R31"])
        self.assertNotIn("stackslots.slots", stats)

    def test_the_fifth_argument_is_not_a_private_stack_slot(self):
        out, stats = self.run_pass("LOAD R10, R30, 16\nADD R1, R1, R10")
        self.assertIn("LOAD R10, R30, 16", out)
        self.assertNotIn("stackslots.slots", stats)

    def test_a_fifth_argument_after_allocating_a_frame_is_not_promoted(self):
        body = "ADDI R30, R30, -32\nLOAD R10, R30, 48\nADD R1, R1, R10\nADDI R30, R30, 32"
        out, stats = self.run_pass(body)
        self.assertIn("LOAD R10, R30, 48", out)
        self.assertNotIn("stackslots.slots", stats)


def stack_program(rng: random.Random) -> str:
    """Un bucle que lleva un contador y varios acumuladores en la pila (a veces tambien uno fuera del bucle),
    con registros ocupados al azar para variar cuantos huecos caben. Los resultados quedan en R16..R20."""
    slots = rng.randint(1, 4)
    lines = ["ADDI R30, R30, -32"]
    lines += [f"MOVI R5, {rng.randint(0, 50)}\nSTORE R5, R30, {4 * s}" for s in range(slots)]
    lines += [f"MOVI R{r}, 0" for r in range(17, 21)]
    lines += [f"ADDI R{r}, R{r}, 0" for r in rng.sample(range(7, 16), rng.randint(0, 9))]     # ocupa registros
    lines += ["BRA L.2", "L.1:"]
    for s in range(1, slots):
        lines += [f"LOAD R6, R30, {4 * s}", f"ADDI R6, R6, {rng.randint(1, 5)}", f"STORE R6, R30, {4 * s}",
                  f"LOAD R6, R30, {4 * s}", f"ADD R{16 + s}, R{16 + s}, R6"]
    lines += ["LOAD R5, R30, 0", "ADDI R5, R5, 1", "STORE R5, R30, 0", "L.2:", "LOAD R5, R30, 0",
              f"MOVI R8, {rng.randint(1, 20)}", "BLT R5, R8, L.1"]
    lines += [f"LOAD R{16 + s}, R30, {4 * s}" if s == 0 else f"LOAD R20, R30, {4 * s}" for s in range(slots)]
    lines += ["ADDI R30, R30, 32", "HALT"]
    return ".text\n.globl f\nf:\n" + "\n".join(lines) + "\n"


class StackSlotsSemanticsTest(unittest.TestCase):
    def test_programs_give_the_same_registers_before_and_after(self):
        promoted = 0
        for seed in range(200):
            source = stack_program(random.Random(seed))
            stats: dict = {}
            alone = optimize(source, ["stackslots"], stats=stats)
            promoted += stats.get("stackslots.slots", 0)
            expected = final_registers(source, 0)
            with self.subTest(seed=seed):
                self.assertEqual(final_registers(alone, 0), expected, source + "\n---\n" + alone)
                everything = optimize(source)
                self.assertEqual(final_registers(everything, 0), expected, source + "\n---\n" + everything)
        self.assertGreater(promoted, 0, "el generador nunca ejercita el pase")


def table_program(rng: random.Random) -> str:
    """Cargas desde una tabla (`L.9`, tras el `HALT`) por direcciones `L.9+K` repartidas con calculos en
    medio. Los resultados quedan en R16..R25."""
    lines = []
    for n in range(10):
        address, base = rng.randrange(0, 15) * 4, rng.choice((8, 9, 10, 11, 12, 13))
        lines += [f"LI R{base}, L.9+{address}", f"LOAD R{16 + n}, R{base}, {rng.choice((0, 4, 8))}"]
        if rng.random() < 0.4:
            lines.append(f"ADD R{16 + n}, R{16 + n}, R{rng.choice((16, 17, 18))}")
        if rng.random() < 0.2:
            lines.append(f"MOVI R{rng.choice((5, 6, 7))}, {rng.randint(0, 99)}")
    table = ", ".join(str(rng.randint(0, 1000)) for _ in range(32))
    return ".text\n.globl f\nf:\n" + "\n".join(lines) + f"\nHALT\nL.9:\n.word {table}\n"


class SharebaseSemanticsTest(unittest.TestCase):
    def test_programs_read_the_same_values_before_and_after(self):
        groups = 0
        for seed in range(200):
            source = table_program(random.Random(seed))
            stats: dict = {}
            optimized = optimize(source, ["sharebase"], stats=stats)
            groups += stats.get("sharebase.groups", 0)
            with self.subTest(seed=seed):
                self.assertEqual(final_registers(optimized, 0), final_registers(source, 0), source + "\n---\n" + optimized)
        self.assertGreater(groups, 0, "el generador nunca ejercita el pase")


POOL = [0, 1, 2, 3, 7, 31, 32, 33, 255, 256, 320, 1280, 32767, -32768, 65535, 65536, 100000,
        -1, -2, 2**31 - 1, -2**31]
R3_OPS = ["ADD", "SUB", "MUL", "AND", "OR", "XOR", "SHL", "SHR", "SAR", "SLT", "SLTU"]


def random_program(rng: random.Random) -> str:
    """Instrucciones de calculo al azar entre constantes (R5..R7), un registro desconocido (R1) y R0.
    Los resultados quedan en R16..R25, que `HALT` da por leidos."""
    values = {r: rng.choice(POOL) for r in (5, 6, 7)}
    lines = [f"LI R{r}, {value}" for r, value in values.items()]
    sources = ["R0", "R1", "R1", "R5", "R6", "R7"]
    for n in range(10):
        dest = f"R{16 + n}"
        kind = rng.random()
        if kind < 0.10:
            r = rng.choice((5, 6, 7))                        # recarga una constante, a veces la misma
            values[r] = values[r] if rng.random() < 0.5 else rng.choice(POOL)
            lines.append(f"LI R{r}, {values[r]}")
        if kind < 0.20:
            k, s = rng.choice((5, 6, 7)), rng.choice((5, 6, 7))
            lines += [f"MUL {dest}, {rng.choice([x for x in sources if x != dest])}, R{k}", f"SHL {dest}, {dest}, R{s}"]
        elif kind < 0.65:
            lines.append(f"{rng.choice(R3_OPS)} {dest}, {rng.choice(sources)}, {rng.choice(sources)}")
        else:
            op = rng.choice(["ADDI", "ANDI", "ORI", "XORI", "SHLI", "SHRI", "SARI"])
            imm = {"ADDI": rng.randint(-32768, 32767), "ANDI": rng.randint(0, 65535),
                   "ORI": rng.choice((0, rng.randint(0, 65535))), "XORI": rng.randint(0, 65535)}.get(op, rng.choice((0, rng.randint(0, 31))))
            lines.append(f"{op} {dest}, {rng.choice(sources)}, {imm}")
        sources.append(dest)
    return ".text\n.globl f\nf:\n" + "\n".join(lines) + "\nHALT\n"


def final_registers(source: str, r1: int) -> list[int]:
    cpu = CPU(memory_size=1 << 16)
    cpu.load_program(assemble_bytes(source))
    cpu.regs[1] = r1 & 0xFFFFFFFF
    cpu.regs[30] = 0x8000                                  # la pila, para los programas que la usan
    cpu.run(10_000)
    return cpu.regs[16:26]


class ConstPropSemanticsTest(unittest.TestCase):
    def test_programs_give_the_same_registers_before_and_after(self):
        """Programas de calculo al azar, ejecutados en el simulador de la CPU con y sin el pase: el
        resultado de la maquina, no el texto."""
        totals: dict[str, int] = {}
        for seed in range(400):
            rng = random.Random(seed)
            source = random_program(rng)
            stats: dict = {}
            optimized = optimize(source, ["constprop"], stats=stats)
            for key, value in stats.items():
                totals[key] = totals.get(key, 0) + value
            r1 = rng.choice(POOL)
            with self.subTest(seed=seed):
                self.assertEqual(final_registers(optimized, r1), final_registers(source, r1), source + "\n---\n" + optimized)
        for key in ("constprop.evaluated", "constprop.identities", "constprop.fused", "constprop.redundant"):
            self.assertGreater(totals.get(key, 0), 0, f"el generador nunca ejercita {key}: {totals}")


class DceTest(unittest.TestCase):
    def test_it_is_an_independent_pass_and_keeps_effects_and_the_return_value(self):
        source = ".text\n.globl f\nf:\nMOVI R8, 5\nLOAD R9, R2, 0\nADD R1, R7, R0\nJR R31\n"
        stats = {}
        out = lines_of(optimize(source, ["dce"], stats=stats))
        self.assertNotIn("MOVI R8, 5", out)
        self.assertIn("LOAD R9, R2, 0", out)
        self.assertIn("ADD R1, R7, R0", out)
        self.assertEqual(stats["dce.removed"], 1)

    def test_a_write_to_a_preserved_register_is_dead_before_exit_but_not_before_a_return_or_halt(self):
        # el hilo de un kernel desaparece en EXIT: nadie lee R16..R29 despues (la copia a `texel` de la rotacion)
        for end, kept in (("EXIT", False), ("JR R31", True), ("HALT", True)):
            with self.subTest(end=end):
                source = f".text\n.globl f\nf:\nLOAD R11, R2, 0\nADD R28, R11, R0\nSTORE R11, R3, 0\n{end}\n"
                out = lines_of(optimize(source, ["dce"]))
                self.assertEqual("ADD R28, R11, R0" in out, kept, out)

    def test_exit_keeps_the_stack_pointer_alive(self):
        source = ".text\n.globl f\nf:\nADDI R30, R30, -16\nEXIT\n"
        self.assertIn("ADDI R30, R30, -16", lines_of(optimize(source, ["dce"])))


class BranchesTest(unittest.TestCase):
    def run_pass(self, body: str):
        stats = {}
        source = ".text\n.globl f\nf:\n" + body + "\nJR R31\n"
        return lines_of(optimize(source, ["branches"], stats=stats)), stats

    def test_identical_operands_make_the_result_known(self):
        out, stats = self.run_pass("BEQ R7, R7, L.1\nL.1:\nBNE R8, R8, L.2\nL.2:")
        self.assertIn("BRA L.1", out)
        self.assertNotIn("BNE R8, R8, L.2", out)
        self.assertEqual(stats["branches.taken"], 1)
        self.assertEqual(stats["branches.removed"], 1)

    def test_signed_and_unsigned_comparisons_are_distinct(self):
        out, stats = self.run_pass(
            "MOVI R7, -1\nMOVI R8, 1\nBLT R7, R8, L.1\nL.1:\nBLTU R7, R8, L.2\nL.2:"
        )
        self.assertIn("BRA L.1", out)
        self.assertNotIn("BLTU R7, R8, L.2", out)
        self.assertEqual(stats["branches.taken"], 1)
        self.assertEqual(stats["branches.removed"], 1)


class InvertTest(unittest.TestCase):
    def run_pass(self, body: str, pass_name: str = "invert"):
        stats: dict = {}
        source = ".text\n.globl f\nf:\n" + body + "\nJR R31\n"
        return lines_of(optimize(source, [pass_name], stats=stats)), stats

    def test_a_branch_over_a_jump_becomes_the_opposite_branch(self):
        for op, opposite in (("BEQ", "BNE"), ("BNE", "BEQ"), ("BLT", "BGE"),
                             ("BGE", "BLT"), ("BLTU", "BGEU"), ("BGEU", "BLTU")):
            with self.subTest(op=op):
                out, stats = self.run_pass(f"{op} R7, R8, L.1\nBRA L.2\nL.1:\nMOVI R1, 1\nL.2:")
                self.assertIn(f"{opposite} R7, R8, L.2", out)
                self.assertNotIn("BRA L.2", out)
                self.assertNotIn(f"{op} R7, R8, L.1", out)
                self.assertEqual(stats["invert.inverted"], 1)

    def test_the_skipped_label_stays_for_other_references(self):
        out, _ = self.run_pass("BEQ R7, R8, L.1\nBRA L.2\nL.1:\nMOVI R1, 1\nBNE R9, R0, L.1\nL.2:")
        self.assertIn("L.1:", out)
        self.assertIn("BNE R9, R0, L.1", out)

    def test_other_labels_between_are_fine_as_long_as_the_skipped_one_follows_the_jump(self):
        out, stats = self.run_pass("BEQ R7, R8, L.1\nBRA L.2\nL.3:\nL.1:\nMOVI R1, 1\nL.2:")
        self.assertIn("BNE R7, R8, L.2", out)
        self.assertEqual(stats["invert.inverted"], 1)

    def test_a_label_between_the_branch_and_the_jump_makes_the_jump_reachable_on_its_own(self):
        out, stats = self.run_pass("BEQ R7, R8, L.1\nL.3:\nBRA L.2\nL.1:\nMOVI R1, 1\nL.2:")
        self.assertIn("BRA L.2", out)
        self.assertNotIn("invert.inverted", stats)

    def test_a_branch_that_does_not_skip_the_jump_is_left_alone(self):
        out, stats = self.run_pass("BEQ R7, R8, L.4\nBRA L.2\nL.1:\nMOVI R1, 1\nL.2:\nL.4:")
        self.assertIn("BEQ R7, R8, L.4", out)
        self.assertNotIn("invert.inverted", stats)

    def test_a_jump_to_where_it_falls_is_left_to_the_jumps_pass(self):
        out, stats = self.run_pass("BEQ R7, R8, L.1\nBRA L.1\nL.1:\nMOVI R1, 1")
        self.assertIn("BEQ R7, R8, L.1", out)
        self.assertNotIn("invert.inverted", stats)

    def test_a_target_outside_the_function_is_not_inverted(self):
        out, stats = self.run_pass("BEQ R7, R8, L.1\nBRA elsewhere\nL.1:\nMOVI R1, 1")
        self.assertIn("BRA elsewhere", out)
        self.assertNotIn("invert.inverted", stats)

    def test_a_function_too_big_for_a_16_bit_branch_is_not_inverted(self):
        body = "BEQ R7, R8, L.1\nBRA L.2\nL.1:\n" + "ADDI R1, R1, 1\n" * 33000 + "L.2:"
        out, stats = self.run_pass(body)
        self.assertIn("BRA L.2", out)
        self.assertNotIn("invert.inverted", stats)

    def test_it_runs_by_default_and_before_ssy(self):
        from tools.mini_opt import DEFAULT_PASSES
        self.assertIn("invert", DEFAULT_PASSES)
        self.assertLess(DEFAULT_PASSES.index("invert"), DEFAULT_PASSES.index("ssy"))

    def test_programs_give_the_same_registers_before_and_after(self):
        """Ramas sobre un `BRA` entre valores al azar, ejecutadas en el simulador con y sin el pase."""
        inverted = 0
        for seed in range(200):
            rng = random.Random(seed)
            lines = []
            for n in range(6):
                op = rng.choice(sorted(("BEQ", "BNE", "BLT", "BGE", "BLTU", "BGEU")))
                a, b = rng.choice((0, 5, 6, 7)), rng.choice((0, 5, 6, 7))
                lines += [f"{op} R{a}, R{b}, L.{2 * n + 1}", f"BRA L.{2 * n + 2}", f"L.{2 * n + 1}:",
                          f"ADDI R{16 + n}, R{16 + n}, {rng.randint(1, 9)}", f"L.{2 * n + 2}:",
                          f"ADDI R{16 + n}, R{16 + n}, {rng.randint(10, 99)}"]
            init = [f"LI R{r}, {rng.choice(POOL)}" for r in (5, 6, 7)]
            source = ".text\n.globl f\nf:\n" + "\n".join(init + lines) + "\nHALT\n"
            stats: dict = {}
            optimized = optimize(source, ["invert"], stats=stats)
            inverted += stats.get("invert.inverted", 0)
            with self.subTest(seed=seed):
                self.assertEqual(final_registers(optimized, 0), final_registers(source, 0), source + "\n---\n" + optimized)
        self.assertGreater(inverted, 0, "el generador nunca ejercita el pase")


def boolean_block(op: str, a: str, b: str, dest: str, first: int, second: int, base: int = 1,
                  zero: str = "ADD {d}, R0, R0") -> str:
    """`Bcc a,b,Lf ; MOVI dest,first ; BRA Le ; Lf: ; dest = second ; Le:` como lo escribe lcc."""
    def load(value: int) -> str:
        return zero.format(d=dest) if value == 0 else f"MOVI {dest}, {value}"
    return (f"{op} {a}, {b}, L.{base}\n{load(first)}\nBRA L.{base + 1}\nL.{base}:\n{load(second)}\nL.{base + 1}:")


class BooleanTest(unittest.TestCase):
    def run_pass(self, body: str):
        stats: dict = {}
        source = ".text\n.globl f\nf:\n" + body + "\nJR R31\n"
        return lines_of(optimize(source, ["boolean"], stats=stats)), stats

    def test_each_comparison_becomes_the_shortest_sequence(self):
        slt, sltu, xori = "SLT R7, R8, R9", "SLTU R7, R8, R9", "XORI R7, R7, 1"
        ne = ["SUB R7, R8, R9", "SLTU R7, R0, R7"]               # a != b
        cases = {                                                 # (rama, valor que carga al tomarse)
            ("BLT", 1): [slt], ("BLT", 0): [slt, xori],
            ("BGE", 1): [slt, xori], ("BGE", 0): [slt],
            ("BLTU", 1): [sltu], ("BLTU", 0): [sltu, xori],
            ("BGEU", 1): [sltu, xori], ("BGEU", 0): [sltu],
            ("BNE", 1): ne, ("BNE", 0): ne + [xori],
            ("BEQ", 1): ne + [xori], ("BEQ", 0): ne,
        }
        for (op, taken), expected in cases.items():
            with self.subTest(op=op, taken=taken):
                out, stats = self.run_pass(boolean_block(op, "R8", "R9", "R7", 1 - taken, taken))
                out = out[3:]                                     # sin `.text`, `.globl` ni `f:`
                self.assertEqual(out[:len(expected)], expected)
                self.assertEqual(stats["boolean.converted"], 1)
                self.assertNotIn("BRA L.2", out)
                self.assertNotIn("L.1:", out)
                self.assertIn("L.2:", out)

    def test_a_zero_operand_skips_the_subtraction(self):
        out, _ = self.run_pass(boolean_block("BNE", "R8", "R0", "R7", 0, 1))
        self.assertEqual(out[3], "SLTU R7, R0, R8")
        self.assertNotIn("SUB R7, R8, R0", out)

    def test_the_other_ways_of_writing_a_zero_are_accepted(self):
        for zero in ("MOVI {d}, 0", "ADDI {d}, R0, 0"):
            with self.subTest(zero=zero):
                out, stats = self.run_pass(boolean_block("BLT", "R8", "R9", "R7", 1, 0, zero=zero))
                self.assertEqual(stats["boolean.converted"], 1)
                self.assertEqual(out[3], "SLT R7, R8, R9")

    def test_it_is_left_alone_when_something_else_jumps_to_the_false_label(self):
        out, stats = self.run_pass(boolean_block("BLT", "R8", "R9", "R7", 1, 0) + "\nBEQ R3, R4, L.1")
        self.assertNotIn("boolean.converted", stats)
        self.assertIn("BLT R8, R9, L.1", out)

    def test_other_jumps_to_the_end_label_are_fine(self):
        out, stats = self.run_pass("BEQ R3, R4, L.2\n" + boolean_block("BLT", "R8", "R9", "R7", 1, 0))
        self.assertEqual(stats["boolean.converted"], 1)
        self.assertIn("BEQ R3, R4, L.2", out)
        self.assertIn("L.2:", out)

    def test_it_needs_two_different_values_in_the_same_register(self):
        for first, second, dest_second in ((1, 1, "R7"), (0, 0, "R7"), (1, 0, "R10")):
            with self.subTest(first=first, second=second, dest=dest_second):
                body = (f"BLT R8, R9, L.1\nMOVI R7, {first}\nBRA L.2\nL.1:\n"
                        f"MOVI {dest_second}, {second}\nL.2:")
                _, stats = self.run_pass(body)
                self.assertNotIn("boolean.converted", stats)

    def test_other_values_than_zero_and_one_are_left_alone(self):
        _, stats = self.run_pass("BLT R8, R9, L.1\nMOVI R7, 5\nBRA L.2\nL.1:\nMOVI R7, 0\nL.2:")
        self.assertNotIn("boolean.converted", stats)

    def test_it_runs_by_default_before_constprop(self):
        from tools.mini_opt import DEFAULT_PASSES
        self.assertLess(DEFAULT_PASSES.index("boolean"), DEFAULT_PASSES.index("constprop"))

    def test_programs_give_the_same_registers_before_and_after(self):
        """Todas las comparaciones, con el destino a veces igual a un operando, en el simulador."""
        converted = 0
        for seed in range(300):
            rng = random.Random(seed)
            lines = [f"LI R{r}, {rng.choice(POOL)}" for r in range(16, 20)]
            for n in range(6):
                dest = f"R{rng.randrange(16, 24)}"
                operands = [f"R{rng.randrange(16, 20)}" for _ in range(2)]
                if rng.random() < 0.2:
                    operands[rng.randrange(2)] = "R0"
                first = rng.randrange(2)
                lines.append(boolean_block(rng.choice(("BEQ", "BNE", "BLT", "BGE", "BLTU", "BGEU")),
                                           operands[0], operands[1], dest, first, 1 - first, base=2 * n + 1))
            source = ".text\n.globl f\nf:\n" + "\n".join(lines) + "\nHALT\n"
            stats: dict = {}
            optimized = optimize(source, ["boolean"], stats=stats)
            converted += stats.get("boolean.converted", 0)
            with self.subTest(seed=seed):
                self.assertEqual(final_registers(optimized, 0), final_registers(source, 0), source + "\n---\n" + optimized)
        self.assertGreater(converted, 0, "el generador nunca ejercita el pase")


class UnreachableTest(unittest.TestCase):
    def test_blocks_after_an_unconditional_jump_are_removed(self):
        source = (".text\n.globl f\nf:\nBRA L.2\nL.1:\nMOVI R1, 99\nJR R31\n"
                  "L.2:\nMOVI R1, 7\nJR R31\n")
        stats = {}
        out = lines_of(optimize(source, ["unreachable"], stats=stats))
        self.assertNotIn("MOVI R1, 99", out)
        self.assertIn("MOVI R1, 7", out)
        self.assertEqual(stats["unreachable.blocks"], 1)

    def test_it_consumes_a_branch_simplified_by_the_previous_pass(self):
        source = (".text\n.globl f\nf:\nBEQ R5, R5, L.2\nMOVI R1, 99\nJR R31\n"
                  "L.2:\nMOVI R1, 7\nJR R31\n")
        out = lines_of(optimize(source, ["branches", "unreachable"]))
        self.assertIn("BRA L.2", out)
        self.assertNotIn("MOVI R1, 99", out)


class TailCallsTest(unittest.TestCase):
    CALLEE = ".globl g\ng:\nADDI R1, R1, 1\nJR R31\n"

    def optimize_wrapper(self, before_call: str = "MOVI R1, 7", target: str = "g",
                         after_call: str = "") -> tuple[list[str], dict]:
        source = (".text\n" + self.CALLEE + ".globl f\nf:\nADDI R30, R30, -32\n"
                  "STORE R28, R30, 0\nSTORE R31, R30, 16\n" + before_call + "\n"
                  f"JAL R31, {target}\n" + after_call + "L.1:\nLOAD R28, R30, 0\n"
                  "LOAD R31, R30, 16\nADDI R30, R30, 32\nJR R31\n")
        stats = {}
        return lines_of(optimize(source, ["tailcalls", "unreachable"], stats=stats)), stats

    def test_direct_final_call_restores_the_frame_and_becomes_a_jump(self):
        out, stats = self.optimize_wrapper()
        start = out.index("f:")
        tail = out[start:]
        self.assertNotIn("JAL R31, g", tail)
        self.assertNotIn("JR R31", tail)
        self.assertLess(tail.index("LOAD R28, R30, 0"), tail.index("ADDI R30, R30, 32"))
        self.assertLess(tail.index("LOAD R31, R30, 16"), tail.index("ADDI R30, R30, 32"))
        self.assertLess(tail.index("ADDI R30, R30, 32"), tail.index("BRA g"))
        self.assertEqual(stats["tailcalls"], 1)

    def test_a_real_operation_after_the_call_prevents_it(self):
        out, stats = self.optimize_wrapper(after_call="ADDI R1, R1, 2\n")
        self.assertIn("JAL R31, g", out)
        self.assertNotIn("tailcalls", stats)

    def test_an_external_or_private_target_is_not_assumed_safe(self):
        for target in ("external", "__mini_helper"):
            out, stats = self.optimize_wrapper(target=target)
            self.assertIn(f"JAL R31, {target}", out)
            self.assertNotIn("tailcalls", stats)

    def test_a_callee_with_stack_arguments_is_rejected(self):
        source = (".text\n.globl g\ng:\nLOAD R5, R30, 16\nADD R1, R1, R5\nJR R31\n"
                  ".globl f\nf:\nADDI R30, R30, -32\nSTORE R31, R30, 16\n"
                  "JAL R31, g\nLOAD R31, R30, 16\nADDI R30, R30, 32\nJR R31\n")
        stats = {}
        out = lines_of(optimize(source, ["tailcalls"], stats=stats))
        self.assertIn("JAL R31, g", out)
        self.assertNotIn("tailcalls", stats)

    def test_a_callee_that_takes_a_frame_address_is_rejected(self):
        source = (".text\n.globl g\ng:\nADDI R7, R30, 20\nLOAD R1, R7, 0\nJR R31\n"
                  ".globl f\nf:\nADDI R30, R30, -32\nSTORE R31, R30, 16\n"
                  "JAL R31, g\nLOAD R31, R30, 16\nADDI R30, R30, 32\nJR R31\n")
        stats = {}
        out = lines_of(optimize(source, ["tailcalls"], stats=stats))
        self.assertIn("JAL R31, g", out)
        self.assertNotIn("tailcalls", stats)

    def test_a_pointer_into_the_current_frame_is_not_passed_after_releasing_it(self):
        out, stats = self.optimize_wrapper(before_call="ADDI R1, R30, 12")
        self.assertIn("JAL R31, g", out)
        self.assertNotIn("tailcalls", stats)

    def test_a_caller_that_takes_any_frame_address_is_rejected_even_if_it_does_not_pass_it(self):
        for before in ("ADDI R14, R30, 8\nSTORE R14, R15, 0\nMOVI R1, 7",      # la guarda en memoria
                       "ADD R14, R30, R9\nSTORE R14, R15, 0\nMOVI R1, 7",      # offset variable
                       "STORE R30, R15, 0\nMOVI R1, 7"):                       # guarda el propio R30
            with self.subTest(before=before):
                out, stats = self.optimize_wrapper(before_call=before)
                self.assertIn("JAL R31, g", out)
                self.assertNotIn("tailcalls", stats)

    def test_a_local_whose_address_went_to_memory_survives_a_call_to_a_callee_that_overlaps_it(self):
        """f guarda &a en una global y llama a g; g guarda R31 justo donde esta `a` si f ya cerro su frame
        y lee `*gp`. El resultado tiene que ser 5, no la direccion de retorno."""
        source = (".text\n.globl main\nmain:\nMOVI R30, 0x4000\nJAL R31, f\nHALT\n"
                  ".globl g\ng:\nADDI R30, R30, -48\nSTORE R31, R30, 24\nLI R14, gp\nLOAD R14, R14, 0\n"
                  "LOAD R1, R14, 0\nL.1:\nLOAD R31, R30, 24\nADDI R30, R30, 48\nJR R31\n"
                  ".globl f\nf:\nADDI R30, R30, -32\nSTORE R31, R30, 16\nMOVI R15, 5\nSTORE R15, R30, 8\n"
                  "LI R15, gp\nADDI R14, R30, 8\nSTORE R14, R15, 0\nJAL R31, g\n"
                  "L.2:\nLOAD R31, R30, 16\nADDI R30, R30, 32\nJR R31\n.comm gp,4\n")
        stats = {}
        optimized = optimize(source, ["tailcalls", "unreachable"], stats=stats)

        def result(text):
            cpu = CPU(memory_size=1 << 16)
            cpu.load_program(assemble_bytes(text))
            cpu.run(10_000)
            return cpu.regs[1]

        self.assertEqual(result(source), 5)
        self.assertEqual(result(optimized), 5)
        self.assertNotIn("tailcalls", stats)

    def test_a_shared_epilogue_is_kept_for_its_other_predecessor(self):
        out, stats = self.optimize_wrapper(before_call="BEQ R2, R0, L.1\nMOVI R1, 7")
        tail = out[out.index("f:"):]
        self.assertIn("BRA g", tail)
        self.assertIn("JR R31", tail)
        self.assertEqual(tail.count("ADDI R30, R30, 32"), 2)
        self.assertEqual(stats["tailcalls"], 1)


FREE_REGISTERS_LOOP = """.text
.globl f
f:
{prologue}
MOVI R16, 0
BRA L.2
L.1:
ADD R1, R1, R2
ADD R3, R3, R4
ADD R5, R5, R6
ADD R7, R7, R8
MOVI R9, 77
ADD R10, R10, R9
ADD R11, R11, R12
ADD R13, R13, R14
ADD R15, R15, R16
ADDI R16, R16, 1
L.2:
MOVI R17, 10
BLT R16, R17, L.1
{epilogue}
JR R31
"""


class LicmFreeRegistersTest(unittest.TestCase):
    def run_pass(self, prologue: str = "", epilogue: str = ""):
        source = FREE_REGISTERS_LOOP.format(prologue=prologue, epilogue=epilogue)
        return lines_of(optimize(source, ["licm"]))

    def test_r31_is_not_used_while_the_function_still_has_to_return_through_it(self):
        out = self.run_pass()
        self.assertIn("MOVI R9, 77", out[out.index("L.1:"):])             # no hay donde ponerla

    def test_r31_is_free_in_a_loop_that_comes_between_its_save_and_its_restore(self):
        out = self.run_pass("STORE R31, R30, 0", "LOAD R31, R30, 0")
        self.assertIn("MOVI R31, 77", out[:out.index("BRA L.2")])
        self.assertIn("ADD R10, R10, R31", out[out.index("L.1:"):])

    def test_argument_registers_are_used_when_nobody_reads_them(self):
        source = FREE_REGISTERS_LOOP.format(prologue="", epilogue="").replace("ADD R1, R1, R2\nADD R3, R3, R4\n", "")
        out = lines_of(optimize(source, ["licm"]))
        self.assertTrue(any(l in ("MOVI R1, 77", "MOVI R2, 77", "MOVI R3, 77", "MOVI R4, 77")
                            for l in out[:out.index("BRA L.2")]), out)


class SsyMergeTest(unittest.TestCase):
    def test_a_second_branch_with_the_same_join_shares_the_first_region(self):
        source = (".text\n.globl __kernel_k\n__kernel_k:\nGETTID R16\nANDI R7, R16, 1\nBEQ R7, R0, L.2\n"
                  "ANDI R8, R16, 2\nBEQ R8, R0, L.2\nSTORE R16, R1, 0\nL.2:\nEXIT\n")
        stats = {}
        out = lines_of(optimize(source, ["ssy"], stats=stats))
        self.assertEqual(sum(l.startswith("SSY") for l in out), 1)
        self.assertEqual(stats["ssy.merged"], 1)


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


TUI = ROOT / "z.tui"
RCC = ROOT / "y.lcc" / "build" / ("rcc.exe" if sys.platform == "win32" else "rcc")


@unittest.skipUnless((TUI / "tui_unity_mini.c").exists() and RCC.exists()
                     and (shutil.which("cl") or sys.platform != "win32"),
                     "hace falta el submodulo z.tui, y.lcc/build/rcc y un preprocesador de C (cl en el PATH)")
class TuiDemoTest(unittest.TestCase):
    """La demo de z.tui (unas 12.000 instrucciones de C que nadie escribio para `mini-opt`) compilada con
    y sin los pases: tiene que dibujar la misma pantalla, ocupar menos y ejecutar menos."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        temp = Path(cls.temp.name)
        (temp / "keys.bin").write_bytes(b"\x1b")
        cls.runs = {}
        cls.run_tool("mini-lcc", "tui_unity_mini.c", "-o", str(temp / "raw.s"), cwd=TUI)
        cls.run_tool("mini-opt", str(temp / "raw.s"), "-o", str(temp / "opt.s"))
        for name in ("raw", "opt"):
            cls.run_tool("mini-asm", str(temp / f"{name}.s"), "-o", str(temp / f"{name}.bin"))
            done = cls.run_tool("minicpu", str(temp / f"{name}.bin"), "--serial-input", str(temp / "keys.bin"),
                                "--console-output", str(temp / f"{name}.txt"), "--run-limit", "50000000")
            cls.runs[name] = (int(re.search(r"HALT tras (\d+) instrucciones", done.stdout).group(1)),
                              (temp / f"{name}.txt").read_text(encoding="utf-8"),
                              (temp / f"{name}.bin").stat().st_size)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def run_tool(cls, tool: str, *args: str, cwd: Path = ROOT):
        script = ROOT / "2.cpu-sim-func" / "minicpu_sim.py" if tool == "minicpu" else ROOT / "tools" / tool
        done = subprocess.run([sys.executable, str(script), *args], cwd=cwd, capture_output=True, text=True)
        if done.returncode != 0:
            raise AssertionError(f"{tool} {' '.join(args)}\n{done.stdout}\n{done.stderr}")
        return done

    def test_the_screen_is_the_same_with_and_without_the_passes(self):
        raw, optimized = self.runs["raw"][1], self.runs["opt"][1]
        self.assertIn("File", raw.splitlines()[0])
        self.assertIn("F1 Help", raw.splitlines()[29])
        self.assertEqual(optimized, raw)

    def test_it_executes_clearly_fewer_instructions(self):
        raw, optimized = self.runs["raw"][0], self.runs["opt"][0]
        self.assertLess(optimized, raw * 0.95, f"{raw} -> {optimized}")      # medido: -12,7 %

    def test_the_binary_is_smaller(self):
        raw, optimized = self.runs["raw"][2], self.runs["opt"][2]
        self.assertLess(optimized, raw * 0.98, f"{raw} -> {optimized}")       # medido: -3,5 %


if __name__ == "__main__":
    unittest.main()
