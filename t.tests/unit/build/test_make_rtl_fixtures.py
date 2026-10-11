"""Pruebas del generador compartido de fixtures diferenciales de RTL.

Lo que importa aqui es lo que el banco no puede comprobar por si mismo: que
el filtrado por `requires` omite lo que toca, que el orden es estable (la
numeracion `NN` es lo que enlaza el .hex con el nombre del caso), que la marca
`rtl` de los casos se lee y se valida, y que el formato de salida es el que
leen los `$readmemh`.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools import make_rtl_fixtures as gen  # noqa: E402

HALT = "HALT"
EIGHT_WARPS = {"warp_size": 8, "warps": [{"id": w, "pc": 0, "active_mask": 255} for w in range(8)]}


def _caso(name, requires=(), source=HALT, config=None, exclude=()):
    return gen.Case(name, source, config, tuple(requires), tuple(exclude))


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
        (omitido, motivos), = gen.skipped_cases(casos, ["mul_div"])
        self.assertEqual((omitido.name, motivos), ("b", ["falta video"]))

    def test_seleccionados_y_omitidos_son_complementarios(self):
        casos = [_caso("a"), _caso("b", ["video"]), _caso("c", ["x"]), _caso("d", exclude=["12"])]
        for capacidades in ([], ["video"], ["x", "video"]):
            elegidos = {c.name for c in gen.select_cases(casos, capacidades, "12")}
            omitidos = {c.name for c, _ in gen.skipped_cases(casos, capacidades, "12")}
            self.assertEqual(elegidos | omitidos, {"a", "b", "c", "d"})
            self.assertFalse(elegidos & omitidos)


class ExclusionTest(unittest.TestCase):

    def test_exclude_omite_solo_en_ese_prototipo(self):
        caso = _caso("a", exclude=["12"])
        self.assertEqual(gen.select_cases([caso], (), "12"), [])
        self.assertEqual(gen.select_cases([caso], (), "14"), [caso])

    def test_sin_prototipo_no_se_excluye_nada(self):
        caso = _caso("a", exclude=["12"])
        self.assertEqual(gen.select_cases([caso], ()), [caso])

    def test_el_motivo_de_la_exclusion_se_dice(self):
        (omitido, motivos), = gen.skipped_cases([_caso("a", ["video"], exclude=["12"])], [], "12")
        self.assertEqual(motivos, ["falta video", "excluido"])

    def test_numero_de_prototipo_desde_la_carpeta(self):
        self.assertEqual(gen.prototype_number(Path("12.fpga-gpu")), "12")
        self.assertEqual(gen.prototype_number(Path("29.fpga-gpu-sm-pipeline")), "29")


class CasosMarcadosTest(unittest.TestCase):
    """Lectura de la marca `rtl` de los test.json."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)

    def caso(self, ruta, rtl="default", programa="HALT\n", warps=None, **extra):
        d = self.base / ruta
        d.mkdir(parents=True)
        (d / "program.asm").write_text(programa, encoding="utf-8")
        (d / "warps.json").write_text(json.dumps(warps or {"warp_size": 8, "warps": [{"id": 0}]}),
                                      encoding="utf-8")
        raw = {"architecture": "gpu", "name": ruta, "program": "program.asm",
               "warp_config": "warps.json", "expect": {}, **extra}
        if rtl == "default":
            rtl = {"differential": True}
        if rtl is not None:
            raw["rtl"] = rtl
        (d / "test.json").write_text(json.dumps(raw), encoding="utf-8")
        return d

    def nombres(self):
        return [c.name for c in gen.load_marked_cases(self.base)]

    def test_solo_los_marcados(self):
        self.caso("a/uno")
        self.caso("a/dos", rtl=None)
        self.caso("a/tres", rtl={"differential": False})
        self.assertEqual(self.nombres(), ["a/uno"])

    def test_orden_por_ruta_y_no_por_orden_de_creacion(self):
        for ruta in ("z/b", "a/z", "a/b", "m/a"):
            self.caso(ruta)
        self.assertEqual(self.nombres(), ["a/b", "a/z", "m/a", "z/b"])

    def test_lee_programa_requires_y_warps_del_caso(self):
        self.caso("a/uno", programa="MOVI R3, 1\nHALT\n", requires=["mul_div"],
                  warps={"warp_size": 8, "warps": [{"id": 0}, {"id": 1}]})
        (c,) = gen.load_marked_cases(self.base)
        self.assertEqual(c.source, "MOVI R3, 1\nHALT\n")
        self.assertEqual(c.requires, ("mul_div",))
        self.assertEqual(len(c.config["warps"]), 2)

    def test_rtl_warp_config_sustituye_al_del_caso(self):
        d = self.caso("a/uno", rtl={"differential": True, "warp_config": "otra.json"})
        (d / "otra.json").write_text(json.dumps(EIGHT_WARPS), encoding="utf-8")
        (c,) = gen.load_marked_cases(self.base)
        self.assertEqual(len(c.config["warps"]), 8)

    def test_exclude_se_lee(self):
        self.caso("a/uno", rtl={"differential": True, "exclude": ["12"]})
        (c,) = gen.load_marked_cases(self.base)
        self.assertEqual(c.exclude, ("12",))

    def test_clave_desconocida_se_rechaza(self):
        self.caso("a/uno", rtl={"differential": True, "warps": "x"})
        with self.assertRaisesRegex(gen.RtlMarkError, "desconocidas"):
            gen.load_marked_cases(self.base)

    def test_exclude_debe_ser_lista_de_cadenas(self):
        self.caso("a/uno", rtl={"differential": True, "exclude": [12]})
        with self.assertRaisesRegex(gen.RtlMarkError, "exclude"):
            gen.load_marked_cases(self.base)

    def test_un_caso_de_cpu_no_puede_ser_diferencial_de_gpu(self):
        self.caso("a/uno", architecture="cpu")
        with self.assertRaisesRegex(gen.RtlMarkError, "GPU"):
            gen.load_marked_cases(self.base)

    def test_warp_size_distinto_de_8_se_rechaza_al_escribir(self):
        caso = _caso("a", config={"warp_size": 4, "warps": [{"id": 0}]})
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(ValueError, "lanes"):
            gen.write_fixtures([caso], Path(tmp) / "f")


