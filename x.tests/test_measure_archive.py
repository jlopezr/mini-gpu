"""Archivo de medidas (`tools/measure_archive.py`): sin placa ni build reales.

Lo que se comprueba:

  - que el Fmax sale del build hecho con las fuentes ACTUALES y de ningun otro,
    porque con otro RTL seria el Fmax de otra cosa;
  - que el reloj que se toma es el de menos margen y no el de vídeo;
  - que el CPI global deja fuera los casos de tiempo real;
  - y que `compare` junta CPI y Fmax en ns por instruccion, que es donde se ve
    si un CPI peor compensa una frecuencia mayor.
"""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.measure_archive import (
    archive_measurement, compare_measures, limiting_clock, load_measure,
    matching_build, newest_measures, ns_per_instruction, pooled_cpi,
)


def prototipo(directorio: Path, fuente="module top; endmodule\n"):
    directorio.mkdir(parents=True, exist_ok=True)
    (directorio / "top.v").write_text(fuente, encoding="utf-8")
    (directorio / "apio.ini").write_text("[env:default]\n", encoding="utf-8")
    return directorio


def build(directorio: Path, nombre, clocks, exit_code=0, fuentes=None):
    """Un build archivado con el hash de `fuentes` (las actuales si no se dice)."""
    carpeta = directorio / "reports" / nombre
    carpeta.mkdir(parents=True)
    fuentes = fuentes if fuentes is not None else {
        name: hashlib.sha256((directorio / name).read_bytes()).hexdigest()
        for name in ("top.v", "apio.ini")}
    (carpeta / "metadata.json").write_text(
        json.dumps({"exit_code": exit_code, "source_sha256": fuentes}), encoding="utf-8")
    (carpeta / "summary.json").write_text(json.dumps({"clocks": clocks}), encoding="utf-8")
    return carpeta


RELOJES = {
    "$glbnet$clk_pix": {"achieved": 57.7, "constraint": 25.0},
    "$glbnet$sdram_clk": {"achieved": 81.29, "constraint": 80.0},
}
MEDIDAS = {
    "a": {"instructions": 100, "cycles": 1000},
    "b": {"instructions": 100, "cycles": 800},
    "video": {"instructions": 1000, "cycles": 90000},
    "malo": {"skipped": True, "reason": "x"},
}


class Fmax(unittest.TestCase):
    def test_el_reloj_limite_es_el_de_menos_margen(self):
        nombre, alcanzado, exigido = limiting_clock(RELOJES)
        self.assertEqual((nombre, alcanzado, exigido), ("$glbnet$sdram_clk", 81.29, 80.0))

    def test_sin_relojes_no_hay_limite(self):
        self.assertIsNone(limiting_clock({}))
        self.assertIsNone(limiting_clock(None))

    def test_un_build_de_otras_fuentes_no_vale(self):
        with tempfile.TemporaryDirectory() as tmp:
            directorio = prototipo(Path(tmp) / "30.x")
            build(directorio, "20260101-000000-000000-viejo", RELOJES,
                  fuentes={"top.v": "0" * 64, "apio.ini": "0" * 64})
            self.assertIsNone(matching_build(directorio))

    def test_un_build_fallido_no_vale(self):
        with tempfile.TemporaryDirectory() as tmp:
            directorio = prototipo(Path(tmp) / "30.x")
            build(directorio, "20260101-000000-000000-roto", RELOJES, exit_code=1)
            self.assertIsNone(matching_build(directorio))

    def test_se_toma_el_mas_reciente_que_coincide(self):
        with tempfile.TemporaryDirectory() as tmp:
            directorio = prototipo(Path(tmp) / "30.x")
            build(directorio, "20260101-000000-000000-a", {"c": {"achieved": 70.0, "constraint": 80.0}})
            build(directorio, "20260102-000000-000000-b", RELOJES)
            carpeta, _ = matching_build(directorio)
            self.assertTrue(carpeta.name.endswith("-b"))


