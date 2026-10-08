"""El arranque (crt0) fuera del compilador: `mini-lcc --no-crt` + `1.isa/runtime/crt0.s`.

Sin compilador (la prueba de `crt0.s` con un `main` escrito a mano) siempre corre. La que
pasa por `rcc` necesita el `build/rcc.exe` de `y.lcc` y MSVC para preprocesar, y se omite
si faltan.
"""

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "1.isa"))

from mini_asm import assemble_bytes, first_pass  # noqa: E402

RUNTIME = ROOT / "1.isa" / "runtime"
RCC = ROOT / "y.lcc" / "build" / ("rcc.exe" if sys.platform == "win32" else "rcc")

MAIN = """\
.globl main
main:
MOVI R1, 55
JR R31
"""

C_SOURCE = """\
int sum(int n) { int s = 0, i; for (i = 1; i <= n; i++) s += i; return s; }
int main(void) { return sum(10); }
"""


def program(*files):
    return "".join(f'.include "{name}"\n' for name in files)


class Crt0Test(unittest.TestCase):
    def test_start_is_at_address_zero_and_calls_main(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "main.s").write_text(MAIN, encoding="utf-8")
            source = program("crt0.s", "main.s")
            _, labels, _, _ = first_pass(source, Path(temp), "prog.asm", (RUNTIME,))
            self.assertEqual(labels["_start"], 0)
            self.assertGreater(labels["main"], 0)
            assemble_bytes(source, Path(temp), "prog.asm", (RUNTIME,))

    def test_crt0_can_be_included_twice(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "main.s").write_text(MAIN, encoding="utf-8")
            source = program("crt0.s", "crt0.s", "main.s")      # `.once`
            assemble_bytes(source, Path(temp), "prog.asm", (RUNTIME,))

    def test_a_unit_without_main_links_next_to_the_crt0(self):
        """Lo que motiva todo: unos kernels sin `main` y un anfitrion con `main`."""
        kernels = ".globl k\nk:\nMOVI R2, 1\nJR R31\nL.1:\nHALT\n"
        host = ".globl main\nmain:\nJAL R31, k\nL.1:\nJR R31\n"       # L.1 tambien
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "k.s").write_text(kernels, encoding="utf-8")
            (Path(temp) / "host.s").write_text(host, encoding="utf-8")
            assemble_bytes(program("crt0.s", "host.s", "k.s"), Path(temp), "prog.asm", (RUNTIME,))


@unittest.skipUnless(RCC.exists() and (shutil.which("cl") or sys.platform != "win32"),
                     "hace falta y.lcc/build/rcc y un preprocesador de C (cl en el PATH)")
class CompiledProgramTest(unittest.TestCase):
    def test_no_crt_output_has_no_startup_and_runs_with_crt0(self):
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            (temp / "p.c").write_text(C_SOURCE, encoding="utf-8")
            done = subprocess.run([sys.executable, str(ROOT / "tools" / "mini-lcc"), str(temp / "p.c"),
                                   "--no-crt", "-o", str(temp / "p.s")],
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            text = (temp / "p.s").read_text(encoding="utf-8")
            self.assertNotIn("_start", text)
            self.assertNotIn("__stack", text)
            (temp / "prog.asm").write_text(program("crt0.s", "p.s"), encoding="utf-8")
            done = subprocess.run([sys.executable, str(ROOT / "tools" / "mini-asm"), str(temp / "prog.asm"),
                                   "-I", str(RUNTIME), "-o", str(temp / "prog.bin")],
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            done = subprocess.run([sys.executable, str(ROOT / "tools" / "cpusim"), str(temp / "prog.bin"),
                                   "--run-limit", "100000"], capture_output=True, text=True)
            self.assertRegex(done.stdout, r"HALT tras \d+ instrucciones")
            self.assertEqual(int(re.search(r"R01 = 0x([0-9A-Fa-f]+)", done.stdout).group(1), 16), 55)


if __name__ == "__main__":
    unittest.main()
