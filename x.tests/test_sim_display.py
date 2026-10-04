"""`SimDisplay`: refresco, entrada y cierre, sin abrir ninguna ventana."""
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "1.isa"))
sys.path.insert(0, str(ROOT / "2.cpu-sim-func"))
sys.path.insert(0, str(ROOT / "11.gpu-sim-func"))

from tools import input_script, sim_peripherals
from tools.sim_devices import InputDevice, VideoDevice
from tools.sim_display import SimDisplay
import minicpu_sim
import minigpu_sim

FONT = ROOT / "30.fpga-cpu-console" / "fonts" / "font8x16_cpc464.hex"


class FakeProcess:
    """Hace de `subprocess.Popen`: recoge lo que se le escribe."""

    def __init__(self):
        self.stdin = io.StringIO()
        self.waited = False

    def messages(self):
        return [json.loads(line) for line in self.stdin.getvalue().splitlines()]

    def wait(self, timeout=None):
        self.waited = True


def display_with_machine(machine=None):
    display = SimDisplay(FONT, refresh_hz=1_000_000)       # sin esperas entre frames
    device = InputDevice()
    device.attach_host(display, every=1)
    machine = machine or minicpu_sim.CPU(1 << 21, video=VideoDevice(), input_device=device)
    if machine.input is not device:
        machine.input = device
    display.bind(machine)
    display.process = FakeProcess()
    device.connect_keyboard()
    device.connect_mouse()
    return display, device, machine


def drain(device):
    events = []
    while device.fifo:
        events.append(InputDevice.decode_event(device.read(InputDevice.EVENT_DATA)))
    return events


class EventsTest(unittest.TestCase):
    def test_un_report_de_teclas_llega_al_dispositivo(self):
        display, device, _ = display_with_machine()
        display.events.put({"event": "keys", "pressed": [0xE1, 4]})
        display.apply_events(device)
        self.assertEqual([e["type"] for e in drain(device)], ["modifiers", "key"])
        self.assertEqual(device.read(InputDevice.KEY_STATE0), 1 << 4)

    def test_un_report_de_raton_llega_al_dispositivo(self):
        display, device, _ = display_with_machine()
        display.events.put({"event": "mouse", "buttons": 1, "dx": 5, "dy": -3})
        display.apply_events(device)
        self.assertEqual(drain(device), [
            {"type": "button", "button": 0, "down": True},
            {"type": "move", "dx": 5, "dy": -3}])

    def test_sin_dispositivo_presente_se_ignora(self):
        display, device, _ = display_with_machine()
        device.disconnect_keyboard()
        display.events.put({"event": "keys", "pressed": [4]})
        display.apply_events(device)
        self.assertEqual(drain(device), [])

    def test_cerrar_la_ventana_desconecta_y_para_la_cpu(self):
        display, device, cpu = display_with_machine()
        display.events.put({"event": "keys", "pressed": [4]})
        display.apply_events(device)
        drain(device)
        display.events.put({"event": "closed"})
        display.apply_events(device)
        self.assertTrue(display.closed)
        self.assertTrue(cpu.halted)
        status = device.read(InputDevice.STATUS)
        self.assertFalse(status & (InputDevice.STATUS_KEYBOARD_PRESENT
                                   | InputDevice.STATUS_MOUSE_PRESENT))
        # La tecla pulsada se libera antes de desconectar (§25.11).
        self.assertEqual(drain(device), [{"type": "key", "usage": 4, "down": False,
                                          "modifiers": 0}])

    def test_f12_para_el_simulador_sin_cerrar_la_ventana(self):
        display, device, cpu = display_with_machine()
        display.events.put({"event": "interrupt"})
        display.apply_events(device)
        self.assertTrue(display.interrupted)
        self.assertTrue(cpu.halted)
        self.assertFalse(display.closed)

    def test_en_la_gpu_para_con_peripheral_halted(self):
        device = InputDevice()
        system = minigpu_sim.System(video=VideoDevice(), input_device=device)
        display, device, system = display_with_machine(system)
        display.events.put({"event": "closed"})
        display.apply_events(device)
        self.assertTrue(system.peripheral_halted)


