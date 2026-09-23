"""Regresión cruzada del fuego: modelo Python contra MiniISA ejecutada."""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIRE_DIR = ROOT / "x.tests" / "cases" / "video" / "fire"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "1.isa"))
sys.path.insert(0, str(ROOT / "x.tests"))

from mini_asm import assemble_bytes
from backends.simulator import SimulatorBackend


def load_fire_model():
    spec = importlib.util.spec_from_file_location("fire_reference", FIRE_DIR / "fire.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FireReferenceTest(unittest.TestCase):
    def test_palette_boundaries(self):
        fire = load_fire_model().Fire
        self.assertEqual(fire.rgb565(0), 0x0000)
        self.assertEqual(fire.rgb565(63), 0xF800)
        self.assertEqual(fire.rgb565(64), 0xF800)
        self.assertEqual(fire.rgb565(191), 0xFFE0)
        self.assertEqual(fire.rgb565(192), 0xFFE0)
        self.assertEqual(fire.rgb565(255), 0xFFFF)

    def test_frame_three_matches_executed_assembly(self):
        model = load_fire_model().Fire()
        for _ in range(3):
            model.step()

        source = (FIRE_DIR / "fire.asm").read_text(encoding="utf-8")
        program = assemble_bytes(
            source,
            FIRE_DIR,
            "fire.asm",
            (ROOT / "x.tests" / "inc",),
        )
        result = SimulatorBackend(ROOT).run(
            program=program,
            initial_memory=[],
            register_numbers=set(),
            memory_ranges=[],
            max_instructions=2_000_000,
            timeout_seconds=10,
            video={"run_until_swap": 3, "capture_frame": True},
        )

        self.assertFalse(result["error"])
        self.assertTrue(result["halted"])
        self.assertEqual(result["video"]["swaps"], 3)
        self.assertEqual(result["video"]["frame"], model.render_rgb565())


if __name__ == "__main__":
    unittest.main()
