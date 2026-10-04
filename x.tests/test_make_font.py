"""Generador de fuentes de la consola (`30.fpga-cpu-console/make_font.py`).

Lo que se comprueba, sobre las fuentes que se entregan y sobre el generador de
cajas finas:

  - que cada caracter de caja CP437 (0xB3-0xDA) toca el borde de la celda por
    los brazos que tiene y solo por esos: sin eso, las cajas no se unen entre
    celdas vecinas y se ven huecos;
  - que las cuatro uniones delicadas de las cajas finas (esquinas dobles,
    cruces con hueco) tienen la forma esperada;
  - que ningun codigo CP437 con glifo queda en blanco por error.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "30.fpga-cpu-console" / "fonts"
sys.path.insert(0, str(ROOT / "30.fpga-cpu-console"))

import make_font  # noqa: E402

FONT_NAMES = ("pc", "cpc464", "tamzen")


def load(name):
    words = [int(x, 16) for x in (FONTS / f"font8x16_{name}.hex").read_text().split()]
    return [[(word >> (8 * y)) & 0xFF for y in range(16)] for word in words]


def edges(rows):
    return (rows[0] != 0, rows[15] != 0,
            any(r & 0x80 for r in rows), any(r & 0x01 for r in rows))


class BoxEdgesTest(unittest.TestCase):
    def test_los_brazos_tocan_el_borde_y_solo_ellos(self):
        for name in FONT_NAMES:
            font = load(name)
            for code, arms in make_font.THIN_BOX.items():
                with self.subTest(font=name, code=f"{code:#04x}"):
                    self.assertEqual(edges(font[code]), tuple(bool(a) for a in arms))

    def test_generador_cumple_lo_mismo(self):
        for code, arms in make_font.THIN_BOX.items():
            with self.subTest(code=f"{code:#04x}"):
                self.assertEqual(edges(make_font.thin_box(*arms)), tuple(bool(a) for a in arms))


class ThinShapesTest(unittest.TestCase):
    @staticmethod
    def pixel(rows, x, y):
        return bool(rows[y] & (0x80 >> x))

    def test_cruce_simple_es_continuo(self):
        rows = make_font.thin_box(1, 1, 1, 1)
        self.assertTrue(all(self.pixel(rows, 4, y) for y in range(16)))
        self.assertTrue(all(self.pixel(rows, x, 7) for x in range(8)))
        self.assertEqual(sum(bin(r).count("1") for r in rows), 16 + 7)

    def test_cruce_doble_deja_el_centro_abierto(self):
        rows = make_font.thin_box(2, 2, 2, 2)
        for x in (3, 5):  # carriles verticales, cortados entre las dos horizontales
            self.assertFalse(self.pixel(rows, x, 7))
            self.assertTrue(self.pixel(rows, x, 6) and self.pixel(rows, x, 8))
        for y in (6, 8):  # lineas horizontales, cortadas entre los dos carriles
            self.assertFalse(self.pixel(rows, 4, y))
        self.assertFalse(self.pixel(rows, 4, 7))

    def test_esquina_doble_exterior_e_interior(self):
        rows = make_font.thin_box(2, 0, 0, 2)  # ╚
        self.assertTrue(self.pixel(rows, 3, 8) and self.pixel(rows, 7, 8))  # exterior
        self.assertTrue(self.pixel(rows, 5, 6) and self.pixel(rows, 7, 6))  # interior
        self.assertFalse(self.pixel(rows, 4, 6))
        self.assertFalse(self.pixel(rows, 3, 9) or self.pixel(rows, 5, 7))

    def test_simple_entra_entre_las_dos_dobles(self):
        rows = make_font.thin_box(1, 0, 0, 2)  # ╘
        self.assertTrue(all(self.pixel(rows, 4, y) for y in range(9)))
        self.assertTrue(all(self.pixel(rows, x, 6) and self.pixel(rows, x, 8) for x in range(4, 8)))
        self.assertFalse(self.pixel(rows, 5, 7))


class FontContentTest(unittest.TestCase):
    def test_solo_los_blancos_esperados(self):
        for name in FONT_NAMES:
            font = load(name)
            blank = {code for code in range(256) if not any(font[code])}
            with self.subTest(font=name):
                self.assertEqual(blank, {0x00, 0x20, 0xFF})

    def test_256_glifos(self):
        for name in FONT_NAMES:
            self.assertEqual(len(load(name)), 256)


if __name__ == "__main__":
    unittest.main()