class Archivo(unittest.TestCase):
    def test_guarda_la_medida_con_el_fmax_del_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            directorio = prototipo(Path(tmp) / "30.x")
            build(directorio, "20260101-000000-000000-ok", RELOJES)
            carpeta = archive_measurement(directorio, "console", MEDIDAS, "| tabla |\n",
                                          "antes", realtime={"video"})
            documento = load_measure(carpeta)
            self.assertEqual(documento["fmax"]["achieved_mhz"], 81.29)
            self.assertEqual(documento["label"], "antes")
            self.assertTrue(documento["cases"]["video"]["realtime"])
            self.assertEqual((carpeta / "measure.md").read_text(encoding="utf-8"), "| tabla |\n")

    def test_sin_build_de_estas_fuentes_el_fmax_es_nulo(self):
        with tempfile.TemporaryDirectory() as tmp:
            directorio = prototipo(Path(tmp) / "30.x")
            carpeta = archive_measurement(directorio, "console", MEDIDAS, "t\n", "antes")
            self.assertIsNone(load_measure(carpeta)["fmax"])

    def test_la_etiqueta_se_limpia_para_el_nombre_de_carpeta(self):
        with tempfile.TemporaryDirectory() as tmp:
            directorio = prototipo(Path(tmp) / "30.x")
            carpeta = archive_measurement(directorio, "console", MEDIDAS, "t\n", "a b/c")
            self.assertTrue(carpeta.name.endswith("-medida-a_b_c"))

    def test_las_mas_recientes_van_de_nueva_a_vieja(self):
        with tempfile.TemporaryDirectory() as tmp:
            directorio = prototipo(Path(tmp) / "30.x")
            for etiqueta in ("uno", "dos", "tres"):
                archive_measurement(directorio, "console", MEDIDAS, "t\n", etiqueta)
            nombres = [p.parent.name for p in newest_measures(directorio)]
            self.assertEqual(len(nombres), 2)
            self.assertTrue(nombres[0].endswith("-tres"))
            self.assertTrue(nombres[1].endswith("-dos"))


class Cpi(unittest.TestCase):
    def test_el_cpi_global_deja_fuera_tiempo_real_y_omitidos(self):
        cases = {name: dict(data, realtime=name == "video") for name, data in MEDIDAS.items()}
        # (1000 + 800) ciclos entre (100 + 100) instrucciones
        self.assertAlmostEqual(pooled_cpi(cases), 9.0)

    def test_sin_casos_no_hay_cpi(self):
        self.assertIsNone(pooled_cpi({}))

    def test_ns_por_instruccion_es_cpi_entre_fmax(self):
        self.assertAlmostEqual(ns_per_instruction(8.0, {"achieved_mhz": 80.0}), 100.0)
        self.assertIsNone(ns_per_instruction(8.0, None))
        self.assertIsNone(ns_per_instruction(None, {"achieved_mhz": 80.0}))


def documento(label, cpi, mhz, cases, fuentes="a"):
    return {"label": label, "created": "2026-09-29T10:00:00", "cpi": cpi,
            "fmax": None if mhz is None else {"achieved_mhz": mhz},
            "source_sha256": {"top.v": fuentes}, "cases": cases}


class Comparacion(unittest.TestCase):
    def test_un_cpi_peor_con_mucho_mas_fmax_sale_ganando(self):
        antes = documento("antes", 8.2, 81.0, {"a": {"instructions": 10, "cycles": 82}})
        despues = documento("despues", 8.6, 100.0, {"a": {"instructions": 10, "cycles": 86}}, "b")
        texto = compare_measures(antes, despues)
        # 8,2/81 = 101,2 ns; 8,6/100 = 86,0 ns: un 15 % menos
        self.assertIn("101.23 ns/instr", texto)
        self.assertIn("86.00 ns/instr", texto)
        self.assertIn("CPI +4.9 %", texto)
        self.assertIn("ns/instr -15.0 %", texto)
        self.assertIn("| a | 8.20 | 8.60 | +4.9 % |", texto)

    def test_sin_fmax_lo_dice_en_vez_de_inventarlo(self):
        antes = documento("antes", 8.0, None, {})
        despues = documento("despues", 8.0, 80.0, {}, "b")
        texto = compare_measures(antes, despues)
        self.assertIn("Fmax n/d, n/d ns/instr", texto)
        self.assertIn("ns/instr n/d", texto)

    def test_mismo_rtl_avisa(self):
        texto = compare_measures(documento("x", 8.0, 80.0, {}), documento("y", 8.0, 80.0, {}))
        self.assertIn("mismo RTL", texto)

    def test_los_casos_de_tiempo_real_no_salen_en_la_tabla(self):
        caso = {"instructions": 10, "cycles": 100, "realtime": True}
        texto = compare_measures(documento("x", 8.0, 80.0, {"video": caso}),
                                 documento("y", 8.0, 80.0, {"video": caso}, "b"))
        self.assertNotIn("| video |", texto)


if __name__ == "__main__":
    unittest.main()
