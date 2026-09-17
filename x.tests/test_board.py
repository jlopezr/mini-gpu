"""Comprobación de placa y carga de bitstream, sin hardware real."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from backends import board


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeSerialModule:
    EIGHTBITS = PARITY_NONE = STOPBITS_ONE = 0

    def __init__(self, fail=None):
        self.fail = fail

    def Serial(self, **kwargs):
        if self.fail is not None:
            raise self.fail
        return FakeConnection()


MUDA = TimeoutError("sin respuesta")


def fake_monitor(respuestas, open_error=None):
    """Monitor que da una respuesta distinta en cada lectura.

    Cada elemento es una versión `(major, minor)` o una excepción, para poder
    representar una placa que cambia de comportamiento tras la carga.
    """
    pending = list(respuestas)

    class Client:
        def __init__(self, connection):
            del connection

        def get_version(self):
            respuesta = pending.pop(0)
            if isinstance(respuesta, BaseException):
                raise respuesta
            major, minor = respuesta
            return SimpleNamespace(major=major, minor=minor)

    return SimpleNamespace(
        serial=FakeSerialModule(open_error), BAUDRATE=115200, MonitorClient=Client,
    )


PROJECT = Path("6.fpga-cpu")


def ensure(monitor, policy):
    board.ensure_bitstream(monitor, "COM3", 1.0, (1, 6), PROJECT,
                           "cpu-fpga", "ebr", policy)


class BoardTest(unittest.TestCase):

    def test_version_correcta_no_sube_nada(self):
        monitor = fake_monitor([(1, 6)])
        with mock.patch.object(board, "upload") as upload:
            ensure(monitor, board.UploadPolicy())
        upload.assert_not_called()

    def test_placa_ausente_no_intenta_subir(self):
        # Sin placa no hay nada que cargar: debe ser un error seco.
        monitor = fake_monitor([(1, 6)], open_error=OSError("no existe COM3"))
        with mock.patch.object(board, "upload") as upload:
            with self.assertRaises(board.BoardNotConnected) as caught:
                ensure(monitor, board.UploadPolicy(assume_yes=True))
        upload.assert_not_called()
        self.assertIn("COM3", str(caught.exception))

    def test_placa_sin_programar_se_ofrece_a_cargar(self):
        # El chip USB-serie enumera aunque la FPGA no tenga bitstream, asi que
        # "no contesta el monitor" SI se arregla cargando.
        monitor = fake_monitor([MUDA, (1, 6)])
        with mock.patch.object(board, "upload") as upload:
            ensure(monitor, board.UploadPolicy(assume_yes=True))
        upload.assert_called_once_with(PROJECT)

    def test_placa_sin_programar_con_no_upload_falla(self):
        monitor = fake_monitor([MUDA])
        with mock.patch.object(board, "upload") as upload:
            with self.assertRaises(board.BitstreamMismatch):
                ensure(monitor, board.UploadPolicy(allowed=False))
        upload.assert_not_called()

    def test_si_sigue_muda_tras_cargar_falla(self):
        monitor = fake_monitor([MUDA, MUDA])
        with mock.patch.object(board, "upload"):
            with self.assertRaises(board.BitstreamMismatch) as caught:
                ensure(monitor, board.UploadPolicy(assume_yes=True))
        self.assertIn("sigue sin responder", str(caught.exception))

    def test_no_upload_falla_sin_preguntar(self):
        monitor = fake_monitor([(1, 5)])
        with mock.patch.object(board, "upload") as upload:
            with self.assertRaises(board.BitstreamMismatch) as caught:
                ensure(monitor, board.UploadPolicy(allowed=False))
        upload.assert_not_called()
        self.assertIn("1.5", str(caught.exception))

    def test_yes_sube_y_reverifica(self):
        # Primera lectura incorrecta, segunda (tras la carga) correcta.
        monitor = fake_monitor([(1, 5), (1, 6)])
        with mock.patch.object(board, "upload") as upload:
            ensure(monitor, board.UploadPolicy(assume_yes=True))
        upload.assert_called_once_with(PROJECT)

    def test_upload_que_no_programa_la_placa_falla(self):
        # `apio upload` puede terminar bien sin dejar la placa programada.
        monitor = fake_monitor([(1, 5), (1, 5)])
        with mock.patch.object(board, "upload"):
            with self.assertRaises(board.BitstreamMismatch) as caught:
                ensure(monitor, board.UploadPolicy(assume_yes=True))
        self.assertIn("sigue respondiendo", str(caught.exception))

    def test_sin_terminal_falla_en_vez_de_colgarse(self):
        monitor = fake_monitor([(1, 5)])
        with mock.patch("sys.stdin.isatty", return_value=False), \
             mock.patch("builtins.input", side_effect=AssertionError("no preguntar")):
            with self.assertRaises(board.BitstreamMismatch) as caught:
                ensure(monitor, board.UploadPolicy())
        self.assertIn("--yes", str(caught.exception))

    def test_respuesta_negativa_cancela(self):
        monitor = fake_monitor([(1, 5)])
        with mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", return_value="n"), \
             mock.patch.object(board, "upload") as upload:
            with self.assertRaises(board.BitstreamMismatch) as caught:
                ensure(monitor, board.UploadPolicy())
        upload.assert_not_called()
        self.assertIn("cancelada", str(caught.exception))

    def test_respuesta_afirmativa_sube(self):
        monitor = fake_monitor([(1, 5), (1, 6)])
        with mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", return_value="s"), \
             mock.patch.object(board, "upload") as upload:
            ensure(monitor, board.UploadPolicy())
        upload.assert_called_once_with(PROJECT)

    def test_apio_ausente_da_mensaje_util(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError()):
            with self.assertRaises(board.BitstreamMismatch) as caught:
                board.upload(PROJECT)
        self.assertIn("apio", str(caught.exception))

    def test_apio_con_error_informa_del_codigo(self):
        completed = SimpleNamespace(returncode=2)
        with mock.patch("subprocess.run", return_value=completed):
            with self.assertRaises(board.BitstreamMismatch) as caught:
                board.upload(PROJECT)
        self.assertIn("código 2", str(caught.exception))

    def test_apio_no_captura_su_salida(self):
        # Si se capturara, una carga de varios minutos pareceria un cuelgue.
        completed = SimpleNamespace(returncode=0)
        with mock.patch("subprocess.run", return_value=completed) as run:
            board.upload(PROJECT)
        self.assertNotIn("capture_output", run.call_args.kwargs)
        self.assertNotIn("stdout", run.call_args.kwargs)


class FreshBitstreamTest(unittest.TestCase):
    """Cuando se puede reutilizar el bitstream y saltarse `apio upload`.

    El atajo vale unos diez minutos de nextpnr por carga, asi que los dos
    errores cuestan caro en direcciones opuestas: perderlo sin motivo hace
    esperar, y usarlo cuando el RTL ha cambiado programa la placa con un
    bitstream viejo y el fallo aparece mucho despues.
    """

    def _proyecto(self, carpeta: Path) -> Path:
        (carpeta / "apio.ini").write_text("[env]\nboard = ulx3s-85f\n",
                                          encoding="utf-8")
        (carpeta / "top.v").write_text("module top; endmodule\n", encoding="utf-8")
        destino = carpeta / "_build" / "default"
        destino.mkdir(parents=True)
        (destino / "hardware.bit").write_bytes(b"\x00")
        return carpeta

    def test_un_banco_de_pruebas_nuevo_no_invalida_el_bitstream(self):
        """Un `*_tb.v` no se sintetiza: no puede cambiar el bitstream.

        Contarlos costaba una sintesis entera cada vez que alguien arreglaba un
        banco, que es justo el fichero que mas se toca.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as carpeta:
            proyecto = self._proyecto(Path(carpeta))
            bitstream = proyecto / "_build" / "default" / "hardware.bit"
            reciente = bitstream.stat().st_mtime + 100
            banco = proyecto / "gpu_uart_tb.v"
            banco.write_text("// banco\n", encoding="utf-8")
            import os
            os.utime(banco, (reciente, reciente))
            self.assertEqual(board._fresh_bitstream(proyecto), bitstream)

    def test_un_fuente_sintetizable_nuevo_si_lo_invalida(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as carpeta:
            proyecto = self._proyecto(Path(carpeta))
            bitstream = proyecto / "_build" / "default" / "hardware.bit"
            reciente = bitstream.stat().st_mtime + 100
            fuente = proyecto / "top.v"
            os.utime(fuente, (reciente, reciente))
            self.assertIsNone(board._fresh_bitstream(proyecto))


if __name__ == "__main__":
    unittest.main()
