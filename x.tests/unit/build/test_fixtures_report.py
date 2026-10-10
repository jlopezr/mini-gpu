"""Pruebas de `fixtures-report`: la matriz y las tres comprobaciones.

Una comprobacion que nunca ha fallado no se sabe si funciona, y el informe real
sale limpio. Aqui se provoca cada fallo a mano sobre un arbol de mentira.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools import fixtures_report as report  # noqa: E402
from tools import make_rtl_fixtures as gen  # noqa: E402
from tools import stage_programs  # noqa: E402


def _caso(name, requires=(), exclude=()):
    return gen.Case(name, "HALT", None, tuple(requires), tuple(exclude))


class MatrizTest(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        # 01 tiene la ALU con MUL/DIV; 02 no.
        self.con = self.proto("01.con", {"gpu_lane.v": "case OPCODE_MUL: x"})
        self.sin = self.proto("02.sin", {"gpu_lane.v": "nada"})

    def proto(self, nombre, ficheros):
        d = self.base / nombre
        d.mkdir()
        for f, texto in ficheros.items():
            (d / f).write_text(texto, encoding="utf-8")
        return d

    def filas(self, casos):
        return report.build_matrix(ROOT, [self.con, self.sin], casos)

    def test_numero_nn_o_omision_por_prototipo(self):
        (_, celdas), (_, otra) = self.filas([_caso("a", ["mul_div"]), _caso("b")])
        self.assertEqual(celdas["01"], (0, []))
        self.assertEqual(celdas["02"], (None, ["falta mul_div"]))
        # `b` es el primero que le toca a 02, no el segundo: la numeracion sigue a la seleccion.
        self.assertEqual(otra["01"][0], 1)
        self.assertEqual(otra["02"][0], 0)

    def test_la_exclusion_se_ve_con_su_motivo(self):
        (_, celdas), = self.filas([_caso("a", exclude=["02"])])
        self.assertEqual(celdas["02"], (None, ["excluido"]))

    def test_render_dice_el_motivo_de_cada_omision(self):
        texto = report.render_matrix(self.filas([_caso("a", ["mul_div"]), _caso("b")]), ["01", "02"])
        self.assertIn("a en 02: falta mul_div", texto)
        self.assertNotIn("b en", texto)
        primera = texto.splitlines()[1]
        self.assertTrue(primera.startswith("a") and primera.rstrip().endswith("-"), primera)

    def test_sin_omisiones_no_hay_seccion(self):
        self.assertNotIn("Omisiones", report.render_matrix(self.filas([_caso("b")]), ["01", "02"]))


class ComprobacionesTest(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.fuentes = self.base / "x.tests"
        (self.fuentes / "cases-gpu" / "demos").mkdir(parents=True)
        for carpeta in ("cases-cpu", "cases-shared"):
            (self.fuentes / carpeta).mkdir()
        for atributo, valor in (("FUENTES", self.fuentes), ("ROOT", self.base)):
            patcher = mock.patch.object(stage_programs, atributo, valor)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.proto = self.base / "22.p"
        self.proto.mkdir()

    def banco(self, programa):
        (self.proto / "x_tb.v").write_text(
            f'$readmemh("generated/programs/{programa}.hex", m);\n', encoding="utf-8")

    def demo(self, nombre, readme=None, test_json=None):
        d = self.fuentes / "cases-gpu" / "demos" / nombre
        d.mkdir()
        (d / f"{nombre}.asm").write_text("HALT\n", encoding="utf-8")
        if readme is not None:
            (d / "README.md").write_text(readme, encoding="utf-8")
        if test_json is not None:
            (d / "test.json").write_text(json.dumps(test_json), encoding="utf-8")
        return d

    def problemas(self, filas=()):
        return report.check(self.base, list(filas), [self.proto])

    def test_programa_inexistente(self):
        self.banco("fantasma")
        (problema,) = self.problemas()
        self.assertIn("pide generated/programs/fantasma.hex y no hay fantasma.asm", problema)

    def test_una_ruta_mencionada_solo_en_un_comentario_no_se_prepara(self):
        (self.proto / "x_tb.v").write_text(
            '// antes: $readmemh("generated/programs/antiguo.hex", m);\n', encoding="utf-8")
        self.assertEqual(stage_programs.pedidos(self.proto), {})

    def test_stage_genera_solo_el_hex_que_lee_el_banco(self):
        self.demo("plasma")
        self.banco("plasma")
        self.assertEqual(stage_programs.stage(self.proto), 0)
        destino = self.proto / "generated" / "programs"
        self.assertTrue((destino / "plasma.hex").is_file())
        self.assertFalse((destino / "plasma.bin").exists())

    def test_programa_sin_caso_ni_readme(self):
        self.demo("huerfano")
        self.banco("huerfano")
        (problema,) = self.problemas()
        self.assertIn("ningún caso ni README documenta", problema)

    def test_documentado_por_un_caso_que_lo_ejecuta(self):
        self.demo("plasma", test_json={"program": "plasma.asm"})
        self.banco("plasma")
        self.assertEqual(self.problemas(), [])

    def test_un_caso_de_la_misma_carpeta_que_ejecuta_otro_programa_no_basta(self):
        d = self.demo("variante", test_json={"program": "otro.asm"})
        self.banco("variante")
        self.assertEqual(len(self.problemas()), 1)
        (d / "README.md").write_text("Usa `variante.asm` para medir.\n", encoding="utf-8")
        self.assertEqual(self.problemas(), [])

    def test_documentado_por_un_readme_que_lo_nombra(self):
        self.demo("calib", readme="# calib\n\n`calib.asm` mide el reloj.\n")
        self.banco("calib")
        self.assertEqual(self.problemas(), [])

    def test_readme_que_no_lo_nombra_no_vale(self):
        self.demo("calib", readme="# otra cosa\n")
        self.banco("calib")
        self.assertEqual(len(self.problemas()), 1)

    def test_fuente_duplicada(self):
        self.demo("doble")
        otra = self.fuentes / "cases-gpu" / "otra"
        otra.mkdir()
        (otra / "doble.asm").write_text("HALT\n", encoding="utf-8")
        self.banco("doble")
        (problema,) = self.problemas()
        self.assertIn("mas de una vez", problema)

    def test_caso_diferencial_que_ningun_prototipo_usa(self):
        filas = [(_caso("usado"), {"22": (0, [])}), (_caso("huerfano"), {"22": (None, ["excluido"])})]
        (problema,) = self.problemas(filas)
        self.assertEqual(problema, "caso diferencial que ningún prototipo usa: huerfano")

    def test_todo_en_orden(self):
        self.demo("ok", test_json={"program": "ok.asm"})
        self.banco("ok")
        self.assertEqual(self.problemas([(_caso("a"), {"22": (0, [])})]), [])


class RepositorioTest(unittest.TestCase):

    def test_el_repo_no_tiene_problemas_de_fixtures(self):
        prototipos = report.differential_prototypes(ROOT)
        self.assertGreaterEqual(len(prototipos), 5)
        filas = report.build_matrix(ROOT, prototipos)
        self.assertEqual(report.check(ROOT, filas, prototipos), [])


if __name__ == "__main__":
    unittest.main()
