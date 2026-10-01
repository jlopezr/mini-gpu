"""Pruebas del generador compartido de fixtures diferenciales de RTL.

Lo que importa aqui es lo que el banco no puede comprobar por si mismo: que
el filtrado por `requires` omite lo que toca, que el orden es estable (la
numeracion `NN` es lo que enlaza el .hex con el nombre del caso) y que el
formato de salida es el que leen los `$readmemh`.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import make_rtl_fixtures as gen  # noqa: E402

HALT = "HALT"


def _caso(name, requires=(), source=HALT, config=None):
    return gen.Case(name, source, config, tuple(requires))


class SeleccionPorRequiresTest(unittest.TestCase):

    def test_sin_requires_entra_en_todos_los_prototipos(self):
        casos = [_caso("a"), _caso("b")]
        self.assertEqual(gen.select_cases(casos, ()), casos)

    def test_se_omite_el_caso_al_que_le_falta_una_capacidad(self):
        casos = [_caso("a"), _caso("b", ["video"]), _caso("c", ["mul_div"])]
        elegidos = gen.select_cases(casos, ["mul_div"])
        self.assertEqual([c.name for c in elegidos], ["a", "c"])

    def test_hacen_falta_todas_las_capacidades_no_una(self):
        caso = _caso("a", ["video", "frame_capture"])
        self.assertEqual(gen.select_cases([caso], ["video"]), [])
        self.assertEqual(gen.select_cases([caso], ["video", "frame_capture", "x"]), [caso])

    def test_el_orden_es_el_de_declaracion(self):
        casos = [_caso(n) for n in ("z", "a", "m")]
        self.assertEqual([c.name for c in gen.select_cases(casos, ())], ["z", "a", "m"])

    def test_los_omitidos_dicen_que_capacidades_faltan(self):
        casos = [_caso("a"), _caso("b", ["video", "mul_div"])]
        (omitido, faltan), = gen.skipped_cases(casos, ["mul_div"])
        self.assertEqual((omitido.name, faltan), ("b", ["video"]))

    def test_seleccionados_y_omitidos_son_complementarios(self):
        casos = [_caso("a"), _caso("b", ["video"]), _caso("c", ["x"])]
        for capacidades in ([], ["video"], ["x", "video"]):
            elegidos = {c.name for c in gen.select_cases(casos, capacidades)}
            omitidos = {c.name for c, _ in gen.skipped_cases(casos, capacidades)}
            self.assertEqual(elegidos | omitidos, {"a", "b", "c"})
            self.assertFalse(elegidos & omitidos)


class ListaDeCasosTest(unittest.TestCase):

    def test_los_nombres_no_se_repiten(self):
        nombres = [c.name for c in gen.cases]
        self.assertEqual(len(nombres), len(set(nombres)))

    def test_el_orden_de_la_lista_es_determinista(self):
        """Los programas con azar usan semilla fija: dos importaciones, mismo texto."""
        import importlib
        antes = [(c.name, c.source) for c in gen.cases]
        importlib.reload(gen)
        self.assertEqual([(c.name, c.source) for c in gen.cases], antes)


class FormatoTest(unittest.TestCase):

    EXTENSIONES = {".asm", ".bin", ".program.hex", ".regs.hex", ".memory.hex",
                   ".config.hex", ".counts.hex", ".state.hex"}

    def _generar(self, casos):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name) / "fixtures"
        n = gen.write_fixtures(casos, out)
        return out, n

    def test_ficheros_por_caso_y_metadatos(self):
        casos = [_caso("uno", source="MOVI R3, 5\nHALT"), _caso("dos")]
        out, n = self._generar(casos)
        self.assertEqual(n, 2)
        nombres = {p.name for p in out.iterdir()}
        esperados = {f"{i:02d}{ext}" for i in range(2) for ext in self.EXTENSIONES}
        self.assertEqual(nombres, esperados | {"manifest.json", "count.vh"})
        self.assertEqual((out / "count.vh").read_text().strip(), "localparam CASES=2;")
        manifiesto = json.loads((out / "manifest.json").read_text())
        self.assertEqual([m["name"] for m in manifiesto], ["uno", "dos"])
        self.assertEqual([m["id"] for m in manifiesto], [0, 1])

    def test_formato_de_los_hex(self):
        out, _ = self._generar([_caso("a", source="MOVI R3, 5\nHALT")])
        programa = (out / "00.program.hex").read_text().split()
        self.assertEqual(len(programa), 256)
        for archivo, palabras in (("regs", 8 * 8 * 32), ("config", 8 * 3),
                                  ("counts", 8), ("state", 8 * 3), ("memory", 512)):
            lineas = (out / f"00.{archivo}.hex").read_text().split()
            self.assertEqual(len(lineas), palabras, archivo)
            self.assertTrue(all(len(l) == 8 and int(l, 16) >= 0 for l in lineas), archivo)

    def test_la_numeracion_sigue_a_la_seleccion(self):
        casos = [_caso("a"), _caso("b", ["video"]), _caso("c")]
        out, n = self._generar(gen.select_cases(casos, []))
        self.assertEqual(n, 2)
        self.assertEqual([m["name"] for m in json.loads((out / "manifest.json").read_text())], ["a", "c"])
        self.assertFalse((out / "02.asm").exists())

    def test_un_programa_que_falla_en_el_simulador_aborta(self):
        with self.assertRaises(Exception):
            self._generar([_caso("mal", source="LOAD R1, R0, 0x7ffff0\nHALT")])


class ConsumidorTest(unittest.TestCase):

    def test_detecta_el_banco_que_incluye_count_vh(self):
        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp)
            self.assertFalse(gen.consumes_fixtures(carpeta))
            (carpeta / "otro_tb.v").write_text("module t; endmodule\n")
            self.assertFalse(gen.consumes_fixtures(carpeta))
            (carpeta / "gpu_system_bl8_tb.v").write_text('`include "fixtures/count.vh"\n')
            self.assertTrue(gen.consumes_fixtures(carpeta))

    def test_los_prototipos_diferenciales_del_repo(self):
        for numero, esperado in (("12", True), ("22", True), ("29", True), ("21", False)):
            carpeta = next(ROOT.glob(f"{numero}.*"))
            self.assertEqual(gen.consumes_fixtures(carpeta), esperado, carpeta.name)


if __name__ == "__main__":
    unittest.main()
