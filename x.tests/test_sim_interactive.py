"""`--serial-tty`, el límite de instrucciones y el depurador con INPUT y pantalla.

Nada de esto abre una ventana ni toca el terminal: el proceso de la ventana y el
teclado se sustituyen por dobles.
"""
import argparse
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "1.isa"))
sys.path.insert(0, str(ROOT / "2.cpu-sim-func"))
sys.path.insert(0, str(ROOT / "11.gpu-sim-func"))

from mini_asm import assemble_bytes
from tools import debug_cli, sim_peripherals
from tools.debug_core import CommandError, DebugSession
from tools.debug_target import SimTarget, TargetError
from tools.sim_devices import InputDevice, SerialDevice, VideoDevice
from tools.sim_display import SimDisplay
from tools.sim_host import CTRL_C, SerialTty
import minicpu_sim
import minigpu_sim

LOOP = "loop: BEQ R0, R0, loop"


class FakeKeyboard:
    def __init__(self, *chunks):
        self.chunks = list(chunks)

    def read(self):
        return self.chunks.pop(0) if self.chunks else b""


def tty_with(*chunks):
    tty = SerialTty()
    tty.keyboard = FakeKeyboard(*chunks)
    return tty


class InstructionLimitTest(unittest.TestCase):
    def run_cli(self, *options):
        with tempfile.TemporaryDirectory() as tmp:
            program = Path(tmp) / "bucle.asm"
            program.write_text(LOOP + "\n", encoding="utf-8")
            serial = Path(tmp) / "serie.bin"
            result = subprocess.run(
                [sys.executable, str(ROOT / "2.cpu-sim-func" / "minicpu_sim.py"), str(program),
                 "--serial-output", str(serial), *options],
                capture_output=True, encoding="utf-8")
            return result, serial.exists()

    def test_el_limite_sale_con_mensaje_y_codigo_2_sin_traceback(self):
        result, _ = self.run_cli("--run-limit", "500")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("límite de instrucciones alcanzado", result.stderr)
        self.assertIn("--run-limit 500", result.stderr)

    def test_las_salidas_se_escriben_aunque_se_llegue_al_limite(self):
        _, wrote = self.run_cli("--run-limit", "500")
        self.assertTrue(wrote)

    def test_la_excepcion_sigue_siendo_runtime_error(self):
        cpu = minicpu_sim.CPU(1 << 16)
        cpu.load_program(assemble_bytes(LOOP))
        with self.assertRaises(RuntimeError) as caught:
            cpu.run(100)
        self.assertIsInstance(caught.exception, minicpu_sim.InstructionLimitExceeded)


class SerialTtyTest(unittest.TestCase):
    def test_las_teclas_entran_por_rx(self):
        tty = tty_with(b"hola")
        serial = SerialDevice()
        tty.poll(serial)
        self.assertEqual(bytes(serial.rx), b"hola")

    def test_las_que_no_caben_esperan_y_no_se_pierden(self):
        tty = tty_with(b"x" * 100)
        serial = SerialDevice(depth=64)
        tty.poll(serial)
        self.assertEqual(len(serial.rx), 64)
        self.assertEqual(len(tty.pending), 36)
        self.assertFalse(serial.overrun)
        del serial.rx[:]
        tty.poll(serial)
        self.assertEqual(len(serial.rx), 36)
        self.assertEqual(tty.pending, b"")

    def test_ctrl_c_para_la_maquina_y_no_llega_al_programa(self):
        tty = tty_with(b"ab" + CTRL_C)
        cpu = minicpu_sim.CPU(1 << 16)
        tty.bind(cpu)
        serial = SerialDevice()
        tty.poll(serial)
        self.assertTrue(cpu.halted)
        self.assertTrue(tty.interrupted)
        self.assertEqual(bytes(serial.rx), b"")

    def test_en_la_gpu_para_con_peripheral_halted(self):
        tty = tty_with(CTRL_C)
        system = minigpu_sim.System()
        tty.bind(system)
        tty.poll(SerialDevice())
        self.assertTrue(system.peripheral_halted)

    def test_sin_teclado_abierto_no_hace_nada(self):
        tty = SerialTty()
        serial = SerialDevice()
        tty.poll(serial)
        self.assertEqual(bytes(serial.rx), b"")

    def test_la_salida_del_programa_va_al_terminal_y_se_conserva(self):
        serial = SerialDevice()
        tty = tty_with()
        written = []
        tty.write = written.append
        serial.attach_tty(tty)
        for byte in b"ok":
            serial.write(serial.DATA, byte)
        for _ in range(32):
            serial.tick()
        self.assertEqual(b"".join(written), b"ok")
        self.assertEqual(serial.output(), b"ok")

    def test_el_terminal_sondea_la_entrada_cada_n_ticks(self):
        serial = SerialDevice()
        tty = tty_with(b"z")
        serial.attach_tty(tty, every=10)
        for _ in range(9):
            serial.tick()
        self.assertEqual(bytes(serial.rx), b"")
        serial.tick()
        self.assertEqual(bytes(serial.rx), b"z")

    def test_un_programa_de_la_cpu_recibe_las_teclas(self):
        serial = SerialDevice()
        tty = tty_with(b"", b"A")
        serial.attach_tty(tty, every=5)
        cpu = minicpu_sim.CPU(1 << 16, serial=serial)
        cpu.load_program(assemble_bytes("""MOVHI R1, 0x8010
wait: LOAD R2, R1, 4
ANDI R2, R2, 0xFF
BEQ R2, R0, wait
LOAD R3, R1, 0
STORE R3, R1, 0
HALT"""))
        tty.bind(cpu)
        out = []
        tty.write = out.append
        cpu.run(1000)
        self.assertEqual(cpu.regs[3], ord("A"))

    def test_start_y_close_restauran_el_terminal(self):
        keyboards = []

        class Recorded:
            def __enter__(self):
                keyboards.append("on")
                return self

            def __exit__(self, *exc):
                keyboards.append("off")

        with mock.patch("tools.sim_host.Keyboard", Recorded), \
                mock.patch("tools.sim_host.atexit.register"):
            tty = SerialTty()
            with mock.patch("sys.stderr", io.StringIO()):
                tty.start()
            tty.close()
            tty.close()                                  # idempotente
        self.assertEqual(keyboards, ["on", "off"])


