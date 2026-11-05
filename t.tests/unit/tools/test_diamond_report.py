"""parse_twr: errores de camino frente a errores de ancho minimo de pulso."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools.diamond_report import parse_twr  # noqa: E402

HEADER = """Preference: FREQUENCY NET "clk_a" 100.000000 MHz ;
            4096 items scored, 0 timing errors detected.
Report:  120.000MHz is the maximum frequency for this preference.
"""

# TRACE escribe "1 timing error detected" en singular.
PULSE_ONLY = HEADER + """Preference: FREQUENCY NET "clk_b" 370.000000 MHz ;
            71 items scored, 1 timing error detected.
Error:  The following path exceeds requirements by 1.297ns

   Destination:    SIOLOGIC   CLK            gpdi_dp[0]_MGIOL
   Delay:               4.000ns -- based on Minimum Pulse Width

Passed: The following path meets requirements by 0.613ns
   Delay:               5.000ns -- based on Minimum Pulse Width
Timing summary (Setup):
Timing errors: 1  Score: 1297
Timing summary (Setup and Hold):
Timing errors: 1 (setup), 0 (hold)
"""

PATH_AND_PULSE = HEADER + """Preference: FREQUENCY NET "clk_b" 370.000000 MHz ;
            71 items scored, 2 timing errors detected.
Error:  The following path exceeds requirements by 0.721ns

   Source:         FF         Q              a  (from clk_b +)
   Delay:               3.311ns  (15.9% logic, 84.1% route), 1 logic levels.

Error:  The following path exceeds requirements by 1.297ns

   Destination:    SIOLOGIC   CLK            gpdi_dp[0]_MGIOL
   Delay:               4.000ns -- based on Minimum Pulse Width

Timing summary (Setup and Hold):
Timing errors: 2 (setup), 0 (hold)
"""


def parse(text: str):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "x.twr"
        path.write_text(text, encoding="utf-8")
        return parse_twr(path)


class ParseTwrTests(unittest.TestCase):
    def test_only_pulse_width_keeps_the_clock_as_met_and_warns(self):
        clocks, errors = parse(PULSE_ONLY)
        self.assertEqual(errors["pulse_width"], 1)
        self.assertIn("clk_b", clocks)  # con "errors" en plural desaparecia de la tabla
        self.assertGreaterEqual(clocks["clk_b"]["achieved"], clocks["clk_b"]["constraint"])

    def test_passed_pulse_width_is_not_counted_as_an_error(self):
        _, errors = parse(PULSE_ONLY)
        self.assertEqual(errors["pulse_width"], 1)  # no 2: el "Passed" de 5 ns no cuenta

    def test_real_path_error_still_fails_and_ignores_the_pulse_width_excess(self):
        clocks, errors = parse(PATH_AND_PULSE)
        self.assertEqual(errors["pulse_width"], 1)
        clk = clocks["clk_b"]
        self.assertLess(clk["achieved"], clk["constraint"])
        # estimada desde 0,721 ns, no desde los 1,297 ns del ancho de pulso
        self.assertAlmostEqual(clk["achieved"], 1000.0 / (1000.0 / 370.0 + 0.721), places=3)


if __name__ == "__main__":
    unittest.main()
