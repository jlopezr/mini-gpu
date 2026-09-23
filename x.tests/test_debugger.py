"""El depurador entero sin abrir un terminal.

Se prueba `DebugSession` --que es donde está toda la lógica-- contra el
simulador de verdad, y `BoardTarget` contra un cliente de monitor falso. La TUI
no se prueba aquí a propósito: no tiene lógica propia, cada tecla llama al
mismo `execute()` que se prueba abajo.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "2.cpu-sim-func"))

from minicpu_sim import CPU  # noqa: E402
from tools import debug_source  # noqa: E402
from tools.debug_core import (  # noqa: E402
    STOP_BREAKPOINT, STOP_ERROR, STOP_HALT, STOP_LIMIT, STOP_STEPPED,
    CommandError, DebugSession,
)
from tools.debug_target import SimTarget, TargetError, TargetState  # noqa: E402

PROGRAM = """
inicio:
    MOVI R1, 3
    MOVI R2, 0
bucle:
    ADDI R2, R2, 5
    ADDI R1, R1, -1
    BNE R1, R0, bucle
fin:
    HALT
"""


def build(source_text: str = PROGRAM, tmp: Path | None = None) -> DebugSession:
    """Una sesión con el programa ensamblado y su mapa de fuente."""
    sys.path.insert(0, str(ROOT / "1.isa"))
    from mini_asm import assemble_bytes

    cpu = CPU(64 * 1024)
    cpu.load_program(assemble_bytes(source_text))

    source = debug_source.SourceMap()
    if tmp is not None:
        path = tmp / "programa.asm"
        path.write_text(source_text, encoding="utf-8")
        source = debug_source.from_program(path)
    return DebugSession(SimTarget(cpu), source)


class SourceMapTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = Path(tempfile.mkdtemp())
        self.session = build(tmp=self.tmp)

    def test_maps_pc_to_source_text(self):
        self.assertEqual(self.session.source.text[0], "MOVI R1, 3")

    def test_labels_resolve_both_ways(self):
        source = self.session.source
        self.assertEqual(source.resolve("bucle"), 8)
        self.assertEqual(source.symbol(8), "bucle")
        self.assertEqual(source.nearest(12), ("bucle", 4))

    def test_equates_are_not_positions(self):
        session = build(".equ ANCHO, 320\ninicio:\n    HALT\n", tmp=self.tmp)
        self.assertNotIn("ANCHO", session.source.labels)

    def test_binary_program_has_no_map(self):
        path = self.tmp / "programa.bin"
        path.write_bytes(b"\x00" * 16)
        self.assertTrue(debug_source.from_program(path).empty)

    def test_unreadable_source_degrades_to_empty_map(self):
        # Sin fuente se ven palabras en vez de texto, que es peor pero sirve;
        # lo que no puede es tumbar el depurador con el programa ya cargado.
        self.assertTrue(debug_source.from_program(self.tmp / "no-existe.asm").empty)


class SteppingTest(unittest.TestCase):
    def setUp(self):
        self.session = build()

    def test_step_advances_one_instruction(self):
        stop = self.session.step()
        self.assertEqual(stop.kind, STOP_STEPPED)
        self.assertEqual(self.session.target.state().pc, 4)
        self.assertEqual(self.session.target.registers()[1], 3)

    def test_step_count(self):
        self.session.step(3)
        self.assertEqual(self.session.target.state().instructions, 3)

    def test_run_reaches_halt(self):
        stop = self.session.resume()
        self.assertEqual(stop.kind, STOP_HALT)
        self.assertTrue(self.session.target.state().halted)
        self.assertEqual(self.session.target.registers()[2], 15)

    def test_run_stops_at_breakpoint(self):
        self.session.breakpoints.add(8)
        stop = self.session.resume()
        self.assertEqual(stop.kind, STOP_BREAKPOINT)
        self.assertEqual(self.session.target.state().pc, 8)

    def test_breakpoint_at_current_pc_does_not_block_run(self):
        self.session.breakpoints.add(8)
        self.session.resume()
        stop = self.session.resume()
        self.assertEqual(stop.kind, STOP_BREAKPOINT)
        # Ha dado la vuelta al bucle, no se ha quedado clavado.
        self.assertGreater(stop.executed, 0)

    def test_step_ignores_breakpoints(self):
        self.session.breakpoints.add(4)
        stop = self.session.step(3)
        self.assertEqual(stop.kind, STOP_STEPPED)
        self.assertEqual(stop.executed, 3)

    def test_run_limit_stops_a_runaway_program(self):
        session = build("bucle:\n    BRA bucle\n")
        stop = session.resume(max_instructions=50)
        self.assertEqual(stop.kind, STOP_LIMIT)
        self.assertEqual(stop.executed, 50)

    def test_error_is_reported_as_error(self):
        session = build("    .word 0xFFFFFFFF\n")
        stop = session.resume()
        self.assertEqual(stop.kind, STOP_ERROR)
        self.assertIn("ERROR", session.describe_stop(stop))

    def test_stepping_a_halted_machine_says_so(self):
        self.session.resume()
        stop = self.session.step()
        self.assertEqual(stop.executed, 0)
        self.assertIn("ya estaba parada", self.session.describe_stop(stop))

    def test_step_over_skips_the_call(self):
        session = build(
            "    JAL R31, sub\n    HALT\nsub:\n    MOVI R3, 7\n    JR R31\n")
        stop = session.step_over()
        self.assertEqual(session.target.state().pc, 4)
        self.assertEqual(session.target.registers()[3], 7)
        self.assertGreater(stop.executed, 1)

    def test_step_over_on_a_normal_instruction_is_a_step(self):
        self.session.step_over()
        self.assertEqual(self.session.target.state().instructions, 1)


class CommandTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.session = build(tmp=Path(tempfile.mkdtemp()))

    def test_break_accepts_a_label(self):
        self.session.execute("break bucle")
        self.assertIn(8, self.session.breakpoints)

    def test_until_runs_to_a_label(self):
        self.session.execute("until fin")
        self.assertEqual(self.session.target.state().pc,
                         self.session.source.resolve("fin"))

    def test_delete_all(self):
        self.session.execute("break bucle")
        self.session.execute("delete")
        self.assertFalse(self.session.breakpoints)

    def test_set_register(self):
        self.session.execute("set R5 0x1234")
        self.assertEqual(self.session.target.registers()[5], 0x1234)

    def test_set_register_rejects_r0(self):
        with self.assertRaises(TargetError):
            self.session.execute("set R0 1")

    def test_set_pc_accepts_a_label(self):
        self.session.execute("set pc fin")
        self.assertEqual(self.session.target.state().pc,
                         self.session.source.resolve("fin"))

    def test_write_and_read_memory(self):
        self.session.execute("write 0x1000 0xDEADBEEF")
        lines = self.session.execute("mem 0x1000 16")
        self.assertIn("EF BE AD DE", lines[0])

    def test_mem_moves_the_panel_window(self):
        self.session.execute("mem 0x2000 32")
        self.assertEqual(self.session.memory_address, 0x2000)
        self.assertEqual(len(self.session.memory_rows()), 2)

    def test_unreadable_region_is_a_command_error(self):
        with self.assertRaises(CommandError):
            self.session.execute("mem 0xF0000000 16")

    def test_unknown_command(self):
        with self.assertRaises(CommandError):
            self.session.execute("pasitos")

    def test_bad_register_name(self):
        with self.assertRaises(CommandError):
            self.session.execute("set R99 1")

    def test_empty_line_does_nothing(self):
        self.assertEqual(self.session.execute("   "), [])

    def test_quit_sets_the_flag(self):
        self.session.execute("quit")
        self.assertTrue(self.session.quit)

    def test_help_lists_every_documented_command(self):
        from tools.debug_core import HELP, _COMMANDS

        for entry, _ in HELP:
            self.assertIn(entry.split()[0], _COMMANDS)


class ViewTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.session = build(tmp=Path(tempfile.mkdtemp()))

    def test_listing_marks_the_pc_and_the_breakpoints(self):
        self.session.execute("break bucle")
        rows = self.session.listing()
        self.assertEqual([row.address for row in rows if row.is_pc], [0])
        self.assertEqual([row.address for row in rows if row.has_breakpoint],
                         [8])

    def test_listing_uses_source_text(self):
        row = next(row for row in self.session.listing() if row.address == 0)
        self.assertEqual(row.text, "MOVI R1, 3")

    def test_listing_without_a_map_falls_back_to_words(self):
        session = build()
        row = next(row for row in session.listing() if row.address == 0)
        self.assertTrue(row.text.startswith(".word 0x"))

    def test_status_line_names_the_nearest_label(self):
        self.session.execute("until bucle")
        self.session.execute("step")
        self.assertIn("<bucle+4>", self.session.status_line())

    def test_memory_rows_are_aligned_to_sixteen(self):
        rows = self.session.memory_rows(0x1004, 32)
        self.assertEqual(rows[0][0], 0x1000)

    def test_registers_are_listed_whole(self):
        self.assertEqual(len(self.session.register_rows()), 32)


class FakeProcess:
    """Una ventana que no se abre, para que la suite no pinte nada."""

    def __init__(self):
        self.lines = []
        self.alive = True
        self.stdin = self

    def write(self, text):
        self.lines.append(text)

    def flush(self):
        pass

    def close(self):
        self.alive = False

    def poll(self):
        return None if self.alive else 0

    def wait(self, timeout=None):
        return 0

    @property
    def payloads(self):
        import json

        return [json.loads(line) for line in self.lines]


class VideoTest(unittest.TestCase):
    """La ventana de framebuffer, sin abrir ninguna ventana."""

    def build(self, video=True):
        from tools.sim_devices import VideoDevice

        cpu = CPU(4 * 1024 * 1024,
                  video=VideoDevice(frame_instructions=1000) if video else None)
        session = DebugSession(SimTarget(cpu))
        self.process = FakeProcess()
        session.video._spawn = lambda: setattr(
            session.video, "process", self.process)
        return cpu, session

    def test_no_video_device_says_so(self):
        _, session = self.build(video=False)
        with self.assertRaises(TargetError):
            session.execute("fb")

    def test_layout_follows_the_registers(self):
        from tools.sim_devices import VideoDevice

        cpu, session = self.build()
        cpu.video.write(VideoDevice.FB_FRONT, 0x1000)
        cpu.video.write(VideoDevice.FB_BACK, 0x2000)
        layout = session.target.video_layout()
        self.assertEqual((layout.fb_front, layout.fb_back), (0x1000, 0x2000))
        self.assertEqual(layout.frame_bytes, 320 * 240 * 2)

    def test_show_sends_the_framebuffer(self):
        from tools.sim_devices import VideoDevice

        cpu, session = self.build()
        cpu.video.write(VideoDevice.FB_FRONT, 0x10000)
        cpu.memory[0x10000:0x10004] = b"\x1f\x00\xe0\x07"
        session.execute("fb")
        payload = self.process.payloads[-1]
        self.assertIsNone(payload["back"])
        data = Path(payload["front"]).read_bytes()
        self.assertEqual(len(data), 320 * 240 * 2)
        self.assertEqual(data[:4], b"\x1f\x00\xe0\x07")

    def test_both_buffers(self):
        _, session = self.build()
        session.execute("fb both")
        payload = self.process.payloads[-1]
        self.assertTrue(payload["front"] and payload["back"])

    def test_window_refreshes_after_every_command(self):
        _, session = self.build()
        session.execute("fb")
        antes = len(self.process.lines)
        session.execute("step")
        self.assertGreater(len(self.process.lines), antes)

    def test_closing_the_window_stops_the_refresh(self):
        _, session = self.build()
        session.execute("fb")
        self.process.alive = False
        session.execute("step")
        self.assertFalse(session.video.showing)

    def test_fb_off(self):
        _, session = self.build()
        session.execute("fb")
        session.execute("fb off")
        self.assertFalse(session.video.open)

    def test_auto_is_off_on_a_slow_target(self):
        from tools.debug_board import BoardTarget
        from tools.debug_video import VideoViewer

        # En placa son ~1,5 s por buffer: refrescar sola sería inusable.
        self.assertFalse(VideoViewer(BoardTarget(FakeClient())).auto)

    def test_auto_toggle(self):
        _, session = self.build()
        session.execute("fb auto off")
        self.assertFalse(session.video.auto)
        with self.assertRaises(CommandError):
            session.execute("fb auto")

    def test_unknown_buffer(self):
        _, session = self.build()
        with self.assertRaises(TargetError):
            session.execute("fb lateral")

    def test_quit_closes_the_window(self):
        _, session = self.build()
        session.execute("fb")
        session.execute("quit")
        self.assertFalse(self.process.alive)


class ColorTest(unittest.TestCase):
    """RGB565 -> RGB888 con replicación de bits altos, como el scanout."""

    def convert(self, *words):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "fb_window", ROOT / "tools" / "fb_window.py")
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        data = b"".join(w.to_bytes(2, "little") for w in words)
        return modulo.rgb_bytes(data)

    def test_white_is_really_white(self):
        # Sin replicar los bits altos saldría 0xF8F8F8, o sea gris.
        self.assertEqual(self.convert(0xFFFF), b"\xff\xff\xff")

    def test_primaries(self):
        self.assertEqual(self.convert(0xF800, 0x07E0, 0x001F),
                         b"\xff\x00\x00\x00\xff\x00\x00\x00\xff")

    def test_black(self):
        self.assertEqual(self.convert(0x0000), b"\x00\x00\x00")


class FakeClient:
    """Lo justo de `MonitorClient` para probar `BoardTarget` sin placa."""

    def __init__(self, mmio=None):
        self.regs = [0] * 32
        self.pc = 0
        self.halted = False
        self.steps = 0
        self.ran = False
        self.memory = bytearray(256)
        # Palabras de MMIO que ESTA placa responde; el resto "no existe".
        self.mmio = mmio if mmio is not None else {}

    def read_word(self, address):
        if address not in self.mmio:
            raise RuntimeError("The FPGA rejected the command")
        return self.mmio[address]

    class _Status:
        def __init__(self, pc, halted):
            self.pc, self.halted = pc, halted
            self.error, self.error_code = False, 0

    def get_status(self):
        return self._Status(self.pc, self.halted)

    def read_register(self, index):
        return self.regs[index]

    def read_memory(self, address, length):
        return bytes(self.memory[address:address + length])

    def write_word(self, address, value):
        self.memory[address:address + 4] = value.to_bytes(4, "little")

    def step_cpu(self):
        self.steps += 1
        self.pc += 4

    def run_cpu(self):
        self.ran = True
        self.halted = True

    def halt_cpu(self):
        self.halted = True

    def reset_cpu(self):
        self.pc, self.halted = 0, False


class BoardTargetTest(unittest.TestCase):
    def setUp(self):
        from tools.debug_board import BoardTarget

        self.client = FakeClient()
        self.session = DebugSession(BoardTarget(self.client, "placa falsa"))

    def test_state_comes_from_the_monitor(self):
        self.client.pc = 0x40
        self.assertEqual(self.session.target.state().pc, 0x40)

    def test_step_sends_one_step(self):
        self.session.step(3)
        self.assertEqual(self.client.steps, 3)

    def test_run_without_breakpoints_uses_free_run(self):
        self.session.resume()
        self.assertTrue(self.client.ran)
        self.assertEqual(self.client.steps, 0)

    def test_run_with_a_breakpoint_steps_instead(self):
        self.session.breakpoints.add(0x08)
        stop = self.session.resume()
        self.assertEqual(stop.kind, STOP_BREAKPOINT)
        self.assertFalse(self.client.ran)
        self.assertEqual(self.client.steps, 2)

    def test_writing_a_register_is_refused_not_faked(self):
        # Hoy el monitor no sabe escribir registros (punto 11 del TODO). Lo que
        # importa es que lo diga, no que escriba en un sitio equivocado.
        with self.assertRaises(TargetError):
            self.session.execute("set R5 1")

    def test_memory_write_is_supported(self):
        self.session.execute("write 0x10 0xCAFEBABE")
        self.assertEqual(self.client.memory[0x10:0x14],
                         bytearray(b"\xbe\xba\xfe\xca"))

    def test_serial_failures_become_target_errors(self):
        def boom():
            raise OSError("cable desconectado")

        self.client.get_status = boom
        with self.assertRaises(TargetError):
            self.session.target.state()


@unittest.skipIf(importlib.util.find_spec("textual") is None,
                 "sin textual instalado")
class TuiTest(unittest.TestCase):
    """La TUI se pilota sin terminal con `App.run_test()`.

    No se comprueba cómo queda pintada --eso cambia cada vez que se mueve un
    panel-- sino que las teclas llegan a la sesión y que los paneles se
    refrescan con lo que la sesión dice.
    """

    def setUp(self):
        import tempfile

        self.session = build(tmp=Path(tempfile.mkdtemp()))

    def pilot(self, body):
        import asyncio

        from tools.debug_tui import build_app

        app = build_app(self.session)

        async def go():
            async with app.run_test() as pilot:
                await body(app, pilot)

        asyncio.run(go())

    def test_keys_drive_the_session(self):
        async def body(app, pilot):
            await pilot.press("s")
            await pilot.press("s")
            await pilot.pause()

        self.pilot(body)
        self.assertEqual(self.session.target.state().instructions, 2)

    def test_typed_command_runs(self):
        async def body(app, pilot):
            from textual.widgets import Input

            prompt = app.query_one("#prompt", Input)
            prompt.focus()
            prompt.value = "until fin"
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

        self.pilot(body)
        self.assertEqual(self.session.target.state().pc,
                         self.session.source.resolve("fin"))

    def test_keys_do_not_fire_while_typing(self):
        async def body(app, pilot):
            from textual.widgets import Input

            app.query_one("#prompt", Input).focus()
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()

        self.pilot(body)
        self.assertEqual(self.session.target.state().instructions, 0)

    def test_panels_show_the_state(self):
        captured = {}

        async def body(app, pilot):
            from textual.widgets import Static

            await pilot.press("s")
            await pilot.pause()
            captured["status"] = app.sub_title
            captured["registers"] = str(
                app.query_one("#registers", Static).renderable)

        self.pilot(body)
        self.assertIn("PC=0x00000004", captured["status"])
        self.assertIn("R1", captured["registers"])

    def test_source_brackets_are_not_markup(self):
        from tools.debug_tui import _escape

        self.assertEqual(_escape("LOAD R1, [R2]"), "LOAD R1, \\[R2]")


class BoardVideoTest(unittest.TestCase):
    """Las bases de vídeo se descubren; v1 y v2 no están en el mismo sitio."""

    def target(self, mmio):
        from tools.debug_board import BoardTarget

        return BoardTarget(FakeClient(mmio), "placa falsa")

    def test_video_is_found_through_sys_id(self):
        from tools.mmio_map import (
            MMIO_DEV_VIDEO_BIT, MMIO_MAGIC_VALUE, MMIO_SYSTEM_BASE,
            MMIO_SYSTEM_DEVICES_OFF, MMIO_VIDEO_BASE,
            MMIO_VIDEO_FB_BACK_OFF, MMIO_VIDEO_FB_FRONT_OFF,
        )

        layout = self.target({
            MMIO_SYSTEM_BASE: MMIO_MAGIC_VALUE,
            MMIO_SYSTEM_BASE + MMIO_SYSTEM_DEVICES_OFF: 1 << MMIO_DEV_VIDEO_BIT,
            MMIO_VIDEO_BASE + MMIO_VIDEO_FB_FRONT_OFF: 0x0100_0000,
            MMIO_VIDEO_BASE + MMIO_VIDEO_FB_BACK_OFF: 0x0102_5800,
        }).video_layout()
        self.assertEqual((layout.fb_front, layout.fb_back),
                         (0x0100_0000, 0x0102_5800))

    def test_without_the_magic_it_does_not_guess(self):
        # 0x80000000 es SYSTEM en el mapa v2. Una placa que no se identifica
        # no autoriza a leer ahí como si fuera un FB_FRONT del mapa viejo:
        # devolvería el magic de SYS_ID disfrazado de dirección.
        from tools.mmio_map import MMIO_SYSTEM_BASE

        self.assertIsNone(self.target({
            MMIO_SYSTEM_BASE: 0xDEADBEEF,
            MMIO_SYSTEM_BASE + 4: 0x0102_5800,
        }).video_layout())

    def test_a_board_without_video_says_none(self):
        from tools.mmio_map import (
            MMIO_MAGIC_VALUE, MMIO_SYSTEM_BASE, MMIO_SYSTEM_DEVICES_OFF,
        )

        self.assertIsNone(self.target({
            MMIO_SYSTEM_BASE: MMIO_MAGIC_VALUE,
            MMIO_SYSTEM_BASE + MMIO_SYSTEM_DEVICES_OFF: 0,
        }).video_layout())

    def test_a_board_that_answers_nothing_says_none(self):
        self.assertIsNone(self.target({}).video_layout())


class TargetContractTest(unittest.TestCase):
    """Lo que las dos implementaciones tienen que cumplir por igual."""

    def targets(self):
        from tools.debug_board import BoardTarget

        cpu = CPU(4096)
        return [SimTarget(cpu), BoardTarget(FakeClient(), "placa falsa")]

    def test_state_is_a_target_state(self):
        for target in self.targets():
            self.assertIsInstance(target.state(), TargetState)

    def test_thirty_two_registers(self):
        for target in self.targets():
            self.assertEqual(len(target.registers()), 32)

    def test_unsupported_capabilities_raise_target_error(self):
        for target in self.targets():
            for capability in ("write-register", "write-pc", "free-run"):
                if not target.supports(capability):
                    with self.assertRaises(TargetError):
                        target.require(capability)


if __name__ == "__main__":
    unittest.main()
