"""El depurador contra CPU + GPU (`mini-dbg --gpu`), sin abrir un terminal.

`SystemTarget` envuelve el simulador de `32.cpu-gpu-func-sim`; aquí se prueba
con programas de verdad: una CPU que escribe los descriptores, lanza dos warps
y sondea `WARP_DONE`, y un kernel distinto en cada caso.

Las decisiones que fijan estos tests: parada total, `step` solo mueve el núcleo
(y el warp) con foco, una lista de breakpoints para los dos núcleos y dos
resets (blando de la GPU, duro del sistema).
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "2.cpu-sim-func"))
sys.path.insert(0, str(ROOT / "32.cpu-gpu-func-sim"))

from cpu_gpu_sim import CpuGpuSystem  # noqa: E402
from minicpu_sim import CPU  # noqa: E402
from tools import debug_cli, debug_source  # noqa: E402
from tools.debug_core import (  # noqa: E402
    STOP_BREAKPOINT, STOP_ERROR, STOP_HALT, STOP_WATCH, DebugSession,
    format_lane_grid, mask_bits,
)
from tools.debug_system import SystemTarget  # noqa: E402
from tools.debug_target import SimTarget, TargetError  # noqa: E402

# La CPU del ejemplo `launch.asm`: descriptores de los warps 0 y 1, `WARP_START`
# y sondeo de `WARP_DONE`. El kernel va detrás, en la misma imagen.
CPU_SIDE = """
.include "mmio.inc"
start:
    LI    R10, MMIO_GPU_BASE
    LI    R11, MMIO_GPU_WARPS_BASE
    LI    R12, kernel
    MOVI  R13, 0xFF
    STORE R12, R11, MMIO_GPU_WARPS_PC_OFF
    STORE R13, R11, MMIO_GPU_WARPS_ACTIVE_OFF
    STORE R12, R11, 16 + MMIO_GPU_WARPS_PC_OFF
    STORE R13, R11, 16 + MMIO_GPU_WARPS_ACTIVE_OFF
go:
    MOVI  R14, 3
    STORE R14, R10, MMIO_GPU_WARP_START_OFF
wait:
    LOAD  R15, R10, MMIO_GPU_WARP_DONE_OFF
    BNE   R15, R14, wait
    STORE R14, R10, MMIO_GPU_WARP_DONE_OFF
    HALT
kernel:
"""

KERNEL_SIMPLE = """
    GETTID R1
    ADDI   R2, R1, 1
    ADDI   R2, R2, 1
    HALT
"""

KERNEL_BARRIER = """
    GETTID R1
    BAR
    ADDI   R2, R1, 5
    HALT
"""

# Las lanes 0-3 saltan al punto de reconvergencia; solo las 4-7 hacen el ADDI.
KERNEL_DIVERGE = """
    GETTID R1
    ANDI   R1, R1, 7
    MOVI   R2, 4
    SSY    done
    BLT    R1, R2, done
    ADDI   R3, R3, 10
done:
    ADDI   R3, R3, 1
    HALT
"""

# Las ocho lanes escriben su tid en la misma palabra: gana la última (7, 15...).
KERNEL_STORE = """
    GETTID R1
    LI     R5, out
    STORE  R1, R5, 0
    HALT
out:
    .word 0
"""

# Dirección 0xFFFFFFFC: fuera de memoria, error de acceso.
KERNEL_FAULT = """
    MOVI   R1, -4
    LOAD   R2, R1, 0
    HALT