def namespace(**kwargs):
    base = dict(video=False, frame_instructions=1000, halt_after_swaps=None,
                frame_output=None, console=False, console_output=None,
                console_image=None, console_font="cpc464", serial=False,
                serial_input=None, serial_output=None, serial_tty=False,
                keyboard=False, mouse=False, input_script=None, window=False)
    base.update(kwargs)
    return argparse.Namespace(**base)


class SerialTtyOptionTest(unittest.TestCase):
    def test_serial_tty_habilita_serie_con_terminal(self):
        serial = sim_peripherals.from_arguments(namespace(serial_tty=True))["serial"]
        self.assertIsInstance(serial.tty, SerialTty)

    def test_sin_serial_tty_no_hay_terminal(self):
        serial = sim_peripherals.from_arguments(namespace(serial=True))["serial"]
        self.assertIsNone(serial.tty)

    def test_start_display_abre_y_finish_cierra_el_terminal(self):
        parts = sim_peripherals.from_arguments(namespace(serial_tty=True))
        cpu = minicpu_sim.CPU(1 << 16, **parts)
        with mock.patch.object(SerialTty, "start") as start, \
                mock.patch.object(SerialTty, "close") as close:
            sim_peripherals.start_display(cpu)
            self.assertTrue(start.called)
            self.assertIs(parts["serial"].tty.machine, cpu)
            sim_peripherals.finish_display(cpu)
            self.assertTrue(close.called)

    def test_mini_dbg_rechaza_serial_tty_y_window_en_placa(self):
        for argv in (["programa.asm", "--serial-tty"],
                     ["--board", "-p", "21", "--window"]):
            with self.subTest(argv=argv), mock.patch("sys.stderr", io.StringIO()) as err:
                self.assertEqual(debug_cli.main(argv), 2)
                self.assertIn("error", err.getvalue())


def session_with_input(**video):
    device = InputDevice()
    device.connect_keyboard()
    device.connect_mouse()
    cpu = minicpu_sim.CPU(1 << 21, video=VideoDevice(), input_device=device)
    cpu.load_program(assemble_bytes(LOOP))
    return DebugSession(SimTarget(cpu)), cpu, device


class FakeDisplayProcess:
    def __init__(self):
        self.stdin = io.StringIO()

    def poll(self):
        return None

    def wait(self, timeout=None):
        pass


def fake_start(self, device=None):
    """`SimDisplay.start` sin proceso: lo mismo, con un doble."""
    self.closed = False
    self.process = FakeDisplayProcess()
    self.started_with_input = device is not None
    if device is not None:
        device.connect_keyboard()
        device.connect_mouse()
    self._send_screen(force=True)


class DebuggerInputTest(unittest.TestCase):
    def test_input_enseña_el_estado_sin_consumir_la_cola(self):
        session, cpu, device = session_with_input()
        device.keyboard_report({0xE1, 4})
        device.mouse_report(1, 3, -2)
        before = list(device.fifo)
        text = "\n".join(session.execute("input"))
        self.assertIn("teclado presente", text)
        self.assertIn("ratón presente", text)
        self.assertIn(f"cola {len(before)}/16", text)
        self.assertIn("teclas pulsadas: A LSHIFT", text)       # por Usage ID ascendente
        self.assertIn("botones del ratón: left", text)
        self.assertIn("tecla A down", text)
        self.assertIn("movimiento dx=3 dy=-2", text)
        self.assertEqual(list(device.fifo), before)             # mirar no consume

    def test_input_marca_el_overflow(self):
        session, cpu, device = session_with_input()
        for _ in range(17):
            device.mouse_move(1, 0)
        self.assertIn("OVERFLOW", session.execute("input")[0])

    def test_input_sin_dispositivo_es_un_error_de_capacidad(self):
        session = DebugSession(SimTarget(minicpu_sim.CPU(1 << 16)))
        with self.assertRaises(TargetError):
            session.execute("input")

    def test_input_no_admite_argumentos(self):
        session, *_ = session_with_input()
        with self.assertRaises(CommandError):
            session.execute("input algo")

    def test_help_oculta_input_si_no_hay(self):
        session = DebugSession(SimTarget(minicpu_sim.CPU(1 << 16)))
        self.assertNotIn("input", "\n".join(session.execute("help")))
        session, *_ = session_with_input()
        self.assertIn("input", "\n".join(session.execute("help")))


class DebuggerScreenTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(SimDisplay, "start", fake_start)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_fb_screen_abre_la_ventana_con_input(self):
        session, cpu, device = session_with_input()
        text = session.execute("fb screen")[0]
        self.assertIn("teclado y ratón", text)
        self.assertTrue(session._screen.started_with_input)
        self.assertIs(device.host, session._screen)

    def test_sin_input_la_ventana_solo_muestra(self):
        cpu = minicpu_sim.CPU(1 << 21, video=VideoDevice())
        session = DebugSession(SimTarget(cpu))
        self.assertIn("sin INPUT", session.execute("fb screen")[0])
        self.assertFalse(session._screen.started_with_input)

    def test_sin_video_es_un_error(self):
        session = DebugSession(SimTarget(minicpu_sim.CPU(1 << 16)))
        with self.assertRaises(TargetError):
            session.open_screen()

    def test_f12_interrumpe_la_ejecucion_y_no_para_la_maquina(self):
        session, cpu, device = session_with_input()
        session.execute("fb screen")
        session._screen.events.put({"event": "interrupt"})
        session._screen.apply_events(device)
        self.assertTrue(session._interrupt.is_set())
        self.assertFalse(cpu.halted)

    def test_cerrar_la_ventana_desconecta_pero_no_para(self):
        session, cpu, device = session_with_input()
        session.execute("fb screen")
        session._screen.events.put({"event": "closed"})
        session._screen.apply_events(device)
        self.assertFalse(cpu.halted)
        self.assertFalse(device.keyboard_present)

    def test_los_comandos_refrescan_la_pantalla(self):
        session, cpu, device = session_with_input()
        session.execute("fb screen")
        cpu.video.video_mode = VideoDevice.MODE_BLANK
        session.execute("regs")
        screens = [line for line in session._screen.process.stdin.getvalue().splitlines()
                   if '"screen"' in line]
        self.assertGreaterEqual(len(screens), 2)

    def test_las_teclas_llegan_mientras_se_ejecuta(self):
        session, cpu, device = session_with_input()
        session.execute("fb screen")
        device.host_every = 1
        session._screen.events.put({"event": "keys", "pressed": [4]})
        session.execute("step 3")
        self.assertEqual(device.pressed(), [4])

    def test_fb_off_y_quit_cierran_la_pantalla(self):
        session, cpu, device = session_with_input()
        session.execute("fb screen")
        screen = session._screen
        session.execute("fb off")
        self.assertIsNone(session._screen)
        self.assertIsNone(device.host)
        self.assertIsNone(screen.process)
        session.execute("fb screen")
        session.execute("quit")
        self.assertIsNone(session._screen)

    def test_fb_screen_otra_vez_refresca_sin_abrir_otra(self):
        session, cpu, device = session_with_input()
        session.execute("fb screen")
        first = session._screen
        self.assertEqual(session.execute("fb screen"), ["pantalla refrescada"])
        self.assertIs(session._screen, first)

    def test_una_ventana_cerrada_se_vuelve_a_abrir(self):
        session, cpu, device = session_with_input()
        session.execute("fb screen")
        session._screen.closed = True
        session.execute("fb screen")
        self.assertFalse(session._screen.closed)


class DisplayOptionsTest(unittest.TestCase):
    def test_on_interrupt_sustituye_a_parar_la_maquina(self):
        calls = []
        display = SimDisplay(Path("x"), on_interrupt=lambda: calls.append(1))
        cpu = minicpu_sim.CPU(1 << 16)
        display.bind(cpu)
        display.events.put({"event": "interrupt"})
        display.apply_events(None)
        self.assertEqual(calls, [1])
        self.assertFalse(cpu.halted)

    def test_sin_dispositivo_la_entrada_se_ignora(self):
        display = SimDisplay(Path("x"))
        display.events.put({"event": "keys", "pressed": [4]})
        display.events.put({"event": "mouse", "buttons": 1, "dx": 1, "dy": 1})
        display.apply_events(None)                           # no revienta

    def test_stop_on_close_falso_no_para(self):
        display = SimDisplay(Path("x"), stop_on_close=False)
        cpu = minicpu_sim.CPU(1 << 16)
        display.bind(cpu)
        display.events.put({"event": "closed"})
        display.apply_events(None)
        self.assertTrue(display.closed)
        self.assertFalse(cpu.halted)


if __name__ == "__main__":
    unittest.main()
