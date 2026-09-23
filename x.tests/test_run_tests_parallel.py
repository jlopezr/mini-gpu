"""El reparto de casos entre procesos, y las cuatro cosas que lo limitan.

Paralelizar los casos de simulador baja `gpusim` de 184,8 s a 96,2 s.
El techo es bajo y conviene saberlo: dos casos --`gpu-mandelbrot` y
`gpu-mandelbrot-packed`, 89 y 95 s-- son el 99,9 % del tiempo, así que ningún
reparto baja del más lento. Es un 1,9x, no un 24x.

Lo que estos tests fijan no es la velocidad sino las condiciones en las que NO
se reparte, que es donde están los fallos que costaría caro descubrir en
caliente:

- Con `--jobs 1` no hay pool. No es un pool de tamaño uno: cuando un caso se
  cuelga o hay que depurarlo, el pool estorba y hace falta una ruta que no lo
  monte.
- Con trazas tampoco, porque varios procesos escribiendo la misma traza la
  entrelazarían y no sería la traza de nada.
- Sin backends de simulador --sólo placa-- tampoco: hay una sola placa.
- Y con un solo caso no compensa montar procesos.

La placa además no comparte máquina con los workers: el reparto TERMINA antes
de que se toque el puerto serie. Sus timeouts son de reloj de pared, así que
con la máquina saturada una lectura podría agotarlos por contienda y no por un
fallo real. Se pierde el solape y se gana que un rojo en placa signifique lo
que dice.
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run_tests  # noqa: E402


def opciones(**cambios):
    base = dict(trace=False, trace_detail=False, trace_limit=None,
                trace_file=None, jobs=0)
    base.update(cambios)
    return SimpleNamespace(**base)


class ResolveJobsTest(unittest.TestCase):
    def test_jobs_uno_no_monta_pool(self):
        self.assertEqual(
            run_tests.resolve_jobs(1, simuladores=1, casos=50, args=opciones()), 1)

    def test_sin_simuladores_no_se_reparte(self):
        """Sólo placa: hay una, y va en serie."""
        self.assertEqual(
            run_tests.resolve_jobs(0, simuladores=0, casos=50, args=opciones()), 1)

    def test_un_solo_caso_no_compensa(self):
        self.assertEqual(
            run_tests.resolve_jobs(0, simuladores=1, casos=1, args=opciones()), 1)

    def test_las_trazas_fuerzan_secuencial(self):
        """Varios procesos escribiendo la misma traza la entrelazan."""
        for cambio in ({"trace": True}, {"trace_detail": True},
                       {"trace_file": Path("t.log")}):
            with self.subTest(**cambio):
                self.assertEqual(
                    run_tests.resolve_jobs(0, simuladores=1, casos=50,
                                           args=opciones(**cambio)), 1)

    def test_automatico_no_pide_mas_procesos_que_casos(self):
        """Con cuatro casos no tiene sentido arrancar veinticuatro procesos."""
        self.assertLessEqual(
            run_tests.resolve_jobs(0, simuladores=1, casos=4, args=opciones()), 4)

    def test_un_numero_explicito_se_respeta(self):
        self.assertEqual(
            run_tests.resolve_jobs(6, simuladores=1, casos=50, args=opciones()), 6)


class NombresDeBackendTest(unittest.TestCase):
    """Los nombres se declaran, no se deducen del sufijo.

    Los backends de simulador se llamaban `cpu-simulator` y `gpu-simulator`, y
    había código que los reconocía por terminar en «simulator». Al renombrarlos
    a `cpusim`/`gpusim` --para que coincidan con `tools/cpusim` y
    `tools/gpusim`, que ya existían-- ese código dejó de encontrarlos **sin
    decir nada**: el reparto en procesos se apagó, y un backend que no se
    construye no ejecuta nada y la suite informa «N caso(s), 0 fallo(s)».

    Un verde que no ha probado nada es peor que un rojo, así que esto fija que
    el conjunto declarado y las definiciones no se separen.
    """

    def test_todo_simulador_declarado_existe_como_backend(self):
        self.assertTrue(
            run_tests.SIMULADORES <= set(run_tests.BACKEND_DEFINITIONS))

    def test_los_tres_simuladores_estan(self):
        """Los mismos tres que tienen lanzador en tools/."""
        self.assertEqual(run_tests.SIMULADORES,
                         {"cpusim", "gpusim", "gpusim-cycle"})
        for nombre in ("cpusim", "gpusim", "gpusim-cycle"):
            with self.subTest(backend=nombre):
                self.assertTrue((ROOT.parent / "tools" / nombre).exists(),
                                f"tools/{nombre} no existe")

    def test_ningun_backend_se_queda_sin_construir(self):
        """El fallo concreto: `gpusim-cycle` se añadió a las definiciones y su
        `if` de construcción se olvidó, así que corría con cero backends."""
        for nombre in run_tests.SIMULADORES:
            with self.subTest(backend=nombre):
                definicion = run_tests.BACKEND_DEFINITIONS[nombre]
                self.assertIn(definicion["default_version"],
                              definicion["versions"],
                              f"{nombre}: su versión por defecto no existe")

    def test_el_modelo_de_ciclos_es_un_backend_y_no_una_version(self):
        ciclos = run_tests.BACKEND_DEFINITIONS["gpusim-cycle"]
        self.assertEqual(ciclos["default_version"], "cycle")
        self.assertIn("gpusim-cycle", run_tests.SIMULADORES_GPU)


class BackendArgumentsTest(unittest.TestCase):
    """Una sola lista de argumentos para los dos caminos.

    Estaba embebida en el bucle principal. Si el camino de los procesos tuviera
    su propia copia, un backend podría recibir cosas distintas según cómo se
    lanzara -- y eso se vería como un caso que pasa en secuencial y falla en
    paralelo, o al revés.
    """

    def caso(self, **cambios):
        base = {
            "name": "x", "program": b"", "initial_memory": [],
            "expected": {"registers": {}, "memory": [], "observations": {},
                         "video": None, "frame": None},
            "max_instructions": 10, "timeout_seconds": 1.0,
            "architecture": "cpu", "stdin": b"", "warp_config": None,
            "run_until": None, "simulator_options": {},
        }
        base.update(cambios)
        return base

    def test_el_serie_va_a_cpu_y_simuladores_gpu(self):
        cpu = run_tests.backend_arguments(self.caso(), "cpusim", opciones())
        self.assertIn("stdin", cpu)
        gpu = run_tests.backend_arguments(
            self.caso(architecture="gpu"), "gpusim", opciones())
        self.assertIn("stdin", gpu)
        self.assertIn("warp_config", gpu)
        hardware = run_tests.backend_arguments(
            self.caso(architecture="gpu"), "gpu-fpga", opciones())
        self.assertNotIn("stdin", hardware)

    def test_el_video_solo_se_pasa_si_el_caso_lo_pide(self):
        """Un caso normal no paga las lecturas de registros ni el frame."""
        sin = run_tests.backend_arguments(self.caso(), "cpusim", opciones())
        self.assertNotIn("video", sin)
        con = run_tests.backend_arguments(
            self.caso(run_until={"swap": 2}), "cpusim", opciones())
        self.assertEqual(con["video"]["run_until_swap"], 2)


class VideoTimingOutputTest(unittest.TestCase):
    def test_muestra_contadores_fisicos_en_run_until_de_placa(self):
        case = {"run_until": {"swap": 300}}
        result = {"video": {"frames": 318, "swaps": 300}}
        self.assertEqual(
            run_tests.video_timing_suffix(result, case, "cpu-fpga"),
            " (318 refrescos, 300 swaps, 18 sin swap, ~56.6 FPS @ 60 Hz)")

    def test_no_calcula_fps_con_una_muestra_demasiado_corta(self):
        case = {"run_until": {"swap": 1}}
        result = {"video": {"frames": 3, "swaps": 1}}
        self.assertEqual(
            run_tests.video_timing_suffix(result, case, "cpu-fpga"),
            " (3 refrescos, 1 swap, 2 sin swap)")

    def test_no_presenta_frames_sinteticos_como_medida_fisica(self):
        case = {"run_until": {"swap": 300}}
        result = {"video": {"frames": 318, "swaps": 300}}
        self.assertEqual(
            run_tests.video_timing_suffix(result, case, "cpusim"), "")

    def test_sin_run_until_no_hay_resumen(self):
        result = {"video": {"frames": 10, "swaps": 0}}
        self.assertEqual(
            run_tests.video_timing_suffix(result, {"run_until": None},
                                          "cpu-fpga"), "")


if __name__ == "__main__":
    unittest.main()
