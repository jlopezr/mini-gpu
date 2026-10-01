"""`tools/perf_report.py`: las cuentas del informe, sin placa ni medidas reales."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import perf_report as report  # noqa: E402


def case(instructions, cycles, clock=80_000_000, **extra):
    return dict(instructions=instructions, cycles=cycles, clock_hz=clock, **extra)


def measure(version, cases, cpi=None, created="2026-10-01T10:00:00", rtl="a"):
    return dict(version=version, label="bench", created=created, cpi=cpi,
                source_sha256={"top.v": rtl}, fmax={"achieved_mhz": 100.0}, cases=cases)


def entry(number, name, *measures):
    return (Path(f"{number}.{name}"), list(measures))


class CommonCpiTest(unittest.TestCase):

    def test_solo_cuenta_los_casos_que_todos_midieron(self):
        # `extra` lo mide solo A: si entrara, A saldria con un CPI de otro
        # conjunto y la comparacion con B no valdria.
        a = measure("a", {"x": case(100, 200), "extra": case(100, 900)})
        b = measure("b", {"x": case(100, 300)})
        cpis, common = report.common_cpi([entry(1, "a", a), entry(2, "b", b)])
        self.assertEqual(common, 1)
        self.assertEqual(cpis, [2.0, 3.0])

    def test_los_casos_de_tiempo_real_no_entran(self):
        a = measure("a", {"x": case(100, 200), "video": case(100, 900, realtime=True)})
        b = measure("b", {"x": case(100, 300), "video": case(100, 100, realtime=True)})
        cpis, common = report.common_cpi([entry(1, "a", a), entry(2, "b", b)])
        self.assertEqual((cpis, common), ([2.0, 3.0], 1))

    def test_un_caso_omitido_no_cuenta_como_medido(self):
        a = measure("a", {"x": case(100, 200), "y": {"skipped": True, "reason": "n/a"}})
        b = measure("b", {"x": case(100, 300), "y": case(100, 500)})
        _cpis, common = report.common_cpi([entry(1, "a", a), entry(2, "b", b)])
        self.assertEqual(common, 1)

    def test_un_prototipo_sin_contadores_no_vacia_los_casos_comunes(self):
        # 6, 10, 12 y 14 no miden ciclos. Con su conjunto vacio en la
        # interseccion, nadie tenia casos comunes y el CPI salia n/d a todos.
        a = measure("a", {"x": case(100, 200)})
        b = measure("b", {"x": case(100, 300)})
        sin = measure("sin", {"x": {"skipped": True, "reason": "n/a"}})
        cpis, common = report.common_cpi(
            [entry(1, "sin", sin), entry(2, "a", a), entry(3, "b", b)])
        self.assertEqual((cpis, common), ([None, 2.0, 3.0], 1))

    def test_sin_casos_comunes_no_inventa_un_cpi(self):
        a = measure("a", {"x": case(100, 200)})
        b = measure("b", {"y": case(100, 300)})
        cpis, common = report.common_cpi([entry(1, "a", a), entry(2, "b", b)])
        self.assertEqual((cpis, common), ([None, None], 0))


class FpsTest(unittest.TestCase):

    def test_fps_son_intercambios_por_segundo_de_reloj_de_placa(self):
        # 20 swaps en 80 M ciclos a 80 MHz = 1 s -> 20 FPS.
        data = case(1, 80_000_000, video={"frames": 60, "swaps": 20})
        self.assertAlmostEqual(report._fps(data), 20.0)

    def test_con_pocos_intercambios_no_hay_cifra(self):
        # Un solo swap daba 1542 FPS: el arranque pesa mas que el ritmo.
        data = case(1, 100_000, video={"frames": 1, "swaps": 1})
        self.assertIsNone(report._fps(data))
        a = measure("a", {"v": data})
        self.assertIn("corto", "\n".join(report.video_table([entry(1, "a", a)])))

    def test_un_caso_sin_video_no_tiene_fps(self):
        self.assertIsNone(report._fps(case(1, 100)))

    def test_sin_ciclos_es_el_simulador_y_no_hay_fps(self):
        data = dict(instructions=10, cycles=None, clock_hz=None,
                    video={"frames": 5, "swaps": 3})
        self.assertIsNone(report._fps(data))

    def test_el_limite_de_vsync_se_marca(self):
        a = measure("a", {"v": case(1, 80_000_000 // 60 * 10, video={"frames": 10, "swaps": 10})})
        table = "\n".join(report.video_table([entry(1, "a", a)]))
        self.assertIn("(vsync)", table)


class TablesTest(unittest.TestCase):

    def test_una_celda_distingue_omitido_de_no_medido(self):
        a = measure("a", {"x": {"skipped": True, "reason": "n/a"}})
        b = measure("b", {})
        table = "\n".join(report.per_program_table(
            [entry(1, "a", a), entry(2, "b", b)], report._cpi, "{:.2f}"))
        row = [line for line in table.splitlines() if line.startswith("| x")][0]
        self.assertIn("n/a", row)
        self.assertIn("—", row)

    def test_los_casos_de_video_llevan_asterisco(self):
        a = measure("a", {"v": case(1, 2, realtime=True)})
        table = "\n".join(report.per_program_table([entry(1, "a", a)], report._ms, "{:.3f}"))
        self.assertIn("v\\*", table)

    def test_cambios_marca_mejor_y_peor_y_ignora_lo_pequeno(self):
        before = measure("a", {"peor": case(10_000, 20_000), "mejor": case(10_000, 40_000),
                               "igual": case(10_000, 30_000)}, created="2026-09-01T10:00:00")
        now = measure("a", {"peor": case(10_000, 30_000), "mejor": case(10_000, 20_000),
                            "igual": case(10_000, 30_100)})
        table = "\n".join(report.changes_table([entry(1, "a", now, before)]))
        self.assertRegex(table, r"peor.*\+50\.0 %.*peor")
        self.assertRegex(table, r"mejor.*-50\.0 %.*mejor")
        self.assertNotIn("igual", table)

    def test_un_caso_muy_breve_no_se_juzga_como_peor(self):
        # 8 instrucciones: unos ciclos de arranque son un +30 % que no dice nada.
        before = measure("a", {"breve": case(8, 135), "largo": case(10_000, 20_000)},
                         created="2026-09-01T10:00:00")
        now = measure("a", {"breve": case(8, 176), "largo": case(10_000, 30_000)})
        table = "\n".join(report.changes_table([entry(1, "a", now, before)]))
        self.assertNotIn("breve |", table)
        self.assertIn("largo", table)
        self.assertIn("No se juzgan 1 caso(s) de menos de 1000", table)

    def test_el_historial_avisa_del_mismo_rtl(self):
        cases = {"x": case(100, 200)}
        new = measure("a", cases, cpi=2.0, rtl="same")
        old = measure("a", cases, cpi=2.0, created="2026-09-01T10:00:00", rtl="same")
        table = "\n".join(report.history_table([entry(1, "a", new, old)], 5))
        self.assertIn("mismo RTL", table)

    def test_el_historial_compara_solo_los_casos_comunes(self):
        # Antes salia -56 %: la medida vieja era un conjunto parcial con el CPI
        # alto y la nueva, completa, lo promediaba con casos baratos. Sobre el
        # caso que las dos tienen no ha cambiado nada.
        old = measure("a", {"x": case(100, 1000)}, cpi=10.0, created="2026-09-01T10:00:00")
        new = measure("a", {"x": case(100, 1000), "y": case(1000, 1000)}, cpi=1.8)
        table = "\n".join(report.history_table([entry(1, "a", new, old)], 5))
        self.assertIn("+0.0 % (1 casos", table)
        self.assertNotIn("-8", table)


if __name__ == "__main__":
    unittest.main()
