"""`tools/perf_counters.py`: leer CPU PERFORMANCE y repartir los ciclos.

Sin placa: el cliente es un diccionario de direcciones a valores, y se comprueba
lo que se lee, en que orden, y que el bloque vuelva a como estaba.
"""
import unittest

from tools import monitor_protocol
from tools.perf_counters import (DCACHE_COUNTERS, MULDIV_COUNTERS, PIPELINE_COUNTERS,
                                 STALL_COUNTERS, VIDEO_COUNTERS, breakdown,
                                 dcache_breakdown, muldiv_breakdown, video_breakdown,
                                 difference, format_report, pipeline_breakdown,
                                 read_counters)

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



class PipelineTest(unittest.TestCase):
    """Ranuras 8 a 11 de la CPU segmentada (capacidad `perf_pipeline`)."""

    def test_las_ranuras_son_las_del_contrato(self):
        self.assertEqual(PIPELINE_COUNTERS, {
            "stall_ex_mem": 0x20, "stall_raw": 0x24, "stall_branch": 0x28,
            "stall_id_empty": 0x2C})

    def test_solo_las_lee_si_se_piden(self):
        pipeline = {BASE + 0x20: 100, BASE + 0x24: 250, BASE + 0x28: 75, BASE + 0x2C: 25}
        cliente = ClienteFalso(bloque() | pipeline)
        c = read_counters(cliente.read_word, cliente.write_word, stalls=True)
        self.assertNotIn("stall_raw", c["stalls"])
        c = read_counters(cliente.read_word, cliente.write_word, stalls=True, pipeline=True)
        self.assertEqual(c["stalls"]["stall_raw"], 250)

    def test_reparto_por_instruccion_y_otros_es_lo_que_falta(self):
        # 1000 ciclos, 125 instrucciones: 125 + 100 + 250 + 75 + 25 = 575 contados.
        stalls = {"stall_ex_mem": 100, "stall_raw": 250, "stall_branch": 75,
                  "stall_id_empty": 25}
        p = pipeline_breakdown(1000, 125, stalls)
        self.assertEqual((p["ex_mem"], p["raw"], p["branch"], p["id_empty"]),
                         (0.8, 2.0, 0.6, 0.2))
        self.assertAlmostEqual(p["other"], 3.4)
        self.assertAlmostEqual(1 + sum(p.values()), 1000 / 125)

    def test_sin_ranuras_del_pipeline_no_hay_reparto(self):
        self.assertIsNone(pipeline_breakdown(1000, 125, {"stall_mem": 3}))
        self.assertIsNone(pipeline_breakdown(1000, 0, {"stall_raw": 3}))

    def test_el_informe_lo_enseña(self):
        c = {"cycles": 1000, "instructions": 125, "overflow": 0,
             "stalls": {"imem_hits": 120, "imem_misses": 5, "mem_tx": 30,
                        "stall_mem": 300, "stall_fetch": 120, "stall_mmio": 50,
                        "stall_ex_mem": 100, "stall_raw": 250, "stall_branch": 75,
                        "stall_id_empty": 25}}
        self.assertIn("dependencia 2.00", "\n".join(format_report(c)))



class DcacheTest(unittest.TestCase):
    """Ranuras 12 y 13 de la cache de datos (capacidad `perf_dcache`)."""

    def test_las_ranuras_son_las_del_contrato(self):
        self.assertEqual(DCACHE_COUNTERS, {"dmem_hits": 0x30, "dmem_misses": 0x34})

    def test_solo_las_lee_si_se_piden(self):
        cliente = ClienteFalso(bloque() | {BASE + 0x30: 90, BASE + 0x34: 10})
        c = read_counters(cliente.read_word, cliente.write_word, stalls=True)
        self.assertNotIn("dmem_hits", c["stalls"])
        c = read_counters(cliente.read_word, cliente.write_word, stalls=True, dcache=True)
        self.assertEqual((c["stalls"]["dmem_hits"], c["stalls"]["dmem_misses"]), (90, 10))

    def test_tasa_de_aciertos_y_fallos_por_instruccion(self):
        d = dcache_breakdown(200, {"dmem_hits": 90, "dmem_misses": 10})
        self.assertEqual((d["hits"], d["misses"]), (90, 10))
        self.assertAlmostEqual(d["hit_rate"], 0.9)
        self.assertAlmostEqual(d["misses_per_instruction"], 0.05)

    def test_sin_loads_no_hay_tasa_y_sin_ranuras_no_hay_nada(self):
        self.assertIsNone(dcache_breakdown(200, {"dmem_hits": 0, "dmem_misses": 0})["hit_rate"])
        self.assertIsNone(dcache_breakdown(200, {"stall_raw": 3}))
        self.assertIsNone(dcache_breakdown(200, None))


