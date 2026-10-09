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
        out, _ = self.run_pass("ADD R13, R28, R0\nSTORE R13, R1, 0")
        self.assertIn("ADD R13, R28, R0", out)


class DceTest(unittest.TestCase):
    def test_it_is_an_independent_pass_and_keeps_effects_and_the_return_value(self):
        source = ".text\n.globl f\nf:\nMOVI R8, 5\nLOAD R9, R2, 0\nADD R1, R7, R0\nJR R31\n"
        stats = {}
        out = lines_of(optimize(source, ["dce"], stats=stats))
        self.assertNotIn("MOVI R8, 5", out)
        self.assertIn("LOAD R9, R2, 0", out)
        self.assertIn("ADD R1, R7, R0", out)
        self.assertEqual(stats["dce.removed"], 1)


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


if __name__ == "__main__":
    unittest.main()
