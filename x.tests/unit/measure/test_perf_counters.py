"""`tools/perf_counters.py`: leer CPU PERFORMANCE y repartir los ciclos.

Sin placa: el cliente es un diccionario de direcciones a valores, y se comprueba
lo que se lee, en que orden, y que el bloque vuelva a como estaba.
"""
import unittest

from tools import monitor_protocol
from tools.perf_counters import (STALL_COUNTERS, breakdown, difference,
                                 format_report, read_counters)

BASE = 0x8101_0000
CTRL = BASE + 0x100
OVF0 = BASE + 0x104


class ClienteFalso:
    """Un bloque de contadores en memoria, con el registro de lo que se hizo."""

    def __init__(self, registros, falla_en=None):
        self.registros = dict(registros)
        self.operaciones = []
        self.falla_en = falla_en

    def read_word(self, direccion):
        self.operaciones.append(("r", direccion))
        if direccion == self.falla_en:
            raise RuntimeError("ranura sin contador")
        return self.registros[direccion]

    def write_word(self, direccion, valor):
        self.operaciones.append(("w", direccion, valor))
        self.registros[direccion] = valor


def bloque(**cambios):
    r = {BASE + 0x00: 1000, BASE + 0x04: 125, BASE + 0x08: 120, BASE + 0x0C: 5,
         BASE + 0x10: 30, BASE + 0x14: 300, BASE + 0x18: 120, BASE + 0x1C: 50,
         CTRL: 1, OVF0: 0}
    r.update(cambios)
    return r


class DireccionesTest(unittest.TestCase):
    def test_el_protocolo_lee_de_cpu_performance_de_v2(self):
        """`PerfMixin` leia de 0x8000_0300, donde vivian en v1. En v2 ese offset
        del bloque SYSTEM da error, y `monitor.py perf` decia «The FPGA rejected
        the command» en todas las carpetas."""
        self.assertEqual(monitor_protocol.PERF_CYCLES, 0x8101_0000)
        self.assertEqual(monitor_protocol.PERF_RETIRED, 0x8101_0004)

    def test_las_ranuras_de_espera_son_las_del_contrato(self):
        self.assertEqual(STALL_COUNTERS, {
            "imem_hits": 0x08, "imem_misses": 0x0C, "mem_tx": 0x10,
            "stall_mem": 0x14, "stall_fetch": 0x18, "stall_mmio": 0x1C})


class LecturaTest(unittest.TestCase):
    def test_lee_todo_congelando_el_bloque_y_lo_deja_como_estaba(self):
        cliente = ClienteFalso(bloque())
        c = read_counters(cliente.read_word, cliente.write_word, stalls=True)
        self.assertEqual((c["cycles"], c["instructions"], c["overflow"]), (1000, 125, 0))
        self.assertEqual(c["stalls"]["stall_mem"], 300)
        escrituras = [op for op in cliente.operaciones if op[0] == "w"]
        # ENABLE a cero antes de leer (§12.5) y el valor de antes al terminar.
        self.assertEqual(escrituras, [("w", CTRL, 0), ("w", CTRL, 1)])
        self.assertEqual(cliente.operaciones[1], ("w", CTRL, 0))
        self.assertEqual(cliente.operaciones[-1], ("w", CTRL, 1))
        self.assertEqual(cliente.registros[CTRL], 1)

    def test_respeta_un_bloque_que_ya_estaba_congelado(self):
        """No se fuerza a uno: si alguien lo habia congelado, sigue congelado."""
        cliente = ClienteFalso(bloque(**{}) | {CTRL: 0})
        read_counters(cliente.read_word, cliente.write_word)
        self.assertEqual(cliente.registros[CTRL], 0)

    def test_sin_esperas_no_toca_las_ranuras_que_pueden_no_existir(self):
        cliente = ClienteFalso(bloque())
        c = read_counters(cliente.read_word, cliente.write_word)
        self.assertIsNone(c["stalls"])
        leidas = {op[1] for op in cliente.operaciones if op[0] == "r"}
        self.assertFalse(leidas & {BASE + off for off in STALL_COUNTERS.values()})

    def test_si_una_lectura_falla_el_bloque_se_descongela(self):
        """Una ranura sin contador da error de MMIO a media lectura: dejar el
        bloque congelado pararia los contadores del siguiente programa."""
        cliente = ClienteFalso(bloque(), falla_en=BASE + 0x08)
        with self.assertRaises(RuntimeError):
            read_counters(cliente.read_word, cliente.write_word, stalls=True)
        self.assertEqual(cliente.registros[CTRL], 1)

    def test_sin_write_word_solo_lee(self):
        cliente = ClienteFalso(bloque())
        read_counters(cliente.read_word)
        self.assertTrue(all(op[0] == "r" for op in cliente.operaciones))


