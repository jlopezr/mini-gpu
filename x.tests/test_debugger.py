"""El depurador entero sin abrir un terminal.

Se prueba `DebugSession` --que es donde está toda la lógica-- contra el
simulador de verdad, y `BoardTarget` contra un cliente de monitor falso. La TUI
no se prueba aquí a propósito: no tiene lógica propia, cada tecla llama al
mismo `execute()` que se prueba abajo.
"""
import importlib.util
import base64
import io
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "2.cpu-sim-func"))

from minicpu_sim import CPU  # noqa: E402
from tools import debug_source  # noqa: E402
from tools.debug_core import (  # noqa: E402
    STOP_BREAKPOINT, STOP_ERROR, STOP_FINISHED, STOP_HALT, STOP_INTERRUPTED,
    STOP_LIMIT, STOP_STEPPED, STOP_SWAP,
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


class PeripheralWarningTest(unittest.TestCase):
    def test_video_source_without_device_warns(self):
        import argparse
        import tempfile

        from tools import sim_peripherals

        path = Path(tempfile.mkdtemp()) / "video.asm"
        path.write_text("STORE R1, R2, MMIO_VIDEO_SWAP_OFF\n",
                        encoding="utf-8")
        args = argparse.Namespace(
            video=False, frame_output=None, halt_after_swaps=None)
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            warned = sim_peripherals.warn_missing_video(path, args)
        self.assertTrue(warned)
        self.assertIn("--video", stderr.getvalue())

    def test_video_source_with_device_does_not_warn(self):
        import argparse
        import tempfile

        from tools import sim_peripherals

        path = Path(tempfile.mkdtemp()) / "video.asm"
        path.write_text("LOAD R1, R2, MMIO_VIDEO_STATUS_OFF\n",
                        encoding="utf-8")
        args = argparse.Namespace(
            video=True, frame_output=None, halt_after_swaps=None)
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            warned = sim_peripherals.warn_missing_video(path, args)
        self.assertFalse(warned)
        self.assertEqual(stderr.getvalue(), "")

    def test_mini_dbg_no_longer_accepts_fb_layout(self):
        from tools.debug_cli import build_parser

        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit):
            build_parser().parse_args(["program.asm", "--fb-layout"])
        self.assertIn("unrecognized arguments: --fb-layout", stderr.getvalue())


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

    def test_li_reserves_two_rows_and_expands_while_executing(self):
        session = build("LI R1, 0x12345678\nHALT\n", tmp=self.tmp)

        rows = session.listing()
        self.assertEqual([row.address for row in rows[:3]], [0, 4, 8])
        self.assertEqual(
            rows[0].text,
            "LI R1, 0x12345678                ──────▶ MOVHI R1, 0x1234")
        self.assertEqual(
            rows[1].text,
            "  (continuacion)                 └─────▶ ORI R1, R1, 0x5678")

        session.step()
        rows = session.listing()
        self.assertEqual(
            rows[0].text,
            "LI R1, 0x12345678                ──────▶ MOVHI R1, 0x1234")
        self.assertEqual(
            rows[1].text,
            "  (continuacion)                 └─────▶ ORI R1, R1, 0x5678")

        session.step()
        rows = session.listing()
        self.assertEqual(rows[0].text, "LI R1, 0x12345678")
        self.assertEqual(rows[1].text, "  (continuacion)")

    def test_symbolic_memory_offset_has_effective_address(self):
        session = build(
            ".equ PORT_OFF, 12\nMOVI R2, 0x1000\n"
            "STORE R1, R2, PORT_OFF\nHALT\n", tmp=self.tmp)
        session.step()
        self.assertEqual(
            session.source.memory_annotation(4, session.target.registers()),
            "; +12 [0x0000100C]")

    def test_negative_symbolic_memory_offset(self):
        session = build(
            ".equ PREV, -4\nMOVI R2, 0x1000\n"
            "LOAD R1, R2, PREV\nHALT\n", tmp=self.tmp)
        session.step()
        self.assertEqual(
            session.source.memory_annotation(4, session.target.registers()),
            "; -4 [0x00000FFC]")

    def test_direct_jump_has_code_target_annotation(self):
        session = build(
            "BRA destino\nMOVI R1, 1\ndestino:\nHALT\n", tmp=self.tmp)
        self.assertEqual(
            session.source.target_annotation(0, session.target.registers()),
            ("; → [0x00000008]", "code", 8))

    def test_indirect_jump_uses_current_base_register(self):
        session = build(
            "MOVI R2, 0x20\nJALR R31, R2, 2\nHALT\n", tmp=self.tmp)
        session.step()
        self.assertEqual(
            session.source.target_annotation(4, session.target.registers()),
            ("; → [0x00000028]", "code", 0x28))


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

    def test_run_command_accepts_an_explicit_limit(self):
        session = build("bucle:\n    BRA bucle\n")
        self.assertIn("limite de 50", session.execute("run 50")[0])

    def test_run_can_be_interrupted(self):
        session = build("bucle:\n    BRA bucle\n")
        session.interrupt()
        stop = session.resume()
        self.assertEqual(stop.kind, STOP_INTERRUPTED)

    def test_regs_accepts_register_with_or_without_r(self):
        self.session.step()
        self.assertEqual(self.session.execute("regs R1"),
                         self.session.execute("regs 1"))

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

    def test_finish_ignores_returns_from_nested_calls(self):
        session = build(
            "    JAL R31, outer\n"
            "    HALT\n"
            "outer:\n"
            "    ADDI R20, R31, 0\n"
            "    JAL R31, inner\n"
            "    ADDI R31, R20, 0\n"
            "    JR R31\n"
            "inner:\n"
            "    MOVI R3, 7\n"
            "    JR R31\n")
        session.step()
        stop = session.finish()
        self.assertEqual(stop.kind, STOP_FINISHED)
        self.assertEqual(session.target.state().pc, 4)
        self.assertEqual(session.target.registers()[3], 7)


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

    def test_frame_stops_after_swap_is_completed(self):
        from tools.sim_devices import VideoDevice

        cpu, session = self.build()
        cpu.video.frame_instructions = 3
        cpu.video.write(VideoDevice.SWAP, 1)
        stop = session.run_to_next_swap()
        self.assertEqual(stop.kind, STOP_SWAP)
        self.assertEqual(stop.executed, 3)
        self.assertEqual(cpu.video.swap_count, 1)
        self.assertFalse(cpu.video.swap_pending)

    def test_frame_without_video_is_rejected(self):
        _, session = self.build(video=False)
        with self.assertRaises(TargetError):
            session.execute("frame")

    def test_help_only_lists_available_video_commands(self):
        _, without_video = self.build(video=False)
        help_text = "\n".join(without_video.execute("help"))
        self.assertNotIn("fb [X]", help_text)
        self.assertNotIn("frame", help_text)

        _, with_video = self.build(video=True)
        help_text = "\n".join(with_video.execute("help"))
        self.assertIn("fb [X]", help_text)
        self.assertIn("frame", help_text)

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
        data = base64.b64decode(payload["front"])
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

    def test_successive_frames_are_sent_in_memory(self):
        cpu, session = self.build()
        session.execute("fb")
        first = self.process.payloads[-1]["front"]
        cpu.memory[0] = 1
        session.execute("step")
        second = self.process.payloads[-1]["front"]
        self.assertNotEqual(first, second)
        self.assertEqual(len(base64.b64decode(second)), 320 * 240 * 2)

    def test_continue_refreshes_when_a_swap_completes(self):
        from tools.sim_devices import VideoDevice

        cpu, session = self.build()
        cpu.video.frame_instructions = 3
        session.execute("fb")
        before = sum("front" in payload for payload in self.process.payloads)
        cpu.video.write(VideoDevice.SWAP, 1)
        session.resume(max_instructions=5)
        self.assertEqual(cpu.video.swap_count, 1)
        after = sum("front" in payload for payload in self.process.payloads)
        self.assertEqual(after, before + 1)

    def test_continue_does_not_refresh_frames_with_auto_off(self):
        from tools.sim_devices import VideoDevice

        cpu, session = self.build()
        cpu.video.frame_instructions = 3
        session.execute("fb")
        session.video.auto = False
        before = sum("front" in payload for payload in self.process.payloads)
        cpu.video.write(VideoDevice.SWAP, 1)
        session.resume(max_instructions=5)
        after = sum("front" in payload for payload in self.process.payloads)
        self.assertEqual(after, before)

    def test_continue_updates_title_without_sending_a_new_frame(self):
        _, session = self.build()
        session.execute("fb")
        before = len(self.process.payloads)
        session.resume(max_instructions=2)
        new_payloads = self.process.payloads[before:]
        self.assertTrue(any(set(payload) == {"title"}
                            for payload in new_payloads))

    def test_escape_event_interrupts_without_closing_video(self):
        _, session = self.build()
        session.execute("fb")
        session.video._handle_event('{"event": "interrupt"}')
        self.assertTrue(session._interrupt.is_set())
        self.assertTrue(session.video.open)

    def test_key_event_is_forwarded_without_closing_video(self):
        _, session = self.build()
        session.execute("fb")
        keys = []
        session.video.on_key = keys.append
        session.video._handle_event('{"event": "key", "key": "s"}')
        self.assertEqual(keys, ["s"])
        self.assertTrue(session.video.open)

    def test_video_errors_are_forwarded_to_the_debugger(self):
        _, session = self.build()
        errors = []
        session.video.on_error = errors.append
        session.video._handle_event(
            '{"event": "error", "message": "not enough image data"}')
        self.assertEqual(errors, ["not enough image data"])

    def test_non_json_child_stderr_is_forwarded_as_an_error(self):
        _, session = self.build()
        errors = []
        session.video.on_error = errors.append
        session.video._handle_event("Pillow explotó\n")
        self.assertEqual(errors, ["Pillow explotó"])

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

    def test_slash_searches_in_the_focused_code_panel(self):
        async def body(app, pilot):
            from textual.widgets import Input

            await pilot.click("#code", offset=(1, 1))
            await pilot.press("/")
            await pilot.pause()
            prompt = app.query_one("#prompt", Input)
            self.assertIs(app.focused, prompt)
            prompt.value = "bucle"
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app.code_center,
                             self.session.source.resolve("bucle"))
            self.assertEqual(app.focused.id, "code")

        self.pilot(body)

    def test_a_repeats_the_last_search(self):
        async def body(app, pilot):
            from textual.widgets import Input

            await pilot.click("#code", offset=(1, 1))
            await pilot.press("/")
            prompt = app.query_one("#prompt", Input)
            prompt.value = "ADDI"
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app.code_center, 8)

            await pilot.press("a")
            await pilot.pause()
            self.assertEqual(app.code_center, 12)

        self.pilot(body)

    def test_video_keys_can_type_a_code_search(self):
        async def body(app, pilot):
            await pilot.click("#code", offset=(1, 1))
            app.action_video_key("/")
            for key in "bucle":
                app.action_video_key(key)
            app.action_video_key("Return")
            await pilot.pause()
            self.assertEqual(app.code_center,
                             self.session.source.resolve("bucle"))

        self.pilot(body)

    def test_footer_bindings_follow_capabilities_and_focused_panel(self):
        async def body(app, pilot):
            self.assertNotIn("v", app._bindings.key_to_bindings)
            self.assertNotIn("f", app._bindings.key_to_bindings)

            await pilot.click("#code", offset=(1, 1))
            code_keys = app.query_one("#code")._bindings.key_to_bindings
            self.assertIn("b", code_keys)
            self.assertIn("p", code_keys)
            self.assertNotIn("h", code_keys)

            await pilot.click("#memory", offset=(1, 1))
            memory_keys = app.query_one("#memory")._bindings.key_to_bindings
            self.assertIn("h", memory_keys)
            self.assertNotIn("b", memory_keys)

            await pilot.click("#registers", offset=(1, 1))
            register_keys = app.query_one(
                "#registers")._bindings.key_to_bindings
            self.assertNotIn("b", register_keys)
            self.assertNotIn("h", register_keys)

        self.pilot(body)

    def test_video_footer_adds_v_and_f(self):
        from tools.debug_tui import build_app
        from tools.sim_devices import VideoDevice

        cpu = CPU(64 * 1024, video=VideoDevice())
        app = build_app(DebugSession(SimTarget(cpu)))
        self.assertIn("v", app._bindings.key_to_bindings)
        self.assertIn("f", app._bindings.key_to_bindings)

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

    def test_click_outside_prompt_restores_debugger_keys(self):
        async def body(app, pilot):
            from textual.widgets import Input

            prompt = app.query_one("#prompt", Input)
            await pilot.click(prompt)
            await pilot.pause()
            self.assertIs(app.focused, prompt)

            await pilot.click("#code", offset=(1, 1))
            await pilot.pause()
            self.assertEqual(app.focused.id, "code")

            await pilot.press("s")
            await pilot.pause()

        self.pilot(body)
        self.assertEqual(self.session.target.state().instructions, 1)

    def test_click_console_focuses_command_prompt(self):
        async def body(app, pilot):
            from textual.widgets import Input

            prompt = app.query_one("#prompt", Input)
            await pilot.click("#console", offset=(2, 1))
            await pilot.pause()
            self.assertIs(app.focused, prompt)

        self.pilot(body)

    def test_code_arrows_scroll_and_p_returns_to_pc(self):
        async def body(app, pilot):
            await pilot.click("#code", offset=(1, 1))
            await pilot.press("down")
            await pilot.pause()
            self.assertEqual(app.code_center, 4)

            await pilot.press("p")
            await pilot.pause()
            self.assertIsNone(app.code_center)

        self.pilot(body)

    def test_b_toggles_breakpoint_on_selected_code_line(self):
        async def body(app, pilot):
            await pilot.click("#code", offset=(1, 1))
            await pilot.press("down")
            await pilot.press("b")
            await pilot.pause()
            self.assertEqual(self.session.breakpoints, {4})

            await pilot.press("b")
            await pilot.pause()
            self.assertEqual(self.session.breakpoints, set())

        self.pilot(body)

    def test_u_runs_until_the_selected_code_line(self):
        async def body(app, pilot):
            await pilot.click("#code", offset=(1, 1))
            await pilot.press("down")
            await pilot.press("down")
            self.assertEqual(app.code_center, 8)
            await pilot.press("u")
            await pilot.pause()
            while app.running:
                await pilot.pause()

        self.pilot(body)
        self.assertEqual(self.session.target.state().pc, 8)

    def test_b_toggles_breakpoint_at_pc_without_code_cursor(self):
        async def body(app, pilot):
            await pilot.press("b")
            await pilot.pause()
            self.assertEqual(self.session.breakpoints, {0})

            await pilot.press("b")
            await pilot.pause()
            self.assertEqual(self.session.breakpoints, set())

        self.pilot(body)

    def test_scrolled_code_marks_selected_instruction(self):
        from tools.debug_tui import _code_view

        rendered, _, visible = _code_view(
            self.session, height=8, center=8)
        selected = next(line for line in rendered.splitlines()
                        if "0x00000008" in line)
        self.assertIn(">", selected)
        self.assertIn(8, visible)

    def test_code_and_memory_links_have_different_colors(self):
        import tempfile

        from tools.debug_tui import _code_view

        tmp = Path(tempfile.mkdtemp())
        code = build("BRA destino\ndestino:\nHALT\n", tmp=tmp)
        memory = build(
            ".equ PORT, 8\nSTORE R1, R2, PORT\nHALT\n", tmp=tmp)
        self.assertIn("[dim cyan]; →", _code_view(code)[0])
        self.assertIn("[dim magenta]; +8", _code_view(memory)[0])

    def test_mmio_memory_links_use_a_third_color(self):
        import tempfile

        from tools.debug_tui import _code_view

        session = build(
            "LI R2, 0x80200000\n"
            ".equ SWAP, 12\n"
            "STORE R1, R2, SWAP\nHALT\n",
            tmp=Path(tempfile.mkdtemp()))
        session.step(2)
        self.assertIn("[dim yellow]; +12 \\[0x8020000C]",
                      _code_view(session)[0])

    def test_execution_returns_code_cursor_to_pc(self):
        async def body(app, pilot):
            await pilot.click("#code", offset=(1, 1))
            await pilot.press("down")
            await pilot.press("s")
            await pilot.pause()
            self.assertIsNone(app.code_center)

        self.pilot(body)

    def test_execution_returns_to_pc_if_it_was_not_visible(self):
        async def body(app, pilot):
            app.code_center = 0x100
            app.code_row_addresses = {0x100}
            app.dispatch("step")
            await pilot.pause()
            self.assertIsNone(app.code_center)

        self.pilot(body)

    def test_click_effective_address_moves_memory_panel(self):
        import asyncio
        import tempfile

        from tools.debug_tui import build_app

        session = build(
            ".equ PORT, 12\nMOVI R2, 0x1000\nSTORE R1, R2, PORT\nHALT\n",
            tmp=Path(tempfile.mkdtemp()))
        session.step()
        app = build_app(session)

        async def go():
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                code = app.query_one("#code")
                row, target = next(
                    (row, target)
                    for row, target in enumerate(app.code_row_targets)
                    if target is not None)
                kind, address, start, _ = target
                self.assertEqual(kind, "memory")
                self.assertEqual(address, 0x100C)
                x = code.content_region.x - code.region.x + start + 1
                y = code.content_region.y - code.region.y + row
                await pilot.click("#code", offset=(x, y))
                await pilot.pause()

        asyncio.run(go())
        self.assertEqual(session.memory_address, 0x1000)

    def test_click_jump_target_moves_code_view(self):
        import asyncio
        import tempfile

        from tools.debug_tui import build_app

        label = "destino_" + "largo_" * 12
        session = build(
            f"BRA {label}\nMOVI R1, 1\n{label}:\nHALT\n",
            tmp=Path(tempfile.mkdtemp()))
        app = build_app(session)

        async def go():
            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                code = app.query_one("#code")
                row, target = next(
                    (row, target)
                    for row, target in enumerate(app.code_row_targets)
                    if target is not None and target[0] == "code")
                _, address, start, _ = target
                self.assertEqual(address, 8)
                x = code.content_region.x - code.region.x + start + 1
                y = code.content_region.y - code.region.y + row
                await pilot.click("#code", offset=(x, y))
                await pilot.pause()

        asyncio.run(go())
        self.assertEqual(app.code_center, 8)

    def test_memory_arrows_and_h_move_memory_view(self):
        async def body(app, pilot):
            await pilot.click("#memory", offset=(1, 1))
            await pilot.press("down")
            await pilot.pause()
            self.assertEqual(self.session.memory_address, 16)

            await pilot.press("up")
            await pilot.pause()
            self.assertEqual(self.session.memory_address, 0)

            self.session.memory_address = 0x100
            await pilot.press("h")
            await pilot.pause()
            self.assertEqual(self.session.memory_address, 0)

        self.pilot(body)

    def test_page_and_home_work_in_code_and_memory(self):
        async def body(app, pilot):
            await pilot.click("#code", offset=(1, 1))
            await pilot.press("pagedown")
            await pilot.pause()
            self.assertIsNotNone(app.code_center)
            self.assertGreater(app.code_center, 0)
            await pilot.press("home")
            await pilot.pause()
            self.assertEqual(app.code_center, 0)

            await pilot.click("#memory", offset=(1, 1))
            await pilot.press("pagedown")
            await pilot.pause()
            self.assertGreater(self.session.memory_address, 0)
            await pilot.press("home")
            await pilot.pause()
            self.assertEqual(self.session.memory_address, 0)

        self.pilot(body)

    def test_escape_interrupts_continue_worker(self):
        import asyncio
        import tempfile

        from tools.debug_tui import build_app

        session = build("bucle:\n    BRA bucle\n",
                        tmp=Path(tempfile.mkdtemp()))
        app = build_app(session)

        async def go():
            async with app.run_test() as pilot:
                await pilot.press("c")
                await pilot.pause()
                await pilot.press("escape")
                for _ in range(50):
                    if not app.running:
                        break
                    await pilot.pause()

        asyncio.run(go())
        self.assertFalse(app.running)
        self.assertGreater(session.target.state().instructions, 0)

    def test_closing_tui_interrupts_an_unlimited_run_worker(self):
        import asyncio
        import tempfile

        from tools.debug_tui import build_app

        session = build("bucle:\n    BRA bucle\n",
                        tmp=Path(tempfile.mkdtemp()))
        app = build_app(session)

        async def go():
            async with app.run_test() as pilot:
                await pilot.press("c")
                await pilot.pause()
                app.exit()

        asyncio.run(go())
        self.assertTrue(session._interrupt.is_set())

    def test_ctrl_c_interrupts_instead_of_tearing_down_asyncio(self):
        import asyncio
        import tempfile

        from tools.debug_tui import build_app

        session = build("bucle:\n    BRA bucle\n",
                        tmp=Path(tempfile.mkdtemp()))
        app = build_app(session)

        async def go():
            async with app.run_test() as pilot:
                await pilot.press("c")
                await pilot.pause()
                await pilot.press("ctrl+c")
                for _ in range(50):
                    if not app.running:
                        break
                    await pilot.pause()

        asyncio.run(go())
        self.assertFalse(app.running)

    def test_focused_panel_has_double_border(self):
        async def body(app, pilot):
            await pilot.click("#code", offset=(1, 1))
            await pilot.pause()
            self.assertEqual(
                app.query_one("#code").styles.border_top[0], "double")

            await pilot.click("#memory", offset=(1, 1))
            await pilot.pause()
            self.assertEqual(
                app.query_one("#memory").styles.border_top[0], "double")

            await pilot.click("#registers", offset=(1, 1))
            await pilot.pause()
            self.assertEqual(
                app.query_one("#registers").styles.border_top[0], "double")

            await pilot.click("#console", offset=(1, 1))
            await pilot.pause()
            self.assertEqual(
                app.query_one("#console-area").styles.border_top[0],
                "double")

        self.pilot(body)

    def test_register_panel_scrolls_with_arrows(self):
        async def body(app, pilot):
            registers = app.query_one("#registers")
            await pilot.click(registers, offset=(1, 1))
            await pilot.press("down")
            await pilot.pause()
            self.assertGreater(registers.scroll_y, 0)

        self.pilot(body)

    def test_error_console_lines_are_red(self):
        from tools.debug_tui import _console_markup

        self.assertEqual(
            _console_markup("ERROR 0x02 (acceso a memoria)"),
            "[red]ERROR 0x02 (acceso a memoria)[/red]")

    def test_warnings_are_yellow_and_uppercase_in_console(self):
        from tools.debug_tui import _warning_markup

        self.assertEqual(
            _warning_markup("falta --video"),
            "[bold yellow]AVISO: falta --video[/bold yellow]")

    def test_panels_show_the_state(self):
        captured = {}

        async def body(app, pilot):
            from textual.widgets import Static

            await pilot.press("s")
            await pilot.pause()
            captured["status"] = app.sub_title
            captured["registers"] = str(
                app.query_one("#register-values", Static).renderable)

        self.pilot(body)
        self.assertIn("PC=0x00000004", captured["status"])
        self.assertIn("R1", captured["registers"])

    def test_only_changed_registers_are_highlighted(self):
        captured = {}

        async def body(app, pilot):
            from textual.widgets import Static

            await pilot.press("s")
            await pilot.pause()
            captured["changed"] = app.changed_registers
            captured["registers"] = str(
                app.query_one("#register-values", Static).renderable)

        self.pilot(body)
        self.assertEqual(captured["changed"], {1})
        self.assertIn("[bold yellow]R1", captured["registers"])
        self.assertNotIn("[bold]R2", captured["registers"])

    def test_code_and_register_panels_fill_the_top_row(self):
        captured = {}

        async def body(app, pilot):
            await pilot.pause()
            captured["code"] = app.query_one("#code").region
            captured["registers"] = app.query_one("#registers").region
            captured["memory"] = app.query_one("#memory").region

        self.pilot(body)
        self.assertEqual(captured["code"].bottom,
                         captured["registers"].bottom)
        self.assertEqual(captured["code"].bottom, captured["memory"].y)

    def test_prompt_is_inside_console_panel(self):
        captured = {}

        async def body(app, pilot):
            await pilot.pause()
            captured["area"] = app.query_one("#console-area").region
            captured["prompt"] = app.query_one("#prompt").region

        self.pilot(body)
        self.assertTrue(captured["area"].contains_region(captured["prompt"]))

    def test_source_brackets_are_not_markup(self):
        from tools.debug_tui import _escape

        self.assertEqual(_escape("LOAD R1, [R2]"), "LOAD R1, \\[R2]")

    def test_code_listing_fills_the_available_height(self):
        from tools.debug_tui import _code_lines

        program = "\n".join("MOVI R1, 1" for _ in range(80))
        # `build` solo necesita una carpeta para crear el mapa fuente.
        import tempfile
        session = build(program, tmp=Path(tempfile.mkdtemp()))
        rendered = _code_lines(session, height=30)
        self.assertEqual(len(rendered.splitlines()), 30)
        self.assertIn("0x00000070", rendered)

    def test_initial_li_does_not_leave_code_panel_empty(self):
        import asyncio
        import tempfile

        from textual.widgets import Static
        from tools.debug_tui import build_app

        program = "LI R1, 0x12345678\n" + "\n".join(
            "MOVI R2, 1" for _ in range(80))
        session = build(program, tmp=Path(tempfile.mkdtemp()))
        app = build_app(session)
        captured = {}

        async def go():
            async with app.run_test(size=(100, 40)) as pilot:
                await pilot.pause()
                rendered = str(app.query_one("#code", Static).renderable)
                captured["lines"] = len(rendered.splitlines())

        asyncio.run(go())
        self.assertGreater(captured["lines"], 2)


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
