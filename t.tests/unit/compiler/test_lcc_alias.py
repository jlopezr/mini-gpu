"""`; @miniopt alias ETIQUETA`: lo que mini-lcc dice de cada LOAD/STORE (ver `alias_` en u.lcc/src/mini.md).

Cada anotacion va justo delante de su instruccion de memoria y vale solo para ella. Dos etiquetas distintas, ninguna
`unknown`, son objetos que no se solapan; la misma etiqueta no dice nada. Necesita el `build/rcc` de `u.lcc` y un
preprocesador de C, y se omite si faltan.
"""

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RCC = ROOT / "u.lcc" / "build" / ("rcc.exe" if sys.platform == "win32" else "rcc")
ALIAS = re.compile(r"^; @miniopt alias (\S+)$")
MEMORY = re.compile(r"^(LOAD|STORE)[A-Z]*\s+(R\d+),\s*(R\d+),\s*(\S+)$")


def compile_c(source: str, *flags: str) -> list[str]:
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        (temp / "p.c").write_text(source, encoding="utf-8")
        done = subprocess.run([sys.executable, str(ROOT / "tools" / "mini-lcc"), str(temp / "p.c"), "--no-crt",
                               *flags, "-o", str(temp / "p.s")], capture_output=True, text=True)
        if done.returncode:
            raise AssertionError(done.stdout + done.stderr)
        return (temp / "p.s").read_text(encoding="utf-8").splitlines()


def accesses(lines: list[str]) -> list[tuple[str, str]]:
    """(etiqueta, instruccion) de cada anotacion, comprobando que la sigue una instruccion de memoria."""
    out = []
    for i, line in enumerate(lines):
        match = ALIAS.match(line)
        if match:
            following = lines[i + 1]
            if not MEMORY.match(following):
                raise AssertionError(f"`{line}` no va delante de un LOAD/STORE: `{following}`")
            out.append((match.group(1), following))
    return out


def tags(source: str, *flags: str) -> list[str]:
    return [tag for tag, _ in accesses(compile_c(source, *flags))]


@unittest.skipUnless(RCC.exists() and (shutil.which("cl") or sys.platform != "win32"),
                     "hace falta u.lcc/build/rcc y un preprocesador de C (cl en el PATH)")
class AliasFactsTest(unittest.TestCase):
    def test_a_global_and_a_field_of_a_global_are_the_global(self):
        found = tags("int y[8]; struct { int a, b; } s;\n"
                     "void f(int i) { y[i] = 1; s.b = 2; }\n")
        self.assertEqual(found, ["global:y", "global:s"])      # `s.b` es el simbolo calculado `s+4`: su base

    def test_a_local_pointer_keeps_the_object_it_was_set_to(self):
        found = tags("int y[8];\n"
                     "int f(int i) { int *p = y + 2; p += i; return *p; }\n")
        self.assertEqual(found, ["global:y"])

    def test_two_objects_reaching_one_pointer_are_unknown(self):
        found = tags("int a[4], b[4];\n"
                     "int f(int n) { int *p = n ? a : b; return *p; }\n")
        self.assertEqual(found, ["unknown"])

    def test_what_comes_from_memory_or_from_the_caller_is_unknown(self):
        found = tags("int *gp;\n"
                     "int f(int *arg) { return *gp + *arg; }\n")
        self.assertEqual(found, ["global:gp", "unknown", "unknown"])  # leer `gp` es leer el global; `*gp` no

    def test_a_pointer_whose_address_is_taken_is_not_followed(self):
        found = tags("int y[4]; void g(int **);\n"
                     "int f(void) { int *p = y; g(&p); return *p; }\n")
        self.assertEqual(found[-1], "unknown")                  # `g` puede cambiar `p`

    def test_an_allocator_call_is_a_fresh_object_numbered_by_site(self):
        source = ("void *malloc(unsigned); void *Z_Malloc(int, int, void *);\n"
                  "int f(int n) { int *p = malloc(8); int *q = malloc(8); int *z = Z_Malloc(8, 1, 0);\n"
                  "               p[0] = n; q[0] = n; z[0] = n; return p[1]; }\n")
        def through_pointers(*flags):                        # sin las de las propias variables en la pila
            return [tag for tag in tags(source, *flags) if not tag.startswith("local:")]
        self.assertEqual(through_pointers(), ["fresh:f.malloc#1", "fresh:f.malloc#2", "unknown", "fresh:f.malloc#1"])
        self.assertEqual(through_pointers("--allocator", "Z_Malloc")[2], "fresh:f.Z_Malloc#3")

    def test_sibling_blocks_that_share_a_stack_slot_share_the_tag(self):
        # lcc da el mismo hueco a `a` y a `b` (blockend restaura el desplazamiento): son los mismos bytes, asi que
        # no pueden llevar etiquetas distintas
        lines = compile_c("void g(int *);\n"
                          "int f(void) { int s = 0; { int a = 1; g(&a); s += a; } { int b = 2; g(&b); s += b; }"
                          " return s; }\n")
        stack = [(tag, instr) for tag, instr in accesses(lines) if tag.startswith("local:")]
        self.assertEqual(len({MEMORY.match(instr).group(4) for _, instr in stack}), 1)
        self.assertEqual({tag for tag, _ in stack}, {"local:f.a"})

    def test_the_parameters_of_a_variadic_function_are_one_object(self):
        found = tags("#include <stdarg.h>\n"
                     "int f(int n, ...) { va_list ap; int s; va_start(ap, n); s = va_arg(ap, int);"
                     " va_end(ap); return s + n; }\n")
        self.assertIn("local:f.$args", found)
        self.assertNotIn("local:f.n", found)

    def test_a_64_bit_access_has_one_annotation_per_word(self):
        found = accesses(compile_c("long long w; void f(void) { w = w + 1; }\n"))
        self.assertEqual([tag for tag, _ in found], ["global:w"] * 4)
        self.assertEqual([instr.split()[0] for _, instr in found], ["LOAD", "LOAD", "STORE", "STORE"])

    def test_no_alias_turns_them_off(self):
        lines = compile_c("int y[8]; void f(int i) { y[i] = 1; }\n", "--no-alias")
        self.assertFalse([line for line in lines if ALIAS.match(line)])


if __name__ == "__main__":
    unittest.main()
