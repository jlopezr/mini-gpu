"""El adaptador de `monitor.py input`, sin ventana y sin placa.

El cliente falso es la FPGA: aplica cada palabra con `InputDevice.apply_event`
(que es exactamente lo que hace `input_registers.v`) y contesta los huecos
libres. Lo que se comprueba es la secuencia de comandos que el PC manda:

  - Shift+A: los eventos salen en el orden de §25.7 con los modificadores nuevos;
  - un arrastre de ratón: el movimiento anterior al clic sale ANTES del clic;
  - FIFO casi llena: teclas y botones esperan sin perderse, el movimiento se
    funde y sale entero, y la FPGA no llega a dar OVERFLOW;
  - la salida: liberaciones y presencia a cero (§25.11).
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools.input_adapter import InputAdapter, run_session  # noqa: E402
from tools.sim_devices import InputDevice as D  # noqa: E402

A, LSHIFT = 0x04, 0xE1


class FakeClient:
    """Lado FPGA de INPUT_EVENTS / INPUT_PRESENCE."""

    def __init__(self, cpu_drain=0):
        self.device = D()
        self.commands = []          # ("events", [palabras]) o ("presence", kbd, mouse)
        self.cpu_drain = cpu_drain  # eventos que la "CPU" saca tras cada comando
        self.received = []          # todas las palabras que llegaron, en orden

    def _free(self):
        for _ in range(self.cpu_drain):
            if self.device.fifo:
                self.device.read(D.EVENT_DATA)
        return D.FIFO_DEPTH - len(self.device.fifo)

    def send_input_events(self, words):
        words = list(words)
        assert len(words) <= D.FIFO_DEPTH
        self.commands.append(("events", words))
        for word in words:
            self.device.apply_event(word)
            self.received.append(word)
        return D.FIFO_DEPTH - len(self.device.fifo)

    def set_input_presence(self, keyboard, mouse):
        self.commands.append(("presence", keyboard, mouse))
        self.device.set_presence(keyboard, mouse)
        return D.FIFO_DEPTH - len(self.device.fifo)

    def cpu_step(self, n=1):
        for _ in range(n):
            if self.device.fifo:
                self.device.read(D.EVENT_DATA)


class FakeSource:
    """Lo que la ventana contaría: una lista de lotes de eventos."""

    def __init__(self, *batches):
        self.batches = list(batches)

    def poll(self, timeout):
        return self.batches.pop(0) if self.batches else [{"event": "interrupt"}]


def decoded(words):
    return [D.decode_event(w) for w in words]


class ShiftATest(unittest.TestCase):
    def test_secuencia_de_shift_mas_a(self):
        client = FakeClient()
        adapter = InputAdapter(client)
        adapter.connect()
        for pressed in ([LSHIFT], [LSHIFT, A], [LSHIFT], []):
            adapter.handle({"event": "keys", "pressed": pressed})
            while adapter.pending:
                adapter.pump()
        eventos = decoded(client.received)
        self.assertEqual(
            [(e["type"], e.get("usage"), e.get("down"), e["modifiers"]) for e in eventos],
            [("modifiers", None, None, 0x02),   # Shift abajo
             ("key", A, True, 0x02),            # A abajo, con Shift
             ("key", A, False, 0x02),           # A arriba: el Shift sigue
             ("modifiers", None, None, 0x00)])  # Shift arriba
        self.assertEqual(client.device.keys, 0)

    def test_el_primer_comando_es_la_presencia(self):
        client = FakeClient()
        InputAdapter(client).connect()
        self.assertEqual(client.commands, [("presence", True, True)])

    def test_un_report_con_varios_cambios_va_en_un_solo_comando(self):
        client = FakeClient()
        adapter = InputAdapter(client)
        adapter.connect()
        adapter.handle({"event": "keys", "pressed": [LSHIFT, A, 0x05]})
        adapter.pump()                      # primero el sondeo de huecos si hace falta
        while adapter.pending:
            adapter.pump()
        comandos = [c for c in client.commands if c[0] == "events" and c[1]]
        self.assertEqual(len(comandos), 1)
        self.assertEqual(len(comandos[0][1]), 3)


class MouseDragTest(unittest.TestCase):
    def test_el_movimiento_anterior_al_clic_sale_antes_del_clic(self):
        client = FakeClient()
        adapter = InputAdapter(client)
        adapter.connect()
        adapter.handle({"event": "mouse", "buttons": 0, "dx": 4, "dy": 1})
        adapter.handle({"event": "mouse", "buttons": 1, "dx": 0, "dy": 0})   # clic
        adapter.handle({"event": "mouse", "buttons": 1, "dx": 5, "dy": 3})   # arrastre
        adapter.handle({"event": "mouse", "buttons": 0, "dx": 2, "dy": 0})   # suelta
        while adapter.pending:
            adapter.pump()
        eventos = decoded(client.received)
        self.assertEqual(
            [(e["type"], e.get("dx"), e.get("dy"), e.get("down")) for e in eventos],
            [("move", 4, 1, None),
             ("button", None, None, True),
             ("move", 5, 3, None),
             ("button", None, None, False),
             ("move", 2, 0, None)])
        self.assertEqual(client.device.mouse_buttons, 0)

    def test_movimiento_grande_se_parte_pero_suma_lo_mismo(self):
        client = FakeClient()
        adapter = InputAdapter(client)
        adapter.connect()
        adapter.handle({"event": "mouse", "buttons": 0, "dx": 5000, "dy": -3000})
        while adapter.pending:
            adapter.pump()
        eventos = decoded(client.received)
        self.assertEqual(sum(e["dx"] for e in eventos), 5000)
        self.assertEqual(sum(e["dy"] for e in eventos), -3000)


class FlowControlTest(unittest.TestCase):
    def test_con_la_fifo_llena_nada_se_pierde_ni_hay_overflow(self):
        client = FakeClient()
        adapter = InputAdapter(client)
        adapter.connect()
        # La FIFO se llena con 16 movimientos que nadie lee.
        client.send_input_events([D.mouse_move_event(1, 0)] * 16)
        adapter.free = 0
        adapter.handle({"event": "keys", "pressed": [A]})
        adapter.handle({"event": "mouse", "buttons": 0, "dx": 7, "dy": 0})
        adapter.handle({"event": "mouse", "buttons": 0, "dx": 3, "dy": 0})
        # Mientras la CPU no lea, no se manda nada con palabras.
        for _ in range(10):
            adapter.clock = lambda t=iter(range(1000, 2000)): next(t)
            adapter.pump()
        enviados = [c for c in client.commands[2:] if c[0] == "events" and c[1]]
        self.assertEqual(enviados, [])
        self.assertFalse(client.device.overflow)
        # La CPU lee; entonces sale la tecla y el movimiento FUNDIDO (7 + 3).
        client.cpu_step(16)
        n = 0
        while adapter.pending and n < 200:
            adapter.clock = lambda t=iter(range(5000, 9000)): next(t)
            adapter.pump()
            client.cpu_step(2)
            n += 1
        self.assertFalse(adapter.pending)
        self.assertFalse(client.device.overflow)
        nuevos = decoded(client.received[16:])
        self.assertEqual([e["type"] for e in nuevos], ["key", "move"])
        self.assertEqual(nuevos[1]["dx"], 10)

    def test_el_sondeo_usa_cero_palabras(self):
        client = FakeClient()
        adapter = InputAdapter(client)
        adapter.connect()
        adapter.free = 0
        adapter.handle({"event": "keys", "pressed": [A]})
        adapter.clock = lambda: 100.0
        adapter.pump()
        self.assertEqual(client.commands[-1], ("events", []))
        self.assertEqual(adapter.free, 16)


class SessionTest(unittest.TestCase):
    def test_al_salir_se_sueltan_las_teclas_y_se_quita_la_presencia(self):
        client = FakeClient(cpu_drain=0)
        fuente = FakeSource(
            [{"event": "keys", "pressed": [LSHIFT, A]},
             {"event": "mouse", "buttons": 1, "dx": 0, "dy": 0}],
            [{"event": "interrupt"}])
        run_session(client, fuente)
        device = client.device
        self.assertEqual(device.keys, 0)
        self.assertEqual(device.mouse_buttons, 0)
        self.assertFalse(device.keyboard_present)
        self.assertFalse(device.mouse_present)
        # Primero la presencia, y la presencia a cero es lo ULTIMO.
        self.assertEqual(client.commands[0], ("presence", True, True))
        self.assertEqual(client.commands[-1], ("presence", False, False))
        tipos = [(e["type"], e.get("down")) for e in decoded(client.received)]
        # Las liberaciones vienen despues de las pulsaciones.
        self.assertIn(("key", False), tipos)
        self.assertIn(("button", False), tipos)
        self.assertGreater(tipos.index(("key", False)), tipos.index(("key", True)))

    def test_cerrar_la_ventana_tambien_desconecta(self):
        client = FakeClient()
        run_session(client, FakeSource([{"event": "closed"}]))
        self.assertEqual(client.commands[-1], ("presence", False, False))


class CtrlCTest(unittest.TestCase):
    """Ctrl+C sale igual que F12: nada pulsado y la presencia a cero."""

    class Interrumpida(FakeSource):
        """Entrega sus lotes y luego se interrumpe, como Ctrl+C en la consola."""

        def __init__(self, client, *batches):
            super().__init__(*batches)
            self.client = client
            self.arm_client = False

        def poll(self, timeout):
            if not self.batches:
                if self.arm_client:
                    self.client.armed = True
                raise KeyboardInterrupt
            return self.batches.pop(0)

    class FallaUnaVez(FakeClient):
        armed = False

        def send_input_events(self, words):
            if self.armed:
                self.armed = False
                raise KeyboardInterrupt     # un segundo Ctrl+C, durante el cierre
            return super().send_input_events(words)

    def test_ctrl_c_suelta_todo_y_quita_la_presencia(self):
        client = FakeClient()
        fuente = self.Interrumpida(
            client,
            [{"event": "keys", "pressed": [LSHIFT, A]},
             {"event": "mouse", "buttons": 1, "dx": 0, "dy": 0}])
        run_session(client, fuente)             # no propaga KeyboardInterrupt
        self.assertEqual(client.device.keys, 0)
        self.assertEqual(client.device.mouse_buttons, 0)
        self.assertEqual(client.commands[-1], ("presence", False, False))

    def test_un_segundo_ctrl_c_durante_el_cierre_tambien_quita_la_presencia(self):
        client = self.FallaUnaVez()
        fuente = self.Interrumpida(
            client, [{"event": "keys", "pressed": [A]}])
        fuente.arm_client = True
        run_session(client, fuente)
        self.assertEqual(client.commands[-1], ("presence", False, False))
        self.assertFalse(client.device.mouse_present)


class PointerHomeTest(unittest.TestCase):
    """El programa de la placa sigue vivo entre sesiones y conserva su puntero."""

    @staticmethod
    def board_pointer(words, start):
        """Un programa que recorta su puntero a la pantalla de 640x480."""
        x, y = start
        for event in decoded(words):
            if event["type"] == "move":
                x = max(0, min(639, x + event["dx"]))
                y = max(0, min(479, y + event["dy"]))
        return x, y

    class Origin(FakeSource):
        origin = (320, 240)

    def sesion(self, start, home=True):
        client = FakeClient()
        silencio = [{"event": "mouse", "buttons": 0, "dx": 0, "dy": 0}]
        fuente = self.Origin(silencio, silencio, silencio, silencio)
        run_session(client, fuente, home=home)
        return self.board_pointer(client.received, start)

    def test_el_puntero_acaba_en_el_origen_desde_cualquier_sitio(self):
        for start in [(320, 240), (0, 0), (639, 479), (500, 100), (3, 400)]:
            self.assertEqual(self.sesion(start), (320, 240), start)

    def test_sin_home_el_puntero_se_queda_donde_estaba(self):
        self.assertEqual(self.sesion((500, 100), home=False), (500, 100))

    def test_una_fuente_sin_origen_no_mueve_nada(self):
        client = FakeClient()
        run_session(client, FakeSource([{"event": "mouse", "buttons": 0, "dx": 0, "dy": 0}]))
        self.assertEqual(self.board_pointer(client.received, (500, 100)), (500, 100))


if __name__ == "__main__":
    unittest.main()