class MuldivTest(unittest.TestCase):
    """Ranuras 14 y 15 de MUL/DIV (capacidad `perf_muldiv`)."""

    def test_las_ranuras_son_las_del_contrato(self):
        self.assertEqual(MULDIV_COUNTERS, {"stall_muldiv": 0x38, "muldiv_retired": 0x3C})

    def test_solo_las_lee_si_se_piden(self):
        cliente = ClienteFalso(bloque() | {BASE + 0x38: 370, BASE + 0x3C: 20})
        c = read_counters(cliente.read_word, cliente.write_word, stalls=True)
        self.assertNotIn("stall_muldiv", c["stalls"])
        c = read_counters(cliente.read_word, cliente.write_word, stalls=True, muldiv=True)
        self.assertEqual((c["stalls"]["stall_muldiv"], c["stalls"]["muldiv_retired"]),
                         (370, 20))

    def test_es_un_motivo_mas_del_reparto(self):
        stalls = {"stall_ex_mem": 0, "stall_raw": 20, "stall_branch": 30,
                  "stall_id_empty": 5, "stall_muldiv": 370}
        p = pipeline_breakdown(100 + 20 + 30 + 5 + 370 + 7, 100, stalls)
        self.assertAlmostEqual(p["muldiv"], 3.7)
        self.assertAlmostEqual(p["other"], 0.07)
        self.assertNotIn("muldiv", pipeline_breakdown(
            200, 100, {k: 0 for k in PIPELINE_COUNTERS}))

    def test_espera_media_y_parte_de_las_instrucciones(self):
        m = muldiv_breakdown(200, {"stall_muldiv": 370, "muldiv_retired": 20})
        self.assertEqual((m["retired"], m["stall"]), (20, 370))
        self.assertAlmostEqual(m["fraction"], 0.1)
        self.assertAlmostEqual(m["cycles_per_op"], 18.5)
        self.assertIsNone(muldiv_breakdown(200, {"stall_muldiv": 0,
                                                 "muldiv_retired": 0})["cycles_per_op"])
        self.assertIsNone(muldiv_breakdown(200, {"stall_raw": 3}))


class VideoTest(unittest.TestCase):
    """Ranuras 16 y 17 de video (capacidad `perf_video`)."""

    def test_las_ranuras_son_las_del_contrato(self):
        self.assertEqual(VIDEO_COUNTERS, {"video_frames": 0x40, "swap_wait": 0x44})

    def test_solo_las_lee_si_se_piden(self):
        cliente = ClienteFalso(bloque() | {BASE + 0x40: 4, BASE + 0x44: 300})
        c = read_counters(cliente.read_word, cliente.write_word, stalls=True)
        self.assertNotIn("video_frames", c["stalls"])
        c = read_counters(cliente.read_word, cliente.write_word, stalls=True, video=True)
        self.assertEqual((c["stalls"]["video_frames"], c["stalls"]["swap_wait"]), (4, 300))

    def test_frame_ocupado(self):
        """1000 ciclos en 4 frames (250 cada uno); 300 esperando y 2 swaps: 350
        de trabajo por swap, el 140 % de un frame."""
        v = video_breakdown(1000, 2, {"video_frames": 4, "swap_wait": 300})
        self.assertAlmostEqual(v["cycles_per_frame"], 250)
        self.assertAlmostEqual(v["work_per_swap"], 350)
        self.assertAlmostEqual(v["occupancy"], 1.4)

    def test_sin_divisores_no_divide_y_sin_ranuras_no_hay_nada(self):
        v = video_breakdown(1000, 0, {"video_frames": 0, "swap_wait": 0})
        self.assertEqual((v["cycles_per_frame"], v["work_per_swap"], v["occupancy"]),
                         (None, None, None))
        self.assertIsNone(video_breakdown(1000, 2, {"stall_raw": 3}))
        self.assertIsNone(video_breakdown(1000, 2, None))

    def test_el_informe_lo_enseña(self):
        lineas = format_report({"cycles": 1000, "instructions": 100, "overflow": 0,
                                "stalls": {k: 0 for k in STALL_COUNTERS}
                                | {"video_frames": 4, "swap_wait": 300}})
        self.assertIn("video: 4 frames con la CPU en marcha (250 ciclos cada uno), "
                      "30.0 % de los ciclos esperando un swap", "\n".join(lineas))


if __name__ == "__main__":
    unittest.main()
