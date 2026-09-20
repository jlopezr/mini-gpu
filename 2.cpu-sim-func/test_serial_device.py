"""Puerto serie en el simulador funcional: el dispositivo y un programa real.

`SerialDevice` modela `19.fpga-cpu-hdmi-ls/serial_port.v`. Estas pruebas fijan
las dos cosas que tienen truco --leer DATA saca de la cola, y nada bloquea-- y
despues ejecutan `examples/serial_upper.asm` de verdad, que es la unica forma de
saber que el modelo sirve para lo que existe.
"""

from __future__ import annotations

import importlib.util
import struct
import sys
import unittest
from pathlib import Path

from minicpu_sim import CPU, SerialDevice

REPO = Path(__file__).resolve().parents[1]
# De la 21 y no de la 19, que es donde estuvo hasta MMIO v2: el simulador ya
# implementa v2 (§17) y la 21 es de momento la unica carpeta migrada, asi que
# el programa de la 19 aqui daria un fallo de acceso. Cuando la 19 se migre da
# igual cual se use; hasta entonces, esta linea marca cual va por delante.
UPPER_ASM = REPO / "21.fpga-cpu-hdmi-alu" / "examples" / "serial_upper.asm"


def assemble(path: Path) -> bytes:
    spec = importlib.util.spec_from_file_location(
        "miniisa_asm_para_tests", REPO / "1.isa" / "miniisa_asm.py")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["miniisa_asm_para_tests"] = modulo
    spec.loader.exec_module(modulo)
    # Con `-I x.tests/inc`, que es donde vive `mmio.inc` generado: desde MMIO
    # v2 los ejemplos no llevan la direccion cableada, la incluyen.
    palabras = modulo.assemble(
        path.read_text(encoding="utf-8"),
        base_dir=path.parent,
        origin=str(path),
        include_dirs=(REPO / "x.tests" / "inc",))
    return b"".join(struct.pack("<I", w) for w in palabras)


class SerialDeviceTest(unittest.TestCase):

    def test_leer_data_saca_de_la_cola(self):
        dev = SerialDevice(stdin=b"AB")
        self.assertEqual(dev.read(dev.DATA), ord("A"))
        self.assertEqual(dev.read(dev.DATA), ord("B"))
        self.assertEqual(dev.read(dev.DATA), 0)

    def test_peek_no_saca(self):
        """Existe para poder mirar la cola desde el PC sin destruirla."""
        dev = SerialDevice(stdin=b"AB")
        self.assertEqual(dev.read(dev.PEEK), ord("A"))
        self.assertEqual(dev.read(dev.PEEK), ord("A"))
        self.assertEqual(dev.read(dev.STATUS) & 0xFF, 2)

    def test_status_cuenta_las_dos_colas(self):
        dev = SerialDevice(depth=64, stdin=b"abc")
        dev.write(dev.DATA, ord("X"))
        estado = dev.read(dev.STATUS)
        self.assertEqual(estado & 0xFF, 3)          # rx_count
        self.assertEqual((estado >> 8) & 0xFF, 63)  # tx_free

    def test_nada_bloquea(self):
        """Leer vacio da cero y escribir lleno pierde el byte, como el RTL."""
        dev = SerialDevice(depth=2)
        self.assertEqual(dev.read(dev.DATA), 0)
        for _ in range(5):
            dev.write(dev.DATA, 0x41)
        self.assertEqual(dev.pop(), b"AA")

    def test_overrun_es_pegajoso_y_se_borra(self):
        dev = SerialDevice(depth=4)
        self.assertEqual(dev.push(b"123456"), 4)
        self.assertTrue(dev.overrun)
        self.assertEqual((dev.read(dev.STATUS) >> 16) & 1, 1)
        dev.write(dev.STATUS, 1 << 16)
        self.assertFalse(dev.overrun)

    def test_fuera_de_la_ventana_no_es_del_dispositivo(self):
        dev = SerialDevice()
        # En v2 SERIE es un bloque de 64 KiB propio en 0x80100000, no un slot
        # de 256 bytes dentro de una pagina compartida. Los limites se sacan
        # de la clase para que el caso siga diciendo "la ventana es la que el
        # dispositivo declara" y no "la ventana es esta que copie aqui".
        self.assertTrue(dev.contains(dev.BASE))
        self.assertTrue(dev.contains(dev.BASE + dev.SIZE - 1))
        # Justo fuera por los dos lados. Abajo esta SYSTEM y arriba VIDEO: el
        # hueco del megabyte entre bloques es a proposito (§3).
        self.assertFalse(dev.contains(dev.BASE - 1))
        self.assertFalse(dev.contains(dev.BASE + dev.SIZE))


class SerialUpperProgramTest(unittest.TestCase):
    """`examples/serial_upper.asm`, ejecutado de verdad."""

    def run_program(self, entrada: bytes, limite: int = 200_000) -> bytes:
        serie = SerialDevice(stdin=entrada)
        cpu = CPU(memory_size=64 * 1024, serial=serie)
        cpu.load_program(assemble(UPPER_ASM))
        # El programa no termina nunca: se le deja correr hasta que vacia la
        # cola de entrada y devuelve todo. Es lo que hace la placa, donde lo
        # para el monitor.
        for _ in range(limite):
            cpu.step()
            if not serie.rx and len(serie.tx) >= len(entrada):
                break
        self.assertFalse(cpu.error, f"error {cpu.error_code:#04x}")
        return serie.pop(255)

    def test_pasa_a_mayuscula(self):
        self.assertEqual(self.run_program(b"hola"), b"HOLA")

    def test_lo_que_no_es_minuscula_vuelve_igual(self):
        """Digitos, espacios y signos tienen que sobrevivir al eco."""
        self.assertEqual(self.run_program(b"a1 Z!z"), b"A1 Z!Z")

    def test_los_bordes_del_rango(self):
        """'a' y 'z' cambian; los vecinos de la tabla ASCII no.

        El `` ` `` es 0x60 y el `{` es 0x7B: si las comparaciones estuvieran
        desplazadas un puesto, uno de los dos se convertiria tambien.
        """
        self.assertEqual(self.run_program(b"`az{"), b"`AZ{")

    def test_una_linea_entera(self):
        texto = b"the quick brown fox\n"
        self.assertEqual(self.run_program(texto), texto.upper())


if __name__ == "__main__":
    unittest.main()