class RefreshTest(unittest.TestCase):
    def test_manda_la_pantalla_y_no_repite_lo_que_no_ha_cambiado(self):
        display, device, cpu = display_with_machine()
        display.poll(device)
        first = display.process.messages()
        self.assertEqual(len(first), 1)
        self.assertIn("screen", first[0])
        self.assertEqual(first[0]["screen"]["mode"], VideoDevice.MODE_PATTERN)
        display.poll(device)
        display.poll(device)
        self.assertEqual(len([m for m in display.process.messages() if "screen" in m]), 1)

    def test_un_cambio_de_pantalla_se_manda(self):
        display, device, cpu = display_with_machine()
        display.poll(device)
        cpu.video.video_mode = VideoDevice.MODE_BLANK
        display.poll(device)
        screens = [m for m in display.process.messages() if "screen" in m]
        self.assertEqual([m["screen"]["mode"] for m in screens],
                         [VideoDevice.MODE_PATTERN, VideoDevice.MODE_BLANK])

    def test_el_framebuffer_viaja_en_base64(self):
        import base64
        display, device, cpu = display_with_machine()
        cpu.video.video_mode = VideoDevice.MODE_SCANOUT
        cpu.video.fb_front = 0x1000
        cpu.memory[0x1000:0x1004] = b"\xAA\xBB\xCC\xDD"
        display.poll(device)
        fb = base64.b64decode(display.process.messages()[0]["screen"]["fb"])
        self.assertEqual(fb[:4], b"\xAA\xBB\xCC\xDD")

    def test_el_refresco_respeta_la_cadencia(self):
        display, device, cpu = display_with_machine()
        display.period = 3600.0                          # una hora
        display._last_send = __import__("time").monotonic()
        display.poll(device)
        self.assertEqual(display.process.messages(), [])

    def test_tick_del_dispositivo_llama_a_poll_cada_n(self):
        display, device, cpu = display_with_machine()
        calls = []
        display.poll = lambda dev: calls.append(dev.ticks)
        device.host_every = 3
        for _ in range(7):
            device.tick()
        self.assertEqual(calls, [3, 6])

    def test_la_cpu_entrega_la_entrada_mientras_ejecuta(self):
        display, device, cpu = display_with_machine()
        device.host_every = 5
        display.events.put({"event": "keys", "pressed": [4]})
        cpu.load_program(__import__("mini_asm").assemble_bytes("loop: BEQ R0, R0, loop"))
        for _ in range(10):
            cpu.step()
        self.assertEqual(drain(device)[0]["usage"], 4)

    def test_finish_cierra_la_ventana_si_ya_estaba_cerrada(self):
        display, device, cpu = display_with_machine()
        display.process.stdin.close = lambda: None
        display.closed = True
        display.finish(device)
        self.assertIsNone(display.process)


