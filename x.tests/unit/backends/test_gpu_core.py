"""Backend `fpga-sys` (la GPU de la 36 y la 37), sin placa."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import run_tests as runner
from backends import gpu_core
from tools import bench_all
from tools.rtl_facts import backends_from_rtl, load_capability_signals

REPOSITORIO = runner.REPOSITORY


class ClienteFalso:
    """Un cliente del monitor que anota los accesos y contesta lo que se le diga."""

    def __init__(self, lecturas=None):
        self.accesos = []
        self.lecturas = {k: list(v) for k, v in (lecturas or {}).items()}

    def write_word(self, direccion, valor):
        self.accesos.append(("w", direccion, valor))

    def read_word(self, direccion):
        self.accesos.append(("r", direccion, None))
        cola = self.lecturas.get(direccion)
        if cola is None:
            return 0
        return cola.pop(0) if len(cola) > 1 else cola[0]

    def escrituras(self):
        return [(d, v) for tipo, d, v in self.accesos if tipo == "w"]


def warp(warp_id, pc=0, active=0, group=0, logical=0, arg=0):
    return SimpleNamespace(warp_id=warp_id, pc=pc, active_mask=active,
                           workgroup_id=group, logical_warp_id=logical, arg=arg)


class LanzamientoTest(unittest.TestCase):
    def test_reset_primero_run_el_ultimo_y_la_mascara_de_lanzados(self):
        cliente = ClienteFalso()
        lanzados = gpu_core.configure_and_launch(
            cliente, [warp(0, pc=0x40, active=0xFF), warp(2, pc=0x80, active=0x0F)])
        escrituras = cliente.escrituras()
        self.assertEqual(lanzados, 0b101)
        self.assertEqual(escrituras[0], (gpu_core.GPU_CONTROL, gpu_core.CTRL_RESET))
        self.assertEqual(escrituras[-1], (gpu_core.GPU_CONTROL, gpu_core.CTRL_RUN))

    def test_escribe_los_ocho_descriptores_y_apaga_los_que_no_participan(self):
        """Desde el hito 2 RESET conserva los descriptores: un warp con ACTIVE
        de un caso anterior arrancaria con RUN."""
        cliente = ClienteFalso()
        gpu_core.configure_and_launch(cliente, [warp(1, pc=0x10, active=0x3)])
        activos = {
            (d - gpu_core.MMIO_GPU_WARPS_BASE) // 16: v
            for d, v in cliente.escrituras()
            if gpu_core.MMIO_GPU_WARPS_BASE <= d < gpu_core.MMIO_GPU_WARPS_BASE + 0x80
            and d % 16 == gpu_core.MMIO_GPU_WARPS_ACTIVE_OFF
        }
        self.assertEqual(activos, {w: (0x3 if w == 1 else 0) for w in range(8)})

    def test_active_es_lo_ultimo_de_cada_descriptor(self):
        """En el hito 1 escribir ACTIVE hace vivo al warp, y escribir el
        descriptor de un warp vivo es un error."""
        cliente = ClienteFalso()
        gpu_core.configure_and_launch(
            cliente, [warp(0, pc=0x40, active=0xFF, group=7, logical=9, arg=0x1234)])
        base = gpu_core.MMIO_GPU_WARPS_BASE
        propias = [d for d, _ in cliente.escrituras()
                   if d in (base + gpu_core.MMIO_GPU_WARPS_PC_OFF,
                            base + gpu_core.MMIO_GPU_WARPS_GROUP_OFF,
                            base + gpu_core.MMIO_GPU_WARPS_LOGICAL_ID_OFF,
                            base + gpu_core.MMIO_GPU_WARPS_ARG_OFF,
                            base + gpu_core.MMIO_GPU_WARPS_ACTIVE_OFF)][:5]
        self.assertEqual(propias[-1], base + gpu_core.MMIO_GPU_WARPS_ACTIVE_OFF)
        valores = dict(cliente.escrituras())
        self.assertEqual(valores[base + gpu_core.MMIO_GPU_WARPS_LOGICAL_ID_OFF], 9)
        self.assertEqual(valores[base + gpu_core.MMIO_GPU_WARPS_ARG_OFF], 0x1234)
        self.assertEqual(valores[base + gpu_core.MMIO_GPU_WARPS_GROUP_OFF], 7)

    def test_sin_warps_activos_no_hay_run(self):
        """RUN sin ningun descriptor habilitado es un error del contrato."""
        cliente = ClienteFalso()
        self.assertEqual(gpu_core.configure_and_launch(cliente, [warp(0)]), 0)
        self.assertNotIn((gpu_core.GPU_CONTROL, gpu_core.CTRL_RUN),
                         cliente.escrituras())


class EsperaTest(unittest.TestCase):
    def _reloj(self, pasos):
        iterador = iter(pasos)
        return lambda: next(iterador)

    def test_acaba_cuando_estan_todos_los_warps_y_la_gpu_ya_no_corre(self):
        cliente = ClienteFalso({
            gpu_core.WARP_DONE: [0b01, 0b11],
            gpu_core.GPU_STATUS: [gpu_core.STATUS_RUNNING, gpu_core.STATUS_RUNNING,
                                  gpu_core.STATUS_IDLE],
        })
        estado = gpu_core.wait_for_kernel(
            cliente, 0b11, 5.0, clock=lambda: 0.0, sleep=lambda _s: None)
        self.assertEqual(estado, gpu_core.STATUS_IDLE)

    def test_no_basta_con_idle_justo_despues_de_run(self):
        """El lanzamiento es un pulso registrado: IDLE puede verse un ciclo
        antes de que el warp arranque. Manda WARP_DONE."""
        cliente = ClienteFalso({
            gpu_core.WARP_DONE: [0, 0, 0b1],
            gpu_core.GPU_STATUS: [gpu_core.STATUS_IDLE],
        })
        gpu_core.wait_for_kernel(cliente, 0b1, 5.0, clock=lambda: 0.0,
                                 sleep=lambda _s: None)
        lecturas_done = [a for a in cliente.accesos if a[:2] == ("r", gpu_core.WARP_DONE)]
        self.assertEqual(len(lecturas_done), 3)

    def test_un_error_corta_la_espera_aunque_falten_warps(self):
        cliente = ClienteFalso({
            gpu_core.WARP_DONE: [0],
            gpu_core.GPU_STATUS: [gpu_core.STATUS_ERROR | gpu_core.STATUS_HALTED],
        })
        estado = gpu_core.wait_for_kernel(
            cliente, 0b11, 5.0, clock=lambda: 0.0, sleep=lambda _s: None)
        self.assertTrue(estado & gpu_core.STATUS_ERROR)

    def test_el_plazo_para_la_gpu_y_lo_dice(self):
        cliente = ClienteFalso({
            gpu_core.WARP_DONE: [0], gpu_core.GPU_STATUS: [gpu_core.STATUS_RUNNING]})
        with self.assertRaises(TimeoutError):
            gpu_core.wait_for_kernel(
                cliente, 0b1, 2.0, clock=self._reloj([0.0, 1.0, 3.0, 4.0]),
                sleep=lambda _s: None)
        self.assertIn((gpu_core.GPU_CONTROL, gpu_core.CTRL_HALT), cliente.escrituras())


class ObservacionesTest(unittest.TestCase):
    def test_sin_error_solo_el_total_y_lo_pedido(self):
        cliente = ClienteFalso({
            gpu_core.PERF_RETIRED: [123], gpu_core.SIMT_WARP_RETIRED: [8]})
        obs, codigo = gpu_core.read_observations(
            cliente, gpu_core.STATUS_IDLE, {"warp[3].instructions_executed"})
        self.assertEqual(obs, {"fault.present": False, "instructions_executed": 123,
                               "warp[3].instructions_executed": 8})
        self.assertEqual(codigo, 0)
        # CONTEXT elige el warp (bits 5:3) antes de leer su contador.
        self.assertIn((gpu_core.SIMT_CONTEXT, 3 << 3), cliente.escrituras())

    def test_no_paga_serie_por_los_warps_que_no_se_piden(self):
        cliente = ClienteFalso({gpu_core.PERF_RETIRED: [1]})
        gpu_core.read_observations(cliente, gpu_core.STATUS_IDLE, set())
        self.assertEqual(cliente.escrituras(), [])

    def test_el_fallo_trae_pc_warp_y_lane_si_es_valida(self):
        diagnostico = (4 << 8) | 0x40 | (3 << 3) | 5
        cliente = ClienteFalso({
            gpu_core.PERF_RETIRED: [9],
            gpu_core.SIMT_FIRST_ERROR: [diagnostico],
            gpu_core.SIMT_FIRST_ERROR_PC: [44]})
        obs, codigo = gpu_core.read_observations(
            cliente, gpu_core.STATUS_ERROR, set())
        self.assertEqual(codigo, 4)
        self.assertEqual(
            (obs["fault.pc"], obs["fault.warp_id"], obs["fault.core_id"]), (44, 3, 5))
        self.assertIsNone(obs["fault.address"])

    def test_lane_no_valida_y_fallo_de_memoria_sin_direccion_inventada(self):
        sin_lane = (6 << 8) | (3 << 3) | 5
        cliente = ClienteFalso({gpu_core.SIMT_FIRST_ERROR: [sin_lane]})
        obs, _ = gpu_core.read_observations(cliente, gpu_core.STATUS_ERROR, set())
        self.assertIsNone(obs["fault.core_id"])
        memoria = (gpu_core.ERROR_MEMORY_ACCESS << 8) | 0x40
        cliente = ClienteFalso({gpu_core.SIMT_FIRST_ERROR: [memoria]})
        obs, codigo = gpu_core.read_observations(
            cliente, gpu_core.STATUS_ERROR, set())
        self.assertEqual(codigo, gpu_core.ERROR_MEMORY_ACCESS)
        self.assertNotIn("fault.address", obs)


class VersionesTest(unittest.TestCase):
    def test_solo_las_carpetas_con_cpu_y_gpu(self):
        carpetas = {v["monitor_path"].parent.name for v in gpu_core.VERSIONS.values()}
        self.assertEqual(carpetas, {"36.fpga-cpu-gpu", "37.fpga-cpu-gpu-mk2"})
        self.assertEqual(set(gpu_core.VERSIONS), {"cpugpu", "mk2"})

    def test_la_36_y_la_37_siguen_siendo_cpu_para_cpu_fpga(self):
        """`fpga-sys` es ADEMAS: no las saca de `fpga-cpu` ni de `fpga-gpu`."""
        from backends import fpga, gpu_fpga
        self.assertIn("cpugpu", fpga.VERSIONS)
        self.assertIn("mk2", fpga.VERSIONS)
        self.assertNotIn("cpugpu", gpu_fpga.VERSIONS)
        self.assertNotIn("mk2", gpu_fpga.VERSIONS)

    def test_backends_from_rtl(self):
        self.assertEqual(backends_from_rtl(REPOSITORIO / "36.fpga-cpu-gpu"), ("cpu", "gpu"))
        self.assertEqual(backends_from_rtl(REPOSITORIO / "37.fpga-cpu-gpu-mk2"), ("cpu", "gpu"))
        # La 35 tiene el adaptador de memoria de la GPU pero ninguna GPU.
        self.assertEqual(backends_from_rtl(REPOSITORIO / "35.fpga-cpu-fifo-sdram2"), ("cpu",))
        self.assertEqual(backends_from_rtl(REPOSITORIO / "29.fpga-gpu-sm-pipeline"), ("gpu",))

    def test_las_capacidades_son_las_de_la_gpu_y_no_las_de_su_cpu(self):
        """Una capacidad con `file: ["cpu.v", "gpu_lane.v"]` se detectaría en
        `cpu.v` y se atribuiría a una lane que no la tiene."""
        senales = load_capability_signals(REPOSITORIO)
        with tempfile.TemporaryDirectory() as tmp:
            carpeta = Path(tmp)
            (carpeta / "cpu.v").write_text("OPCODE_MULHI: begin end\n", encoding="utf-8")
            (carpeta / "gpu_lane.v").write_text("// sin nada\n", encoding="utf-8")
            self.assertNotIn("alu_extended", gpu_core.gpu_capabilities(carpeta, senales))
            (carpeta / "gpu_lane.v").write_text("OPCODE_MULHI: begin end\n", encoding="utf-8")
            self.assertIn("alu_extended", gpu_core.gpu_capabilities(carpeta, senales))

    def test_el_video_y_el_puerto_serie_son_de_la_cpu(self):
        for version in gpu_core.VERSIONS:
            with self.subTest(version=version):
                capacidades = gpu_core.capabilities(version)
                self.assertFalse({"video", "frame_capture", "serial", "input"} & capacidades)

    def test_la_37_tiene_la_isa_extendida_y_la_36_no(self):
        self.assertLessEqual({"alu_extended", "calls", "compare"},
                             gpu_core.capabilities("mk2"))
        self.assertFalse({"alu_extended", "calls", "compare"} & gpu_core.capabilities("cpugpu"))


class IncompatibilidadTest(unittest.TestCase):
    def _caso(self, relativa):
        return runner.load_case(runner.ROOT / relativa, "gpu")

    def test_lo_que_el_rtl_no_expone_se_omite_con_motivo(self):
        caso = self._caso("cases-gpu/alu/r0-hardwired-zero/test.json")
        motivo = gpu_core.incompatibility(caso, "mk2")
        self.assertIn("registros de las lanes", motivo)
        self.assertIn("PC final", motivo)

    def test_un_caso_solo_de_memoria_se_ejecuta(self):
        caso = self._caso("cases-gpu/programs/mandelbrot-packed/test.json")
        self.assertIsNone(gpu_core.incompatibility(caso, "mk2"))
        self.assertIsNone(gpu_core.incompatibility(caso, "cpugpu"))

    def test_la_isa_extendida_se_omite_en_la_36_y_se_ejecuta_en_la_37(self):
        caso = self._caso("cases-shared/alu-extended/mulhi-div-rem/test.json")
        self.assertIn("alu_extended", gpu_core.incompatibility(caso, "cpugpu"))
        self.assertIsNone(gpu_core.incompatibility(caso, "mk2"))

    def test_el_video_es_de_la_cpu(self):
        caso = self._caso("cases-shared/video/double-buffer/test.json")
        self.assertIn("video", gpu_core.incompatibility(caso, "mk2"))

    def test_los_casos_de_gpu_que_se_aceptan_son_pocos_y_se_conocen(self):
        """Mientras el RTL no exponga el estado de los warps, casi todo se
        omite. Si este numero sube es que se ha expuesto algo; hay que decirlo
        en `x.tests/backend-gpu-core.md` y no solo subir la cifra."""
        aceptados = []
        for ruta in sorted((runner.ROOT / "cases-gpu").rglob("test.json")):
            caso = runner.load_case(ruta)
            if gpu_core.incompatibility(caso, "mk2") is None:
                aceptados.append(caso["name"])
        self.assertEqual(aceptados, ["demo-warp-lane-bands", "gpu-mandelbrot-packed"])


class RegistroEnElRunnerTest(unittest.TestCase):
    def test_el_backend_esta_registrado_con_arquitectura_gpu(self):
        definicion = runner.BACKEND_DEFINITIONS["fpga-sys"]
        self.assertEqual(definicion["architecture"], "gpu")
        self.assertIn("fpga-sys", runner.BACKENDS_DE_PLACA)

    def test_prototype_36_resuelve_a_cada_familia(self):
        self.assertEqual(runner.version_for_prototype("36", ("fpga-sys",)),
                         ("fpga-sys", "cpugpu"))
        self.assertEqual(runner.version_for_prototype("36", ("fpga-cpu",)),
                         ("fpga-cpu", "cpugpu"))
        self.assertEqual(runner.version_for_prototype("37", ("sim-gpu", "fpga-sys")),
                         ("fpga-sys", "mk2"))

    def test_gpu_fpga_sigue_sin_conocer_la_36(self):
        with self.assertRaises(ValueError):
            runner.version_for_prototype("36", ("fpga-gpu",))


class TodosLosProtosTest(unittest.TestCase):
    """`test-all`: la 36 y la 37 salen como CPU y como GPU."""

    def test_aparecen_en_las_dos_familias(self):
        gpu = {n for f, n, _ in bench_all.prototypes("gpu", core=True)}
        cpu = {n for f, n, _ in bench_all.prototypes("cpu", core=True)}
        self.assertLessEqual({36, 37}, gpu)
        self.assertLessEqual({36, 37}, cpu)

    def test_sin_core_bench_no_cambia(self):
        """`bench` mide, y fpga-sys todavia no admite --measure."""
        gpu = {n for f, n, _ in bench_all.prototypes("gpu")}
        self.assertFalse({36, 37} & gpu)

    def test_backend_de_cada_familia(self):
        self.assertEqual(bench_all.board_backend("gpu", 36), "fpga-sys")
        self.assertEqual(bench_all.board_backend("gpu", 37), "fpga-sys")
        self.assertEqual(bench_all.board_backend("cpu", 36), "fpga-cpu")
        self.assertEqual(bench_all.board_backend("gpu", 29), "fpga-gpu")
        self.assertEqual(bench_all.board_backend("cpu", 21), "fpga-cpu")


if __name__ == "__main__":
    unittest.main()