class ListaDeCasosTest(unittest.TestCase):

    def test_los_nombres_no_se_repiten(self):
        nombres = [c.name for c in gen.all_cases()]
        self.assertEqual(len(nombres), len(set(nombres)))

    def test_el_orden_es_determinista(self):
        """Los programas con azar usan semilla fija: dos lecturas, mismo texto."""
        self.assertEqual(gen.all_cases(), gen.all_cases())

    def test_todos_los_casos_proceden_de_x_tests_en_orden(self):
        nombres = [c.name for c in gen.all_cases()]
        marcados = [c.name for c in gen.load_marked_cases()]
        self.assertEqual(nombres, marcados)
        self.assertEqual(marcados, sorted(marcados))

    def test_todos_los_casos_del_repo_se_generan(self):
        with tempfile.TemporaryDirectory() as tmp:
            n = gen.write_fixtures(gen.all_cases(), Path(tmp) / "f")
        self.assertEqual(n, len(gen.all_cases()))

    def test_ningun_caso_pide_capacidades_inexistentes(self):
        from tools.rtl_facts import load_capability_signals
        conocidas = set(load_capability_signals(ROOT))
        for caso in gen.all_cases():
            self.assertLessEqual(set(caso.requires), conocidas, caso.name)


class FormatoTest(unittest.TestCase):

    EXTENSIONES = {".asm", ".bin", ".program.hex", ".regs.hex", ".memory.hex",
                   ".config.hex", ".counts.hex", ".state.hex", ".ids.hex"}

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
                                  ("counts", 8), ("state", 8 * 3), ("memory", 512),
                                  ("ids", 8 * 2)):
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
        # Ensambla (0x7fff cabe en signed16) pero direcciona fuera de la memoria simulada.
        with self.assertRaises(AssertionError):
            self._generar([_caso("mal", source="LOAD R1, R0, 0x7fff\nHALT")])

    def test_la_configuracion_de_warps_llega_al_config_hex(self):
        config = {"warp_size": 8, "warps": [{"id": 0}, {"id": 1, "pc": 4, "active_mask": 15, "workgroup_id": 3}]}
        out, _ = self._generar([_caso("a", source="NOP\nHALT", config=config)])
        palabras = (out / "00.config.hex").read_text().split()
        self.assertEqual(palabras[3:6], ["00000004", "0000000f", "00000003"])

    def test_el_id_logico_y_el_argumento_llegan_al_ids_hex(self):
        # Un par (LOGICAL_WARP_ID, WARP_ARG) por warp, en orden de slot fisico.
        config = {"warp_size": 8, "warps": [
            {"id": 0, "logical_warp_id": 7, "arg": "0x1000"},
            {"id": 3, "logical_warp_id": 2, "arg": 0x2000}]}
        out, _ = self._generar([_caso("a", source="NOP\nHALT", config=config)])
        palabras = (out / "00.ids.hex").read_text().split()
        self.assertEqual(palabras[0:2], ["00000007", "00001000"])
        self.assertEqual(palabras[2:6], ["00000000"] * 4, "los warps sin configurar, a cero")
        self.assertEqual(palabras[6:8], ["00000002", "00002000"])


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
