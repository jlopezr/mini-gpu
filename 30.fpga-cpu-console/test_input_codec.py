"""Pruebas del codec de INPUT por el monitor, sin placa y sin consola.

`FakeBoard` es el lado FPGA: contesta `INPUT_EVENTS` / `INPUT_PRESENCE` usando
`InputDevice` como bloque, porque el RTL tiene que reproducir ese oraculo. Si
el RTL cambia de contrato este modelo deja de coincidir y hay que decidir cual
de los dos tiene razon.

Ejecutar desde esta carpeta:

    ..\\.venv\\Scripts\\python.exe -m unittest test_input_codec -v
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.monitor_protocol import CommandRejected  # noqa: E402
from tools.sim_devices import InputDevice  # noqa: E402


def _load_monitor():
    spec = importlib.util.spec_from_file_location(
        "monitor_input_tests", Path(__file__).resolve().parent / "monitor.py")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["monitor_input_tests"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


monitor = _load_monitor()


class FakeBoard:
    """Lado FPGA de los dos comandos, con valores del cable independientes."""

    def __init__(self):
        self.device = InputDevice()
        self.salida = bytearray()
        self._pendiente = bytearray()

    def reset_input_buffer(self):
        pass

    def flush(self):
        pass

    def write(self, data: bytes) -> None:
        self._pendiente += data
        self._procesar()

    def read(self, n: int) -> bytes:
        trozo = bytes(self.salida[:n])
        self.salida[:n] = b""
        return trozo

    def _libres(self) -> int:
        return InputDevice.FIFO_DEPTH - len(self.device.fifo)

    def _procesar(self) -> None:
        while self._pendiente:
            comando = self._pendiente[0]
            if comando == 0x3B:  # INPUT_EVENTS
                if len(self._pendiente) < 2:
                    return
                n = self._pendiente[1]
                if len(self._pendiente) < 2 + 4 * n:
                    return
                for i in range(n):
                    palabra = int.from_bytes(
                        self._pendiente[2 + 4 * i:6 + 4 * i], "little")
                    self.device.apply_event(palabra)
                self._pendiente[:2 + 4 * n] = b""
                self.salida += bytes((0xBB, self._libres()))
            elif comando == 0x3C:  # INPUT_PRESENCE
                if len(self._pendiente) < 2:
                    return
                flags = self._pendiente[1]
                self._pendiente[:2] = b""
                if not flags & 1:
                    self.device.keys = 0
                if not flags & 2:
                    self.device.mouse_buttons = 0
                self.device.keyboard_present = bool(flags & 1)
                self.device.mouse_present = bool(flags & 2)
                self.salida += bytes((0xBC, self._libres()))
            else:
                raise AssertionError(f"comando inesperado 0x{comando:02x}")


def cliente(board):
    return monitor.MonitorClient(board)


class InputEventsTest(unittest.TestCase):

    def test_una_palabra_va_en_little_endian_y_devuelve_huecos(self):
        placa = FakeBoard()
        palabra = InputDevice.key_event(0x04, True, 0x02)
        self.assertEqual(cliente(placa).send_input_events([palabra]), 15)
        self.assertEqual(placa.device.fifo, [palabra])
        self.assertEqual(placa.device.keys, 1 << 0x04)

    def test_lote_de_16_llena_la_cola(self):
        placa = FakeBoard()
        palabras = [InputDevice.mouse_move_event(i, -i) for i in range(1, 17)]
        self.assertEqual(cliente(placa).send_input_events(palabras), 0)
        self.assertEqual(placa.device.fifo, palabras)

    def test_lote_mayor_que_los_huecos_pierde_con_overflow_y_sigue_sincronizado(self):
        placa = FakeBoard()
        c = cliente(placa)
        c.send_input_events([InputDevice.mouse_move_event(1, 1)] * 12)
        self.assertEqual(c.send_input_events(
            [InputDevice.mouse_move_event(2, 2)] * 8), 0)
        self.assertTrue(placa.device.overflow)
        # El enlace no se ha desincronizado: el siguiente comando responde bien.
        self.assertEqual(c.set_input_presence(True, True), 0)

    def test_rango_de_palabras(self):
        for malo in ([], [0] * 17):
            with self.assertRaises(ValueError):
                cliente(FakeBoard()).send_input_events(malo)

    def test_rechazo_de_la_placa_se_distingue(self):
        class Rechaza(FakeBoard):
            def _procesar(self):
                self._pendiente.clear()
                self.salida += b"\xff"
        with self.assertRaises(CommandRejected):
            cliente(Rechaza()).send_input_events([0])


class InputPresenceTest(unittest.TestCase):

    def test_conectar_y_desconectar(self):
        placa = FakeBoard()
        c = cliente(placa)
        c.set_input_presence(True, True)
        self.assertTrue(placa.device.keyboard_present)
        self.assertTrue(placa.device.mouse_present)
        c.send_input_events([InputDevice.key_event(0x04, True, 0)])
        c.set_input_presence(False, True)
        self.assertFalse(placa.device.keyboard_present)
        self.assertEqual(placa.device.keys, 0)
        self.assertTrue(placa.device.mouse_present)


if __name__ == "__main__":
    unittest.main()
