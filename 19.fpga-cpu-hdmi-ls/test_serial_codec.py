"""Pruebas del codec de paquetes del puerto serie, sin placa y sin consola.

Lo que se prueba aqui es `send_bytes` / `send_all` / `recv_bytes` de
`monitor.py` contra un modelo del lado FPGA: una cola de 64 bytes que acepta lo
que le cabe y responde exactamente como el RTL.

`interactive_console()` NO se prueba, y por eso esta separado del codec: lee un
teclado y escribe una pantalla, o sea que probarlo seria probar `msvcrt`. Todo
lo que puede estar mal sin que haya nadie delante --empaquetar, reenviar lo que
no cupo, reensamblar la respuesta-- vive en el codec.

Ejecutar desde esta carpeta:

    ..\\.venv\\Scripts\\python.exe -m unittest test_serial_codec -v
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


def _load_monitor():
    ruta = Path(__file__).resolve().parent / "monitor.py"
    spec = importlib.util.spec_from_file_location("monitor_para_tests", ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["monitor_para_tests"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


monitor = _load_monitor()


class FakeBoard:
    """El lado FPGA: dos colas y el desempaquetado de los dos comandos.

    Es un modelo del RTL, no una grabacion de sus respuestas. Si el RTL cambia
    de contrato, este modelo deja de coincidir y hay que decidir cual de los dos
    tiene razon, que es justo lo que se quiere de un modelo.
    """

    DEPTH = 64

    def __init__(self, consume: int = 0):
        self.rx = bytearray()      # lo que el PC manda hacia la CPU
        self.tx = bytearray()      # lo que la CPU manda hacia el PC
        self.salida = bytearray()  # respuestas pendientes de leer
        self.enviados = bytearray()
        # Cuantos bytes "consume la CPU" en cada paquete, para poder simular
        # una cola que se vacia sola.
        self.consume = consume
        self._pendiente = bytearray()

    # -- interfaz que espera MonitorClient ---------------------------------
    def reset_input_buffer(self) -> None:
        pass

    def flush(self) -> None:
        pass

    def write(self, data: bytes) -> None:
        self._pendiente += data
        self._procesar()

    def read(self, n: int) -> bytes:
        trozo = bytes(self.salida[:n])
        del self.salida[:n]
        return trozo

    # -- el modelo ----------------------------------------------------------
    def _procesar(self) -> None:
        while self._pendiente:
            comando = self._pendiente[0]
            # Valores del protocolo en el cable, independientes del cliente:
            # asi un cambio accidental de opcode no cambia tambien el oraculo.
            if comando == 0x38:  # SEND_BYTES
                if len(self._pendiente) < 2:
                    return
                largo = self._pendiente[1]
                if len(self._pendiente) < 2 + largo:
                    return
                carga = bytes(self._pendiente[2:2 + largo])
                del self._pendiente[:2 + largo]
                hueco = self.DEPTH - len(self.rx)
                aceptados = min(hueco, largo)
                self.rx += carga[:aceptados]
                self.enviados += carga[:aceptados]
                # La CPU va consumiendo.
                del self.rx[:self.consume]
                self.salida += bytes((0xB8, aceptados))
            elif comando == 0x39:  # RECV_BYTES
                if len(self._pendiente) < 2:
                    return
                maximo = self._pendiente[1]
                del self._pendiente[:2]
                cuantos = min(maximo, len(self.tx))
                datos = bytes(self.tx[:cuantos])
                del self.tx[:cuantos]
                self.salida += bytes((0xB9, cuantos)) + datos
            else:
                raise AssertionError(f"comando inesperado 0x{comando:02x}")


def cliente(board) -> "monitor.MonitorClient":
    return monitor.MonitorClient(board)


class SendBytesTest(unittest.TestCase):

    def test_un_paquete_que_cabe_entero(self):
        placa = FakeBoard()
        self.assertEqual(cliente(placa).send_bytes(b"Hola"), 4)
        self.assertEqual(bytes(placa.rx), b"Hola")

    def test_paquete_vacio(self):
        placa = FakeBoard()
        self.assertEqual(cliente(placa).send_bytes(b""), 0)

    def test_aceptacion_parcial_no_es_un_error(self):
        """La cola tiene 64; se mandan 70 y entran 64."""
        placa = FakeBoard()
        aceptados = cliente(placa).send_bytes(bytes(range(70)))
        self.assertEqual(aceptados, 64)
        self.assertEqual(len(placa.rx), 64)

    def test_mas_de_255_se_rechaza_al_empaquetar(self):
        # El campo de longitud es de un byte: partirlo es cosa de send_all.
        with self.assertRaises(ValueError):
            cliente(FakeBoard()).send_bytes(bytes(256))


class SendAllTest(unittest.TestCase):

    def test_reenvia_hasta_colocarlo_todo(self):
        """Con la CPU consumiendo, 500 bytes acaban entrando en orden."""
        placa = FakeBoard(consume=40)
        datos = bytes((i % 251) for i in range(500))
        cliente(placa).send_all(datos)
        self.assertEqual(bytes(placa.enviados), datos)

    def test_parte_los_paquetes_de_mas_de_255(self):
        placa = FakeBoard(consume=64)
        cliente(placa).send_all(bytes(300))
        self.assertEqual(len(placa.enviados), 300)

    def test_si_nadie_consume_falla_en_vez_de_girar(self):
        """Una CPU parada no puede dejar al PC en un bucle infinito."""
        placa = FakeBoard(consume=0)
        with self.assertRaises(monitor.MonitorError) as error:
            cliente(placa).send_all(bytes(200), timeout=0.05)
        self.assertIn("cola de entrada", str(error.exception))


class RecvBytesTest(unittest.TestCase):

    def test_cola_vacia_devuelve_vacio(self):
        self.assertEqual(cliente(FakeBoard()).recv_bytes(16), b"")

    def test_devuelve_lo_que_hay(self):
        placa = FakeBoard()
        placa.tx += b"OK\n"
        self.assertEqual(cliente(placa).recv_bytes(16), b"OK\n")

    def test_respeta_el_maximo_pedido(self):
        placa = FakeBoard()
        placa.tx += b"abcdefgh"
        c = cliente(placa)
        self.assertEqual(c.recv_bytes(3), b"abc")
        self.assertEqual(c.recv_bytes(3), b"def")
        self.assertEqual(c.recv_bytes(3), b"gh")
        self.assertEqual(c.recv_bytes(3), b"")

    def test_maximo_fuera_de_rango(self):
        for malo in (0, 256):
            with self.assertRaises(ValueError):
                cliente(FakeBoard()).recv_bytes(malo)


class MapaTest(unittest.TestCase):

    def test_la_ventana_mmio_cubre_el_dispositivo_serie(self):
        """Si no, `read-byte 0x80000204` se rechazaria en el cliente."""
        self.assertLessEqual(monitor.SERIAL_BASE + 0xFF, monitor.MMIO_LIMIT)
        for offset in (0x00, 0x04, 0x08):
            direccion = monitor.SERIAL_BASE + offset
            self.assertEqual(
                monitor.parse_address(hex(direccion)), direccion)

    def test_la_ventana_mmio_vale_para_palabras_y_bloques(self):
        """El contador de ciclos no se lee byte a byte: para eso esta read-word.

        Mientras esto solo lo usaban `read-byte`/`write-byte`, `read-word` iba
        por un tope de 32 MiB y rechazaba el MMIO en el cliente.
        """
        for comando in ("read-word", "write-block", "read-block", "memory-test"):
            with self.subTest(comando=comando):
                self.assertIn(comando, monitor.MEMORY_COMMANDS)
        self.assertEqual(monitor.parse_address("0x80000300"), 0x80000300)
        self.assertIsNone(monitor.validate_transfer(0x80000300, 4))


class TextoLibreTest(unittest.TestCase):
    """`send` manda texto, y el texto puede empezar por guion."""

    def test_send_admite_texto_que_empieza_por_guion(self):
        args = monitor.parse_args(["send", "-y"])
        self.assertEqual(args.command, "send")
        self.assertEqual(args.arguments, ["-y"])

    def test_el_puerto_sigue_funcionando_con_texto_raro(self):
        """El `--` de argparse es global y se comeria tambien el `--port`."""
        for argv in (["send", "-y", "--port", "COM6"],
                     ["--port", "COM6", "send", "-y"]):
            with self.subTest(argv=argv):
                args = monitor.parse_args(argv)
                self.assertEqual(args.arguments, ["-y"])
                self.assertEqual(args.port, "COM6")

    def test_el_escape_explicito_se_respeta(self):
        args = monitor.parse_args(["send", "--", "-y"])
        self.assertEqual(args.arguments, ["-y"])

    def test_no_toca_el_texto_normal_ni_los_demas_comandos(self):
        args = monitor.parse_args(["send", "hola", "--port", "COM6"])
        self.assertEqual(args.arguments, ["hola"])
        self.assertEqual(args.port, "COM6")
        args = monitor.parse_args(["read-word", "0x80000300", "--port", "COM6"])
        self.assertEqual(args.command, "read-word")
        self.assertEqual(args.arguments, ["0x80000300"])


if __name__ == "__main__":
    unittest.main()