class WiringTest(unittest.TestCase):
    def namespace(self, **extra):
        import argparse
        base = dict(video=False, frame_instructions=1000, halt_after_swaps=None,
                    frame_output=None, console=False, console_output=None,
                    console_image=None, console_font="cpc464", serial=False,
                    serial_input=None, serial_output=None, keyboard=False, mouse=False,
                    input_script=None, window=False)
        base.update(extra)
        return argparse.Namespace(**base)

    def test_window_implica_video_e_input_con_anfitrion(self):
        parts = sim_peripherals.from_arguments(self.namespace(window=True))
        self.assertIsNotNone(parts["video"])
        self.assertIsInstance(parts["input_device"].host, SimDisplay)
        # La ventana conecta teclado y ratón al abrirse, no antes.
        self.assertFalse(parts["input_device"].keyboard_present)

    def test_sin_window_no_hay_anfitrion(self):
        self.assertIsNone(sim_peripherals.from_arguments(self.namespace(keyboard=True))
                          ["input_device"].host)

    def test_un_guion_con_window_puede_usar_teclas_sin_conectar(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "entrada.txt"
            path.write_text("@5 key press A\n", encoding="utf-8")
            input_script.load(path, keyboard=True, mouse=True)        # no falla

    def test_start_y_finish_sin_ventana_no_hacen_nada(self):
        cpu = minicpu_sim.CPU(1 << 20)
        self.assertIsNone(sim_peripherals.start_display(cpu))
        sim_peripherals.finish_display(cpu)


class MouseHoldTest(unittest.TestCase):
    """El ratón no se pierde si la FIFO está casi llena: se funde y se entrega."""

    def setUp(self):
        self.display, self.device, _ = display_with_machine()

    def put(self, buttons=0, dx=0, dy=0):
        self.display.events.put({"event": "mouse", "buttons": buttons, "dx": dx, "dy": dy})
        self.display.apply_events(self.device)

    def test_con_sitio_se_entrega_en_el_acto(self):
        self.put(0, 5, 0)
        self.assertEqual(drain(self.device), [{"type": "move", "dx": 5, "dy": 0}])

    def test_con_la_cola_casi_llena_se_retiene_sin_overflow(self):
        for _ in range(InputDevice.FIFO_DEPTH - 3):          # deja 3 huecos: menos de los reservados
            self.device.key_down(4)
            self.device.key_up(4)
            if len(self.device.fifo) >= InputDevice.FIFO_DEPTH - 3:
                break
        self.put(0, 5, 0)
        self.put(0, 3, 2)
        self.assertFalse(self.device.overflow)
        self.assertEqual(self.display._pending_mouse, [0, 8, 2])

    def test_al_haber_hueco_se_entrega_la_suma_exacta(self):
        while len(self.device.fifo) < InputDevice.FIFO_DEPTH - 3:
            self.device.mouse_move(1, 0)
        self.put(0, 5, 0)
        self.put(0, 3, 2)
        for _ in range(8):                                    # el programa lee y hace sitio
            self.device.read(InputDevice.EVENT_DATA)
        self.display.apply_events(self.device)
        self.assertIsNone(self.display._pending_mouse)
        self.assertEqual(drain(self.device)[-1], {"type": "move", "dx": 8, "dy": 2})
        self.assertFalse(self.device.overflow)

    def test_los_botones_pendientes_son_los_ultimos(self):
        while len(self.device.fifo) < InputDevice.FIFO_DEPTH - 3:
            self.device.mouse_move(1, 0)
        self.put(1, 1, 0)                                     # botón izquierdo pulsado
        self.put(0, 1, 0)                                     # y soltado antes de que haya sitio
        self.assertEqual(self.display._pending_mouse[0], 0)

    def test_sin_raton_presente_se_descarta(self):
        while len(self.device.fifo) < InputDevice.FIFO_DEPTH - 3:
            self.device.mouse_move(1, 0)
        self.put(0, 5, 0)
        self.device.disconnect_mouse()
        self.display.apply_events(self.device)
        self.assertIsNone(self.display._pending_mouse)


class PaintDemoTest(unittest.TestCase):
    """El pintor de `2.cpu-sim-func/examples` con una entrada guionizada."""

    def run_demo(self, script_text, instructions=400_000):
        device = InputDevice()
        device.attach_script(input_script.parse(script_text))
        cpu = minicpu_sim.CPU(video=VideoDevice(), input_device=device)
        cpu.load_program(minicpu_sim.load_program_file(
            ROOT / "2.cpu-sim-func" / "examples" / "input_paint.asm"))
        for _ in range(instructions):
            cpu.step()
        self.assertFalse(cpu.error)

        def pixel(x, y):
            offset = 0x100000 + 2 * (y * 320 + x)
            return cpu.memory[offset] | cpu.memory[offset + 1] << 8

        return pixel

    def test_clic_y_arrastre_pintan(self):
        # El pincel arranca en (160, 120) y se mueve medio pixel por cada pixel
        # de ratón, que es lo que hace que siga al puntero sobre una ventana x2.
        pixel = self.run_demo(
            "@0 keyboard connect\n@0 mouse connect\n"
            "@2000 mouse move 20 10\n@4000 mouse button left down\n"
            "@6000 mouse move 6 0\n@8000 mouse button left up\n")
        self.assertEqual(pixel(160, 120), 0)                # moverse sin boton no pinta
        for x, y in ((170, 125), (171, 126), (173, 125)):   # clic y arrastre, 2x2 cada uno
            self.assertEqual(pixel(x, y), 0xFFFF, (x, y))

    def test_las_letras_dan_su_color(self):
        colores = {"R": 0xF800, "G": 0x07E0, "B": 0x001F, "Y": 0xFFE0,
                   "C": 0x07FF, "M": 0xF81F, "W": 0xFFFF}
        for letra, color in colores.items():
            with self.subTest(letra=letra):
                pixel = self.run_demo(
                    f"@0 keyboard connect\n@0 mouse connect\n@2000 key press {letra}\n"
                    "@4000 mouse button left down\n", instructions=200_000)
                self.assertEqual(pixel(160, 120), color)

    def test_otra_tecla_da_un_color_que_no_es_el_de_las_letras_con_nombre(self):
        pixel = self.run_demo(
            "@0 keyboard connect\n@0 mouse connect\n@2000 key press Q\n"
            "@4000 mouse button left down\n", instructions=200_000)
        self.assertNotIn(pixel(160, 120), (0, 0xF800, 0x07E0, 0x001F, 0xFFE0, 0x07FF, 0xF81F))

    def test_la_barra_espaciadora_borra(self):
        pixel = self.run_demo(
            "@0 keyboard connect\n@0 mouse connect\n@2000 mouse button left down\n"
            "@40000 key press SPACE\n", instructions=400_000)
        self.assertEqual(pixel(160, 120), 0)


if __name__ == "__main__":
    unittest.main()