"""

INCLUDES = (ROOT / "x.tests" / "inc",)


def build(kernel: str = KERNEL_SIMPLE, **options) -> DebugSession:
    path = Path(tempfile.mkdtemp()) / "programa.asm"
    path.write_text(CPU_SIDE + kernel, encoding="utf-8")
    image = debug_cli.load_program(path, INCLUDES)
    system = CpuGpuSystem(64 * 1024, **options)
    system.load_cpu_program(image)
    target = SystemTarget(system, image)
    return DebugSession(target, debug_source.from_program(path, INCLUDES))


def launched(kernel: str = KERNEL_SIMPLE, **options) -> DebugSession:
    """Una sesión parada justo cuando la CPU acaba de lanzar el warp 0."""
    session = build(kernel, **options)
    session.execute("break kernel")
    session.execute("run")
    return session


class StopTest(unittest.TestCase):
    def test_a_breakpoint_on_the_kernel_stops_when_the_cpu_launches_it(self):
        session = build()
        session.execute("break kernel")
        lines = session.execute("run")
        target = session.target
        self.assertIn("[GPU warp 0]", lines[0])
        self.assertEqual(target.core(), "gpu")
        self.assertEqual(target.state().pc, session.source.resolve("kernel"))
        # Parada total: la GPU no ha ejecutado nada, la CPU se quedó en el
        # `STORE` que lanzó los warps.
        self.assertEqual(target.system.gpu.retired, 0)

    def test_every_warp_launched_on_a_mark_stops_once(self):
        session = launched()
        first = session.execute("run")
        self.assertIn("[GPU warp 1]", first[0])
        self.assertEqual(session.target.system.gpu.retired, 0)
        last = session.execute("run")
        self.assertIn("HALT", last[0])

    def test_stop_reason_names_the_core(self):
        session = build()
        session.execute("break wait")
        stop = session.resume()
        self.assertEqual(stop.kind, STOP_BREAKPOINT)
        self.assertEqual(session.target.core(), "cpu")
        self.assertIn("[CPU]", session.describe_stop(stop))

    def test_run_reaches_halt_with_both_cores_done(self):
        session = build()
        stop = session.resume()
        self.assertEqual(stop.kind, STOP_HALT)
        system = session.target.system
        self.assertTrue(system.finished)
        self.assertEqual(system.gpu.done, 0)         # la CPU lo limpió (W1C)
        self.assertEqual(system.gpu.retired, 2 * 4)  # dos warps, 4 instrucciones

    def test_a_gpu_error_stops_everything_and_moves_the_focus(self):
        session = build(KERNEL_FAULT)
        session.execute("core cpu")
        stop = session.resume()
        self.assertEqual(stop.kind, STOP_ERROR)
        text = session.describe_stop(stop)
        self.assertIn("ERROR 0x02", text)
        self.assertIn("[GPU warp", text)
        self.assertEqual(session.target.core(), "gpu")
        # La CPU no estaba rota: se paró porque la GPU lo estaba.
        self.assertFalse(session.target.system.cpu.error)

    def test_step_on_a_gpu_with_an_error_points_to_the_soft_reset(self):
        session = build(KERNEL_FAULT)
        session.resume()
        self.assertIn("reset gpu", session.execute("step")[0])
        session.execute("reset gpu")
        self.assertIsNone(session.target.system.gpu.fault)


class SteppingTest(unittest.TestCase):
    def test_step_moves_only_the_focused_warp(self):
        session = launched()
        system = session.target.system
        cpu_before = system.cpu.instructions_executed
        session.execute("step 3")
        warps = system.gpu.warps
        self.assertEqual(warps[0].instructions_executed, 3)
        self.assertEqual(warps[1].instructions_executed, 0)
        self.assertEqual(system.cpu.instructions_executed, cpu_before)

    def test_step_on_the_cpu_freezes_the_gpu(self):
        session = launched()
        system = session.target.system
        session.execute("core cpu")
        before = system.cpu.instructions_executed
        session.execute("step 5")
        self.assertEqual(system.cpu.instructions_executed, before + 5)
        self.assertEqual(system.gpu.retired, 0)

    def test_gpu_step_ignores_breakpoints_like_any_explicit_step(self):
        session = launched()
        session.execute("break 0x00000054")
        session.execute("step 4")
        self.assertEqual(session.target.system.gpu.warps[0]
                         .instructions_executed, 4)

    def test_step_hops_to_the_next_warp_when_the_focused_one_waits(self):
        session = launched(KERNEL_BARRIER)
        warps = session.target.system.gpu.warps
        session.execute("step 2")                    # GETTID y BAR del warp 0
        self.assertEqual(warps[0].state, "WAIT_BAR")
        lines = session.execute("step")
        self.assertIn("warp 0 espera en una barrera", lines[0])
        self.assertIn("warp 1", lines[0])
        rows = session.target.warp_rows()
        self.assertEqual([row.number for row in rows if row.focused], [1])
        session.execute("step")                      # BAR del warp 1: libera
        self.assertEqual(warps[0].state, "READY")
        self.assertEqual(warps[1].state, "READY")

    def test_step_hops_to_the_next_warp_when_the_focused_one_finished(self):
        session = launched()
        session.execute("step 4")                    # warp 0 hasta el HALT
        lines = session.execute("step")
        self.assertIn("warp 0 ha terminado", lines[0])
        self.assertEqual(session.target.warp_rows()[1].focused, True)

    def test_step_without_live_warps_says_why(self):
        session = build()
        session.execute("core gpu")
        self.assertIn("no tiene warps vivos", session.execute("step")[0])

    def test_stepping_a_warp_leaves_the_scheduler_where_it_was(self):
        session = launched()
        scheduler = session.target.system.gpu.system.streaming_multiprocessor
        before = scheduler.next_warp
        session.execute("step 2")
        self.assertEqual(scheduler.next_warp, before)


class RoundTest(unittest.TestCase):
    """`round`: una instrucción en cada warp que pueda avanzar, sin mover el foco."""

    def test_one_round_runs_one_instruction_in_every_live_warp(self):
        session = launched()
        system = session.target.system
        cpu_before = system.cpu.instructions_executed
        lines = session.execute("round")
        warps = system.gpu.warps
        self.assertEqual([w.instructions_executed for w in warps[:3]], [1, 1, 0])
        self.assertIn("warps 0 1", lines[0])
        self.assertIn("2 instrucciones", lines[0])
        self.assertEqual(system.cpu.instructions_executed, cpu_before)

    def test_the_focus_does_not_move(self):
        session = launched()
        session.execute("warp 1")
        before = session.target.name
        session.execute("round 2")
        self.assertEqual(session.target.name, before)
        session.execute("core cpu")
        session.execute("round")
        self.assertEqual(session.target.core(), "cpu")

    def test_several_rounds_are_summarised(self):
        session = launched()
        lines = session.execute("round 3")
        self.assertEqual(lines, ["3 rondas (6 instrucciones)"])
        warps = session.target.system.gpu.warps
        self.assertEqual([w.instructions_executed for w in warps[:2]], [3, 3])

    def test_a_finished_warp_drops_out_of_the_next_rounds(self):
        session = launched()
        session.execute("round 4")                  # los dos acaban (4 instr.)
        with self.assertRaises(TargetError) as caught:
            session.execute("round")
        self.assertIn("no tiene warps vivos", str(caught.exception))

    def test_rounds_stop_when_nothing_is_left_to_run(self):
        session = launched()
        lines = session.execute("round 10")
        self.assertEqual(lines, ["4 rondas (8 instrucciones)"])

    def test_a_barrier_is_crossed_inside_a_round(self):
        session = launched(KERNEL_BARRIER)
        warps = session.target.system.gpu.warps
        session.execute("round 2")        # GETTID, y BAR: el segundo libera a los dos
        self.assertEqual([w.state for w in warps[:2]], ["READY", "READY"])
        session.execute("round")          # ADDI de los dos, ya sin esperar
        self.assertEqual([w.instructions_executed for w in warps[:2]], [3, 3])

    def test_a_fault_stops_the_round_and_focuses_the_faulty_warp(self):
        session = launched(KERNEL_FAULT)
        session.execute("core cpu")
        session.execute("round")
        lines = session.execute("round")             # el LOAD del warp 0 falla
        self.assertIn("ERROR 0x02", lines[-1])
        self.assertEqual(session.target.core(), "gpu")
        warps = session.target.system.gpu.warps
        # parada total: el warp 1 no ejecutó su LOAD
        self.assertEqual([w.instructions_executed for w in warps[:2]], [1, 1])

    def test_it_needs_a_gpu(self):
        with self.assertRaises(TargetError):
            DebugSession(SimTarget(CPU(64 * 1024))).execute("round")

    def test_without_live_warps_it_says_why(self):
        with self.assertRaises(TargetError) as caught:
            build().execute("round")
        self.assertIn("no tiene warps vivos", str(caught.exception))


class SchedTest(unittest.TestCase):
    """`sched`: el paso del planificador, con el foco siguiendo al warp."""

    def focus(self, session):
        return [r.number for r in session.target.warp_rows() if r.focused]

    def test_the_scheduler_alternates_warps_and_the_focus_follows(self):
        session = launched()
        order = []
        for _ in range(4):
            session.execute("sched")
            order.append(self.focus(session)[0])
        self.assertEqual(order, [0, 1, 0, 1])

    def test_the_line_names_the_warp_that_ran(self):
        session = launched()
        session.execute("sched")
        self.assertIn("[GPU warp 1]", session.execute("sched")[0])

    def test_it_moves_the_focus_from_the_cpu_to_the_gpu(self):
        session = launched()
        session.execute("core cpu")
        session.execute("sched")
        self.assertEqual(session.target.core(), "gpu")

    def test_the_lane_survives_the_change_of_warp(self):
        session = launched()
        session.execute("lane 5")
        session.execute("sched 2")
        self.assertIn("l5", session.target.name)

    def test_n_steps_in_a_row(self):
        session = launched()
        lines = session.execute("sched 4")
        self.assertIn("(4 instrucciones)", lines[0])
        warps = session.target.system.gpu.warps
        self.assertEqual([w.instructions_executed for w in warps[:2]], [2, 2])

    def test_it_matches_the_real_round_robin(self):
        # Mismo orden que el planificador de verdad: lo que `run` ejecutaría.
        session = launched()
        gpu = session.target.system.gpu
        order = []
        for _ in range(4):
            before = [w.instructions_executed for w in gpu.warps]
            session.execute("sched")
            after = [w.instructions_executed for w in gpu.warps]
            order.append(next(i for i, (a, b) in enumerate(zip(before, after))
                              if a != b))
        reference = launched().target.system.gpu
        expected = []
        for _ in range(4):
            before = [w.instructions_executed for w in reference.warps]
            reference.step()
            after = [w.instructions_executed for w in reference.warps]
            expected.append(next(i for i, (a, b) in enumerate(zip(before, after))
                                 if a != b))
        self.assertEqual(order, expected)

    def test_a_manual_step_does_not_disturb_the_scheduler(self):
        session = launched()
        session.execute("warp 1")
        session.execute("step 2")                    # a mano, sin planificador
        session.execute("sched")
        self.assertEqual(self.focus(session), [0])   # el planificador seguía en 0

    def test_it_skips_a_warp_waiting_in_a_barrier(self):
        session = launched(KERNEL_BARRIER)
        session.execute("sched 3")                   # w0 GETTID, w1 GETTID, w0 BAR
        warps = session.target.system.gpu.warps
        self.assertEqual(warps[0].state, "WAIT_BAR")
        session.execute("sched")                     # le toca a w1, no a w0
        self.assertEqual(self.focus(session), [1])

    def test_a_fault_is_reported_and_stops_the_run_of_steps(self):
        session = launched(KERNEL_FAULT)
        lines = session.execute("sched 10")
        self.assertIn("ERROR 0x02", lines[0])

    def test_it_needs_live_warps(self):
        with self.assertRaises(TargetError):
            build().execute("sched")

    def test_it_needs_a_gpu(self):
        with self.assertRaises(TargetError):
            DebugSession(SimTarget(CPU(64 * 1024))).execute("sched")


class FocusTest(unittest.TestCase):
    def test_core_without_argument_toggles(self):
        session = build()
        self.assertEqual(session.target.core(), "cpu")
        session.execute("core")
        self.assertEqual(session.target.core(), "gpu")
        session.execute("core")
        self.assertEqual(session.target.core(), "cpu")

    def test_warp_and_lane_select_and_imply_the_gpu(self):
        session = build()
        session.execute("warp 3")
        self.assertEqual(session.target.core(), "gpu")
        self.assertIn("w3 l0", session.execute("lane 0")[0])
        session.execute("lane 5")
        self.assertIn("l5", session.target.name)

    def test_warp_without_argument_cycles(self):
        session = build(num_warps=3)
        session.execute("warp 2")
        session.execute("warp")
        self.assertEqual([r.number for r in session.target.warp_rows()
                          if r.focused], [0])

    def test_out_of_range_is_a_target_error(self):
        session = build(num_warps=2)
        with self.assertRaises(TargetError):
            session.execute("warp 2")
        with self.assertRaises(TargetError):
            session.execute("lane 8")
        with self.assertRaises(TargetError):
            session.execute("core fpga")

    def test_registers_follow_the_focused_lane(self):
        session = launched()
        session.execute("step")                      # GETTID: R1 = lane
        session.execute("lane 3")
        self.assertEqual(session.target.registers()[1], 3)
        session.execute("lane 6")
        self.assertEqual(session.target.registers()[1], 6)
        session.execute("core cpu")
        self.assertNotEqual(session.target.registers()[11], 6)

    def test_set_register_writes_the_focused_lane_only(self):
        session = launched()
        session.execute("lane 2")
        session.execute("set R9 0x77")
        grid = session.target.lane_grid()
        self.assertEqual([lane[9] for lane in grid.regs],
                         [0, 0, 0x77, 0, 0, 0, 0, 0])

    def test_status_line_names_both_cores(self):
        session = launched()
        line = session.status_line()
        self.assertIn("GPU w0 l0", line)
        self.assertIn("CPU PC=", line)
        session.execute("core cpu")
        self.assertIn("GPU 2/8 vivos", session.status_line())


class ViewTest(unittest.TestCase):
    def test_warp_table_shows_the_descriptor_before_the_launch(self):
        session = build()
        session.execute("until go")
        row = session.target.warp_rows()[0]
        self.assertEqual(row.state, "CONFIG")
        self.assertEqual(row.pc, session.source.resolve("kernel"))
        self.assertEqual(row.active_mask, 0xFF)

    def test_warps_command_lists_every_warp(self):
        session = launched()
        lines = session.execute("warps")
        self.assertEqual(len(lines), 1 + 8)
        self.assertTrue(lines[1].startswith("▶"))
        self.assertIn("READY", lines[1])

    def test_divergence_shows_in_the_mask(self):
        session = launched(KERNEL_DIVERGE)
        session.execute("step 5")                    # hasta el BLT inclusive
        row = session.target.warp_rows()[0]
        self.assertEqual(row.active_mask, 0xF0)
        self.assertEqual(row.live_mask, 0xFF)
        self.assertEqual(row.region_depth, 1)
        self.assertEqual(mask_bits(row.active_mask, row.live_mask, 8),
                         "○○○○●●●●")

    def test_lanes_command_hides_all_zero_rows(self):
        session = launched()
        session.execute("step 2")
        lines = session.execute("lanes")
        self.assertTrue(any(line.startswith("R1 ") for line in lines))
        self.assertFalse(any(line.startswith("R20") for line in lines))
        self.assertIn("omitidos", lines[-1])

    def test_lane_grid_formatter_survives_an_all_zero_warp(self):
        session = build()
        lines = format_lane_grid(session.target.lane_grid())
        self.assertIn("32 registros a cero", lines[-1])

    def test_help_lists_the_gpu_commands(self):
        text = "\n".join(build().execute("help"))
        for name in ("core", "warp", "lane", "warps", "lanes"):
            self.assertIn(name, text)


class IndicatorTest(unittest.TestCase):
    def rows(self, session):
        return {row.address: row for row in session.listing(before=40, after=40)}

    def test_cpu_and_gpu_pcs_are_marked_on_their_own_rows(self):
        session = launched()
        rows = self.rows(session)
        cpu_pc, gpu_pc = session.target.pcs()
        self.assertEqual(gpu_pc, session.source.resolve("kernel"))
        self.assertTrue(rows[cpu_pc].cpu_pc)
        self.assertFalse(rows[cpu_pc].gpu_pc)
        self.assertTrue(rows[gpu_pc].gpu_pc)
        self.assertFalse(rows[gpu_pc].cpu_pc)
        self.assertEqual(sum(row.cpu_pc for row in rows.values()), 1)
        self.assertEqual(sum(row.gpu_pc for row in rows.values()), 1)

    def test_the_gpu_indicator_is_the_focused_warp(self):
        session = launched()
        session.execute("step 2")
        self.assertEqual(session.target.pcs()[1],
                         session.target.system.gpu.warps[0].pc)
        session.execute("warp 1")
        self.assertEqual(session.target.pcs()[1],
                         session.source.resolve("kernel"))

    def test_there_is_no_gpu_indicator_for_a_warp_that_is_not_alive(self):
        session = build()
        self.assertIsNone(session.target.pcs()[1])
        self.assertFalse(any(row.gpu_pc for row in self.rows(session).values()))

    def test_the_focused_core_keeps_the_reverse_row(self):
        session = launched()
        rows = self.rows(session)
        self.assertTrue(rows[session.source.resolve("kernel")].is_pc)
        session.execute("core cpu")
        rows = self.rows(session)
        self.assertTrue(rows[session.target.pcs()[0]].is_pc)

    def test_single_core_has_no_indicators(self):
        session = DebugSession(SimTarget(CPU(64 * 1024)))
        self.assertIsNone(session.target.pcs())
        self.assertFalse(any(row.cpu_pc or row.gpu_pc
                             for row in session.listing()))

    def test_code_panel_draws_both_letters(self):
        from tools.debug_tui import _code_view

        session = launched()
        text, _, _ = _code_view(session, 60)
        self.assertIn("[bold green]C[/bold green]", text)
        self.assertIn("[bold #4da3ff]G[/bold #4da3ff]", text)


class WatchTest(unittest.TestCase):
    def watched(self, kernel=KERNEL_STORE):
        session = build(kernel)
        session.execute("watch out")
        return session

    def test_watch_stops_on_the_write_and_names_the_warp(self):
        session = self.watched()
        stop = session.resume()
        self.assertEqual(stop.kind, STOP_WATCH)
        text = session.describe_stop(stop)
        self.assertIn("0x00000000 → 0x00000007", text)
        self.assertIn("GPU warp 0, PC=", text)
        self.assertEqual(session.target.core(), "gpu")
        self.assertEqual(session.target.warp_rows()[0].focused, True)

    def test_next_run_finds_the_next_writer(self):
        session = self.watched()
        session.resume()
        stop = session.resume()
        text = session.describe_stop(stop)
        self.assertIn("0x00000007 → 0x0000000F", text)
        self.assertIn("GPU warp 1", text)
        self.assertEqual(session.resume().kind, STOP_HALT)

    def test_the_writer_pc_is_the_store(self):
        session = self.watched()
        stop = session.resume()
        writer = session.target.last_writer()
        pc = int(writer.split("PC=")[1], 16)
        self.assertIn("STORE", session.source.text[pc])

    def test_step_reports_a_change_made_behind_the_debuggers_back(self):
        session = build()
        session.execute("watch 0x4000")
        # Alguien ajeno al depurador escribe: se nota en el siguiente comando.
        system = session.target.system
        system.cpu.write_u32(0x4000, 5)
        self.assertIn("0x00000000 → 0x00000005", "\n".join(
            session.execute("step")))

    def test_step_reports_a_change_it_caused(self):
        session = launched(KERNEL_STORE)
        session.execute("watch out")
        lines = session.execute("step 5")
        self.assertTrue(any(line.startswith("watch ") for line in lines),
                        lines)

    def test_step_does_not_report_a_change_twice(self):
        session = launched(KERNEL_STORE)
        session.execute("watch out")
        session.execute("step 5")
        self.assertFalse(any(line.startswith("watch ")
                             for line in session.execute("step")))

    def test_a_write_by_the_user_is_not_news(self):
        session = self.watched()
        session.execute("write out 9")
        self.assertFalse(any(line.startswith("watch ")
                             for line in session.execute("step")))
        # ...y el valor nuevo es el de referencia: solo salta si vuelve a cambiar.
        stop = session.resume()
        self.assertIn("0x00000009 → 0x00000007", session.describe_stop(stop))

    def test_watch_lists_and_unwatch_removes(self):
        session = self.watched()
        listing = session.execute("watch")
        self.assertEqual(len(listing), 1)
        self.assertIn("out", listing[0])
        session.execute("unwatch out")
        self.assertEqual(session.execute("watch"), ["sin watches"])
        self.assertEqual(session.resume().kind, STOP_HALT)
        self.assertFalse(session.target.track_writer)

    def test_unwatch_of_an_unknown_address_is_an_error(self):
        with self.assertRaises(Exception):
            build().execute("unwatch 0x100")

    def test_watch_wider_than_a_word(self):
        session = build(KERNEL_STORE)
        session.execute("watch out 8")
        self.assertEqual(session.resume().kind, STOP_WATCH)

    def test_watch_of_unreadable_memory_is_refused(self):
        with self.assertRaises(Exception):
            build().execute("watch 0x10000000")

    def test_watch_is_refused_where_reading_is_slow(self):
        session = build()
        session.target.fast_memory = False
        with self.assertRaises(TargetError):
            session.execute("watch 0x4000")

    def test_watch_works_on_a_single_core_too(self):
        sys.path.insert(0, str(ROOT / "1.isa"))
        from mini_asm import assemble_bytes

        cpu = CPU(64 * 1024)
        cpu.load_program(assemble_bytes(
            "MOVI R1, 0x100\nMOVI R2, 5\nSTORE R2, R1, 0\nHALT\n"))
        session = DebugSession(SimTarget(cpu))
        session.execute("watch 0x100")
        stop = session.resume()
        self.assertEqual(stop.kind, STOP_WATCH)
        text = session.describe_stop(stop)
        self.assertIn("0x00000000 → 0x00000005", text)
        self.assertIn("PC=0x00000008", text)

    def test_rows_remember_the_previous_value_and_the_writer(self):
        session = self.watched()
        session.resume()
        (row,) = session.watch_rows()
        self.assertEqual(row.label, "out")
        self.assertEqual(int.from_bytes(row.previous, "little"), 0)
        self.assertEqual(int.from_bytes(row.value, "little"), 7)
        self.assertIn("GPU warp 0", row.writer)
        self.assertTrue(row.changed)

    def test_rows_stop_being_changed_with_the_next_command(self):
        session = self.watched()
        session.resume()
        session.execute("regs")
        (row,) = session.watch_rows()
        self.assertFalse(row.changed)
        self.assertIn("GPU warp 0", row.writer)     # el autor se conserva

    def test_a_change_seen_by_step_has_no_writer(self):
        session = launched(KERNEL_STORE)
        session.execute("watch out")
        session.execute("step 5")
        (row,) = session.watch_rows()
        self.assertTrue(row.changed)
        self.assertEqual(row.writer, "")

    def test_untouched_watch_has_no_previous_value(self):
        (row,) = self.watched().watch_rows()
        self.assertIsNone(row.previous)
        self.assertFalse(row.changed)

    def test_help_lists_watch(self):
        text = "\n".join(build().execute("help"))
        self.assertIn("watch", text)
        self.assertIn("unwatch", text)


class ResetTest(unittest.TestCase):
    def test_hard_reset_starts_over(self):
        session = build()
        session.resume()
        system = session.target.system
        session.execute("write 0x4000 0xDEAD")
        session.execute("core gpu")
        session.execute("reset")
        self.assertEqual(system.memory[0x4000:0x4004], bytes(4))
        self.assertEqual(system.cpu.pc, 0)
        self.assertEqual(system.cpu.instructions_executed, 0)
        self.assertEqual(system.cpu_instructions, 0)
        self.assertEqual(system.gpu.retired, 0)
        self.assertFalse(system.cpu.halted)
        self.assertTrue(all(not any(d.values())
                            for d in system.gpu.descriptors))
        self.assertEqual(session.target.core(), "cpu")
        # La imagen vuelve a estar, y el programa vuelve a correr entero.
        self.assertEqual(bytes(system.memory[:len(session.target.image)]),
                         session.target.image)
        self.assertEqual(session.resume().kind, STOP_HALT)

    def test_hard_reset_keeps_the_breakpoints(self):
        session = build()
        session.execute("break kernel")
        session.execute("reset")
        self.assertEqual(session.breakpoints,
                         {session.source.resolve("kernel")})

    def test_soft_reset_only_touches_the_gpu(self):
        session = launched()
        system = session.target.system
        session.execute("write 0x4000 0xBEEF")
        pc = system.cpu.pc
        instructions = system.cpu.instructions_executed
        session.execute("reset gpu")
        self.assertEqual(system.gpu.live, 0)
        self.assertEqual(system.gpu.descriptors[0]["active"], 0xFF)
        self.assertEqual(system.gpu.descriptors[0]["pc"],
                         session.source.resolve("kernel"))
        self.assertEqual(int.from_bytes(system.memory[0x4000:0x4004],
                                        "little"), 0xBEEF)
        self.assertEqual((system.cpu.pc, system.cpu.instructions_executed),
                         (pc, instructions))

    def test_soft_reset_then_relaunch_works(self):
        session = launched()
        session.execute("reset gpu")
        # El descriptor sigue ahí: `WARP_START` desde la CPU repite el lanzamiento.
        system = session.target.system
        system.gpu.warp_start(0b01)
        self.assertEqual(system.gpu.live, 0b01)

    def test_reset_argument_is_checked(self):
        with self.assertRaises(Exception):
            build().execute("reset todo")


class SingleCoreTest(unittest.TestCase):
    """Un objetivo sin GPU no enseña ni acepta nada de esto."""

    def setUp(self):
        self.session = DebugSession(SimTarget(CPU(64 * 1024)))

    def test_gpu_commands_are_refused_with_the_reason(self):
        for command in ("core", "warp 1", "lane", "warps", "lanes"):
            with self.assertRaises(TargetError, msg=command):
                self.session.execute(command)

    def test_help_hides_them(self):
        text = "\n".join(self.session.execute("help"))
        for name in ("core ", "warp ", "lane ", "warps", "lanes"):
            self.assertNotIn(name, text)

    def test_soft_reset_is_not_supported(self):
        with self.assertRaises(TargetError):
            self.session.execute("reset gpu")

    def test_status_line_has_no_gpu_summary(self):
        self.assertNotIn("│", self.session.status_line())


class TuiTest(unittest.TestCase):
    def pilot(self, session, body):
        import asyncio

        from tools.debug_tui import build_app

        app = build_app(session)

        async def go():
            async with app.run_test(size=(180, 50)) as pilot:
                await body(app, pilot)

        asyncio.run(go())

    def test_gpu_panels_and_keys(self):
        session = launched()
        seen = {}

        async def body(app, pilot):
            from textual.widgets import Static

            await pilot.pause()
            warps = app.query_one("#warps", Static)
            registers = app.query_one("#registers")
            seen["warps"] = str(warps.renderable)
            seen["gpu_title"] = registers.border_title
            seen["gpu_values"] = str(
                app.query_one("#register-values", Static).renderable)
            await pilot.press("g")
            await pilot.pause()
            seen["cpu_title"] = registers.border_title
            seen["core"] = session.target.core()
            await pilot.press("w")
            await pilot.pause()
            seen["after_w"] = (session.target.core(),
                               [r.number for r in session.target.warp_rows()
                                if r.focused])
            await pilot.press("l")
            await pilot.pause()
            seen["lane"] = session.target.name

        self.pilot(session, body)
        self.assertIn("READY", seen["warps"])
        self.assertIn("▶", seen["warps"])
        self.assertIn("GPU", seen["gpu_title"])
        self.assertIn("L7", seen["gpu_values"])
        self.assertEqual(seen["cpu_title"], "registros CPU")
        self.assertEqual(seen["core"], "cpu")
        self.assertEqual(seen["after_w"], ("gpu", [1]))
        self.assertIn("l1", seen["lane"])

    def test_r_runs_a_round_and_t_a_scheduler_step(self):
        session = launched()
        seen = {}

        async def body(app, pilot):
            await pilot.press("r")
            await pilot.pause()
            warps = session.target.system.gpu.warps
            seen["round"] = [w.instructions_executed for w in warps[:2]]
            await pilot.press("t")
            await pilot.pause()
            seen["sched"] = [r.number for r in session.target.warp_rows()
                             if r.focused]

        self.pilot(session, body)
        self.assertEqual(seen["round"], [1, 1])
        self.assertEqual(seen["sched"], [0])

    def test_stepping_highlights_the_lane_cells_that_changed(self):
        session = launched()
        seen = {}

        async def body(app, pilot):
            await pilot.press("s")
            await pilot.pause()
            seen["cells"] = set(app.changed_cells)
            await pilot.press("g")
            await pilot.pause()
            seen["registers"] = set(app.changed_registers)

        self.pilot(session, body)
        # GETTID R1: las ocho lanes escriben R1 (la lane 0 vale cero y no cambia).
        self.assertEqual(seen["cells"], {(lane, 1) for lane in range(1, 8)})
        # Cambiar de núcleo no compara registros de sitios distintos.
        self.assertEqual(seen["registers"], set())

    def test_single_core_tui_has_no_gpu_panel(self):
        from textual.css.query import NoMatches

        session = DebugSession(SimTarget(CPU(64 * 1024)))
        seen = {}

        async def body(app, pilot):
            await pilot.pause()
            try:
                app.query_one("#warps")
                seen["warps"] = True
            except NoMatches:
                seen["warps"] = False
            seen["title"] = app.query_one("#registers").border_title

        self.pilot(session, body)
        self.assertFalse(seen["warps"])
        self.assertEqual(seen["title"], "registros")

    def test_watch_panel_only_exists_while_there_are_watches(self):
        session = build(KERNEL_STORE)
        seen = {}

        async def body(app, pilot):
            from textual.widgets import Static

            panel = app.query_one("#watches-panel", Static)
            memory = app.query_one("#memory")
            await pilot.pause()
            seen["hidden"] = panel.display
            seen["wide_before"] = memory.region.width
            app.dispatch("watch out")
            await pilot.pause()
            seen["shown"] = panel.display
            seen["text"] = str(panel.renderable)
            seen["wide_after"] = memory.region.width
            app.dispatch("unwatch all")
            await pilot.pause()
            seen["hidden_again"] = panel.display

        self.pilot(session, body)
        self.assertFalse(seen["hidden"])
        self.assertTrue(seen["shown"])
        self.assertIn("out", seen["text"])
        self.assertIn("sin cambios", seen["text"])
        self.assertLess(seen["wide_after"], seen["wide_before"])
        self.assertFalse(seen["hidden_again"])

    def test_watch_panel_shows_the_writer_and_highlights_the_change(self):
        session = build(KERNEL_STORE)
        seen = {}

        async def body(app, pilot):
            from textual.widgets import Static

            app.dispatch("watch out")
            app.dispatch("run")
            await pilot.pause()
            seen["text"] = str(app.query_one("#watches-panel", Static)
                               .renderable)
            app.dispatch("regs")
            await pilot.pause()
            seen["later"] = str(app.query_one("#watches-panel", Static)
                                .renderable)

        self.pilot(session, body)
        self.assertIn("[bold yellow]out  0x00000007", seen["text"])
        self.assertIn("← 0x00000000  GPU warp 0, PC=", seen["text"])
        self.assertNotIn("bold yellow", seen["later"])

    def test_f1_opens_the_help_window_and_escape_closes_it(self):
        session = launched()
        seen = {}

        async def body(app, pilot):
            await pilot.pause()
            seen["before"] = type(app.screen).__name__
            await pilot.press("f1")
            await pilot.pause()
            seen["open"] = type(app.screen).__name__
            await pilot.press("escape")
            await pilot.pause()
            seen["closed"] = type(app.screen).__name__
            # `q` dentro de la ayuda cierra la ayuda, no sale del depurador
            await pilot.press("f1", "q")
            await pilot.pause()
            seen["q"] = type(app.screen).__name__

        self.pilot(session, body)
        self.assertEqual(seen["open"], "HelpScreen")
        self.assertEqual(seen["before"], seen["closed"])
        self.assertEqual(seen["q"], seen["before"])

    def test_typing_help_opens_the_window_instead_of_printing_the_list(self):
        session = launched()
        seen = {}

        async def body(app, pilot):
            from textual.widgets import Input, RichLog

            prompt = app.query_one("#prompt", Input)
            prompt.focus()
            prompt.value = "help"
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            seen["screen"] = type(app.screen).__name__
            seen["log"] = len(app.query_one("#console", RichLog).lines)

        self.pilot(session, body)
        self.assertEqual(seen["screen"], "HelpScreen")
        self.assertLess(seen["log"], 8)         # no se volcó la lista de comandos

    def test_question_mark_is_text_while_typing(self):
        session = launched()
        seen = {}

        async def body(app, pilot):
            from textual.widgets import Input

            app.query_one("#prompt", Input).focus()
            await pilot.pause()
            await pilot.press("question_mark")
            await pilot.pause()
            seen["typing"] = type(app.screen).__name__
            app.set_focus(None)
            await pilot.press("question_mark")
            await pilot.pause()
            seen["panel"] = type(app.screen).__name__

        self.pilot(session, body)
        self.assertNotEqual(seen["typing"], "HelpScreen")
        self.assertEqual(seen["panel"], "HelpScreen")

    def test_help_text_follows_what_the_target_has(self):
        from tools.debug_tui import _help_markup

        bindings = [("s", "command('step')", "paso"), ("g", "command('core')", "CPU/GPU")]
        gpu = _help_markup(launched(), bindings)
        for text in ("CPU + GPU", "round", "sched", "watch", "Teclas",
                     "Colores y marcas", "PC de la CPU"):
            self.assertIn(text, gpu)
        single = _help_markup(DebugSession(SimTarget(CPU(64 * 1024))), bindings)
        self.assertNotIn("CPU + GPU", single)
        self.assertNotIn("round", single)
        self.assertNotIn("PC de la CPU", single)

    def test_help_text_renders_without_errors(self):
        import io

        from rich.console import Console

        from tools.debug_tui import _help_markup

        console = Console(file=io.StringIO(), force_terminal=True, width=100)
        console.print(_help_markup(launched(), [("s", "command('step')", "paso"),
                                                ("f1", "help", "ayuda")]))

    def test_every_command_has_a_help_section(self):
        from tools.debug_core import HELP, HELP_SECTIONS

        sectioned = set().union(*HELP_SECTIONS.values())
        for name, _ in HELP:
            self.assertIn(name.split()[0], sectioned, name)

    def test_lane_markup_renders_without_errors(self):
        import io

        from rich.console import Console

        from tools.debug_tui import _lane_lines, _warp_lines

        session = launched(KERNEL_DIVERGE)
        session.execute("step 5")
        console = Console(file=io.StringIO(), force_terminal=True, width=100)
        console.print(_warp_lines(session))
        console.print(_lane_lines(session, {(0, 1), (7, 3)}))


if __name__ == "__main__":
    unittest.main()
