"""`cse` (subexpresiones comunes y cargas, con `; @miniopt alias`) y las variables de induccion de `strength`
que avanzan en el cuerpo del bucle (el `wipe_doMelt` de Doom)."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "1.isa"))
sys.path.insert(0, str(ROOT / "2.cpu-sim-func"))

from mini_asm import assemble_bytes  # noqa: E402
from minicpu_sim import CPU  # noqa: E402
from tools.mini_opt import optimize, parse_unit, render_unit  # noqa: E402

CLEAN = ["cse", "copyprop", "dce"]


def lines_of(text: str) -> list[str]:
    return [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith(";")]


def run(source: str) -> list[int]:
    cpu = CPU(memory_size=1 << 16)
    cpu.load_program(assemble_bytes(source))
    cpu.regs[30] = 0x8000
    cpu.run(100_000)
    return cpu.regs[16:26]


def loads(text: str) -> list[str]:
    return [l for l in lines_of(text) if l.startswith("LOAD")]


def reload(store: str, first: str = "global:a", second: str = "global:a", facts: str = "") -> str:
    """Una carga de `a`, algo en medio y la misma carga otra vez."""
    return (f"{facts}.text\nstart:\nLI R14, L.a\nLI R15, L.b\n"
            f"; @miniopt alias {first}\nLOAD R16, R14, 0\n{store}\n"
            f"; @miniopt alias {second}\nLOAD R17, R14, 0\nHALT\n"
            "g:\nJR R31\nL.a:\n.word 5\nL.b:\n.word 6\n")


class AliasParsingTest(unittest.TestCase):
    def test_the_tag_sticks_to_the_next_instruction_and_is_written_back(self):
        unit = parse_unit(reload("ADD R1, R1, R0"), "x")
        tagged = [l for f in unit.functions() for l in f.body if l.kind == "instr" and l.alias]
        self.assertEqual([(l.op, l.alias) for l in tagged], [("LOAD", "global:a"), ("LOAD", "global:a")])
        self.assertEqual(render_unit(unit).count("; @miniopt alias global:a"), 2)

    def test_volatile_is_kept_in_the_tag(self):
        unit = parse_unit(reload("ADD R1, R1, R0", first="unknown volatile"), "x")
        tagged = [l.alias for f in unit.functions() for l in f.body if l.kind == "instr" and l.alias]
        self.assertEqual(tagged[0], "unknown volatile")


class ReloadTest(unittest.TestCase):
    def reloaded(self, source: str) -> bool:
        out = optimize(source, CLEAN)
        self.assertEqual(run(out)[:2], run(source)[:2])
        return len(loads(out)) == 1

    def test_nothing_in_between_reuses_the_load(self):
        self.assertTrue(self.reloaded(reload("ADD R1, R1, R0")))

    def test_a_store_to_another_global_does_not_kill_it(self):
        self.assertTrue(self.reloaded(reload("; @miniopt alias global:b\nSTORE R0, R15, 0")))

    def test_a_store_to_the_stack_does_not_kill_a_global(self):
        self.assertTrue(self.reloaded(reload("STORE R0, R30, 8")))

    def test_a_word_stored_to_the_same_global_is_read_from_its_register(self):
        self.assertTrue(self.reloaded(reload("MOVI R13, 7\n; @miniopt alias global:a\nSTORE R13, R14, 0")))

    def test_a_halfword_stored_to_the_same_global_kills_it(self):
        self.assertFalse(self.reloaded(reload("MOVI R13, 7\n; @miniopt alias global:a\nSTOREH R13, R14, 0")))

    def test_a_store_whose_value_register_changes_is_reloaded(self):
        self.assertFalse(self.reloaded(reload("MOVI R13, 7\n; @miniopt alias global:a\nSTORE R13, R14, 0\nADDI R13, R13, 1")))

    def test_a_store_through_an_unknown_pointer_kills_it(self):
        self.assertFalse(self.reloaded(reload("; @miniopt alias unknown\nSTORE R0, R15, 0")))

    def test_an_untagged_store_kills_it(self):
        self.assertFalse(self.reloaded(reload("STORE R0, R15, 0")))

    def test_a_call_kills_it(self):
        self.assertFalse(self.reloaded(reload("JAL R31, g")))

    def test_a_volatile_load_is_never_reused(self):
        self.assertFalse(self.reloaded(reload("ADD R1, R1, R0", "global:a volatile", "global:a volatile")))
        self.assertFalse(self.reloaded(reload("ADD R1, R1, R0", facts="; @miniopt volatile a\n")))

    def test_an_untagged_load_is_never_reused(self):
        source = reload("ADD R1, R1, R0").replace("; @miniopt alias global:a\n", "")
        self.assertFalse(self.reloaded(source))


# El bucle de columnas de wipe_doMelt: `y[i]` se calcula, R12 se reutiliza para otra cosa y se recalcula entero
COLUMNS = """\
.text
start:
LI R14, L.ptr
MOVI R27, 0
MOVI R16, 0
MOVI R13, 3
L.0:
SHLI R12, R27, 2
; @miniopt alias global:y
LOAD R11, R14, 0
ADD R12, R12, R11
; @miniopt alias unknown
LOAD R12, R12, 0
BGE R12, R0, L.1
ADDI R16, R16, 100
L.1:
SHLI R12, R27, 2
; @miniopt alias global:y
LOAD R11, R14, 0
ADD R12, R12, R11
; @miniopt alias unknown
LOAD R12, R12, 0
ADD R16, R16, R12
ADDI R27, R27, 1
BLT R27, R13, L.0
HALT
L.ptr:
.word L.arr
L.arr:
.word 5, -7, 9
"""


class KeptValueTest(unittest.TestCase):
    def test_a_value_nobody_holds_is_kept_in_a_free_register(self):
        stats: dict = {}
        out = optimize(COLUMNS, CLEAN, stats=stats)
        self.assertEqual(run(out), run(COLUMNS))
        self.assertEqual(run(COLUMNS)[0], 5 - 7 + 100 + 9)
        self.assertEqual(len(loads(out)), 2)                     # `y` e `y[i]`, una vez por vuelta
        self.assertGreaterEqual(stats.get("cse.kept", 0), 1)

    def test_a_store_through_the_element_in_between_keeps_the_reloads(self):
        source = COLUMNS.replace("ADDI R16, R16, 100\n", "ADDI R16, R16, 100\n; @miniopt alias unknown\nSTORE R0, R12, 0\n")
        out = optimize(source, CLEAN)
        self.assertEqual(run(out), run(source))
        self.assertGreater(len(loads(out)), 2)


# El bucle interno de wipe_doMelt: `d[idx] = *(s++); idx += width;` con `s` e `idx` avanzando en el cuerpo y el
# contador del `for` en el ultimo bloque
MELT = """\
.text
start:
LI R10, L.dst
LI R4, L.src
MOVI R15, 2
ADD R9, R0, R0
MOVI R29, 4
BRA L.3
L.1:
ADD R12, R4, R0
ADDI R4, R4, 2
SHLI R11, R9, 1
ADD R11, R11, R10
LOADH R12, R12, 0
STOREH R12, R11, 0
ADD R9, R9, R15
L.2:
ADDI R29, R29, -1
L.3:
BNE R29, R0, L.1
LI R1, L.dst
LOAD R16, R1, 0
LOAD R17, R1, 4
LOAD R18, R1, 8
LOAD R19, R1, 12
HALT
L.src:
.word 0x00020001, 0x00040003
L.dst:
.word 0, 0, 0, 0
"""


class BodyInductionTest(unittest.TestCase):
    def loop(self, text: str) -> list[str]:
        out = lines_of(text)
        return out[out.index("L.1:") + 1:out.index("BNE R29, R0, L.1") + 1]

    def test_the_melt_loop_advances_two_pointers(self):
        stats: dict = {}
        out = optimize(MELT, ["strength"], stats=stats)
        self.assertEqual(run(out), run(MELT))
        self.assertEqual(run(MELT)[:4], [1, 2, 3, 4])            # cada short, una fila (2 shorts) mas abajo
        body = [l for l in self.loop(out) if not l.endswith(":")]
        self.assertEqual(len(body), 6)                           # LOADH, STOREH, tres sumas y el salto
        self.assertEqual(stats["strength.dead_ivs"], 2)          # `s` e `idx` ya no los lee nadie

    def test_an_induction_variable_read_after_the_loop_stays(self):
        source = MELT.replace("LOAD R19, R1, 12\n", "LOAD R19, R1, 12\nADD R20, R9, R0\n")
        out = optimize(source, ["strength"])
        self.assertEqual(run(out), run(source))
        self.assertIn("ADD R9, R9, R15", lines_of(out))

    def test_a_counter_only_used_to_exit_becomes_a_pointer_compare(self):
        source = MELT.replace("R29", "R13")                     # caller-saved: HALT no lo lee, no sale vivo
        stats: dict = {}
        out = optimize(source, ["strength"], stats=stats)
        self.assertEqual(run(out), run(source))
        body = lines_of(out)[lines_of(out).index("L.1:") + 1:]
        body = body[:next(i for i, l in enumerate(body) if l.startswith("BNE")) + 1]
        self.assertEqual(len([l for l in body if not l.endswith(":")]), 5)  # LOADH, STOREH, dos sumas, BNE
        self.assertEqual(stats["strength.counters"], 1)
        self.assertNotIn("R13", body[-1])

    def test_a_counter_with_a_zero_trip_count_still_skips_the_loop(self):
        source = MELT.replace("R29", "R13").replace("MOVI R13, 4", "MOVI R13, 0")
        out = optimize(source, ["strength"])
        self.assertEqual(run(out), run(source))
        self.assertEqual(run(source)[:4], [0, 0, 0, 0])

    def test_a_counter_read_inside_the_loop_stays(self):
        source = MELT.replace("R29", "R13").replace("STOREH R12, R11, 0\n", "STOREH R12, R11, 0\nADD R20, R20, R13\n")
        stats: dict = {}
        out = optimize(source, ["strength"], stats=stats)
        self.assertEqual(run(out), run(source))
        self.assertEqual(stats.get("strength.counters", 0), 0)

    def test_a_step_that_sometimes_runs_is_not_an_induction_variable(self):
        source = MELT.replace("ADD R9, R9, R15\nL.2:\n", "BEQ R12, R0, L.2\nADD R9, R9, R15\nL.2:\n")
        stats: dict = {}
        out = optimize(source, ["strength"], stats=stats)
        self.assertEqual(run(out), run(source))
        self.assertIn("ADD R9, R9, R15", lines_of(out))


if __name__ == "__main__":
    unittest.main()
