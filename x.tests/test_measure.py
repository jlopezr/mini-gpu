"""Pruebas de la tabla de medidas.

`measurement_table` es funcion pura, asi que se puede probar entera sin placa
y sin simulador. Es justo la parte que mas se mira --la tabla que uno lee para
decidir si una version merece la pena-- y la que mas facil es que mienta en
silencio: una celda vacia y un CPI de 0,00 se parecen mucho en un Markdown.

Lo que se comprueba:

  - que un caso omitido en una version sale como `n/a` y no como un hueco;
  - que un bitstream sin contadores lo dice, en vez de fingir un CPI;
  - que las instrucciones se comparten entre versiones cuando coinciden, que
    es lo que hace la tabla legible;
  - y que cuando NO coinciden la tabla grita, porque eso no es una medida
    lenta: es una CPU ejecutando cosas distintas.
"""

import unittest

from run_tests import measurement_table


def medida(instructions=None, cycles=None, clock_hz=None):
    return {"instructions": instructions, "cycles": cycles, "clock_hz": clock_hz}


class MeasurementTableTest(unittest.TestCase):

    def test_cpi_y_tiempo(self):
        tabla = measurement_table(
            {("smoke", "bl8"): medida(100, 3520, 80_000_000)},
            ["smoke"], ["bl8"])
        # 3520 / 100 = 35,20 ciclos por instruccion.
        self.assertIn("| smoke | 100 | 35.20 |", tabla)
        # 3520 ciclos a 80 MHz son 0,044 ms.
        self.assertIn("| smoke | 0.044 |", tabla)

    def test_omitido_y_sin_contadores(self):
        tabla = measurement_table(
            {
                ("video", "ebr"): {"skipped": True, "reason": "no tiene video"},
                ("video", "bl8"): medida(10, 90, 80_000_000),
                ("video", "sim"): medida(10),
            },
            ["video"], ["ebr", "bl8", "sim"])
        fila = [l for l in tabla.splitlines() if l.startswith("| video |")][0]
        self.assertIn("n/a", fila)
        self.assertIn("9.00", fila)
        self.assertIn("sin contadores", fila)

    def test_cero_instrucciones_no_es_sin_contadores(self):
        """Una trampa que para sin retirar instrucciones SI tiene contador
        (perf_counters=True): el CPI esta indefinido (n/d), no ausente."""
        tabla = measurement_table(
            {("explicit-trap", "bl8"): medida(0, 0, 80_000_000)},
            ["explicit-trap"], ["bl8"])
        fila = [l for l in tabla.splitlines()
               if l.startswith("| explicit-trap |")][0]
        self.assertIn("n/d", fila)
        self.assertNotIn("sin contadores", fila)

    def test_instrucciones_compartidas(self):
        """Coinciden, asi que hay UNA columna y no una por version."""
        tabla = measurement_table(
            {
                ("p", "bl8"): medida(1234, 5000, 80_000_000),
                ("p", "sim"): medida(1234),
            },
            ["p"], ["bl8", "sim"])
        self.assertIn("1 234", tabla)
        self.assertNotIn("discrepan", tabla)

    def test_discrepancia_de_instrucciones(self):
        """Si no coinciden, la tabla lo dice en la celda Y en un aviso.

        Sin este aviso, la tabla elegiria un numero cualquiera y presentaria
        dos CPI calculados sobre programas distintos como si fueran
        comparables.
        """
        tabla = measurement_table(
            {
                ("p", "bl8"): medida(1000, 5000, 80_000_000),
                ("p", "sim"): medida(1001),
            },
            ["p"], ["bl8", "sim"])
        self.assertIn("¡discrepan!", tabla)
        self.assertIn("Aviso", tabla)
        self.assertIn("[1000, 1001]", tabla)

    def test_discrepancia_de_video_no_dispara_el_aviso_de_cpu(self):
        """video-band espera un swap real (vsync): varia por diseno entre
        versiones con reloj distinto, no es una CPU haciendo algo distinto."""
        tabla = measurement_table(
            {
                ("video-band", "hdmi"): medida(1077191, 90, 100_000_000),
                ("video-band", "bl8"): medida(1137814, 90, 80_000_000),
            },
            ["video-band"], ["hdmi", "bl8"],
            video_realtime=frozenset({"video-band"}))
        self.assertIn("¡varía! *1", tabla)
        self.assertNotIn("¡discrepan!", tabla)
        self.assertNotIn("Aviso", tabla)
        self.assertIn("*1:", tabla)

    def test_discrepancia_de_serie_no_dispara_el_aviso_de_cpu(self):
        """serial-forth espera bytes reales por UART: varia por diseno entre
        versiones con baudrate distinto, no es una CPU haciendo algo distinto."""
        tabla = measurement_table(
            {
                ("serial-forth", "subword"): medida(307488, 90, 80_000_000),
                ("serial-forth", "alu"): medida(318160, 90, 80_000_000),
            },
            ["serial-forth"], ["subword", "alu"],
            serial_realtime=frozenset({"serial-forth"}))
        self.assertIn("¡varía! *2", tabla)
        self.assertNotIn("¡discrepan!", tabla)
        self.assertNotIn("Aviso", tabla)
        self.assertIn("*2:", tabla)

    def test_cero_instrucciones_no_es_un_hueco(self):
        """Un programa que trampea en la primera instruccion ejecuto cero.

        Es una medida, no una ausencia: si se filtrara por verdad logica en
        vez de por `is not None`, la tabla diria `—` y pareceria que no se
        pudo medir.
        """
        tabla = measurement_table(
            {("trap", "bl8"): medida(0, 12, 80_000_000)}, ["trap"], ["bl8"])
        self.assertIn("| trap | 0 |", tabla)
        # Y no se divide por cero al pedir el CPI.
        self.assertIn("sin contadores", tabla)

    def test_caso_sin_ninguna_medida(self):
        tabla = measurement_table({}, ["p"], ["bl8"])
        self.assertIn("| p | — | — |", tabla)

    def test_las_dos_tablas_estan(self):
        tabla = measurement_table(
            {("p", "bl8"): medida(10, 20, 80_000_000)}, ["p"], ["bl8"])
        self.assertIn("## Ciclos por instruccion", tabla)
        self.assertIn("## Tiempo de CPU (ms)", tabla)
        # Y las cabeceras llevan la version como columna.
        self.assertEqual(tabla.count("| bl8 |"), 2)


if __name__ == "__main__":
    unittest.main()