class DiferenciaTest(unittest.TestCase):
    def test_resta_modular_aunque_un_contador_haya_dado_la_vuelta(self):
        antes = {"cycles": 0xFFFF_FF00, "instructions": 10, "overflow": 3,
                 "stalls": {"stall_mem": 0xFFFF_FFF0, "mem_tx": 1}}
        despues = {"cycles": 0x0000_00FF, "instructions": 50, "overflow": 3,
                   "stalls": {"stall_mem": 0x0000_0010, "mem_tx": 4}}
        d = difference(antes, despues)
        self.assertEqual((d["cycles"], d["instructions"]), (0x1FF, 40))
        self.assertEqual(d["stalls"], {"stall_mem": 0x20, "mem_tx": 3})
        # La diferencia SI es de fiar aunque las dos lecturas no lo fueran.
        self.assertEqual(d["overflow"], 0)

    def test_sin_esperas_en_alguna_de_las_dos_no_las_inventa(self):
        a = {"cycles": 1, "instructions": 1, "overflow": 0, "stalls": None}
        b = {"cycles": 5, "instructions": 3, "overflow": 0, "stalls": {"mem_tx": 1}}
        self.assertIsNone(difference(a, b)["stalls"])


class ReparteTest(unittest.TestCase):
    ESPERAS = {"imem_hits": 120, "imem_misses": 5, "mem_tx": 30,
               "stall_mem": 300, "stall_fetch": 120, "stall_mmio": 50}

    def test_reparto_suma_uno(self):
        r = breakdown(1000, 125, self.ESPERAS)
        self.assertAlmostEqual(r["compute"], 0.65)
        self.assertAlmostEqual(r["fetch"], 0.12)
        self.assertAlmostEqual(r["data"], 0.18)
        self.assertAlmostEqual(r["mmio"], 0.05)
        self.assertAlmostEqual(r["compute"] + r["fetch"] + r["data"] + r["mmio"], 1.0)
        self.assertAlmostEqual(r["hit_rate"], 120 / 125)
        self.assertAlmostEqual(r["tx_per_instruction"], 0.24)

    def test_sin_datos_no_hay_reparto(self):
        self.assertIsNone(breakdown(0, 0, self.ESPERAS))
        self.assertIsNone(breakdown(100, 10, None))

    def test_no_divide_por_cero_y_el_calculo_no_es_negativo(self):
        r = breakdown(100, 0, dict(self.ESPERAS, imem_hits=0, imem_misses=0,
                                   stall_mem=101, stall_fetch=101, stall_mmio=0))
        self.assertIsNone(r["hit_rate"])
        self.assertIsNone(r["tx_per_instruction"])
        self.assertEqual(r["compute"], 0)


class InformeTest(unittest.TestCase):
    def test_informe_con_esperas(self):
        c = {"cycles": 1000, "instructions": 125, "overflow": 0, "stalls": ReparteTest.ESPERAS}
        texto = "\n".join(format_report(c))
        self.assertIn("CPI=8.00 IPC=0.125", texto)
        self.assertIn("calculo 65.0 %, busqueda 12.0 %, datos 18.0 %, MMIO 5.0 %", texto)
        self.assertIn("120 aciertos, 5 fallos (96.0 % de acierto)", texto)
        self.assertNotIn("AVISO", texto)
        self.assertNotIn("no fiable", texto)

    def test_con_desbordamiento_marca_las_cifras_y_dice_como_medir(self):
        c = {"cycles": 65_978_919, "instructions": 1_578_598_955, "overflow": 3, "stalls": None}
        texto = "\n".join(format_report(c))
        self.assertIn("[no fiable: un contador dio la vuelta]", texto)
        self.assertIn("PERF_OVF0=0x3", texto)
        self.assertIn("perf <segundos>", texto)

    def test_cero_instrucciones_no_divide(self):
        c = {"cycles": 40, "instructions": 0, "overflow": 0, "stalls": None}
        self.assertIn("CPI: sin datos", format_report(c)[0])

    def test_sin_esperas_solo_ciclos_e_instrucciones(self):
        c = {"cycles": 800, "instructions": 100, "overflow": 0, "stalls": None}
        self.assertEqual(len(format_report(c)), 1)


if __name__ == "__main__":
    unittest.main()
