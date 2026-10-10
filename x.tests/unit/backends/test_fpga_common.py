"""Lo que comparten `fpga_cpu`, `fpga_gpu` y `fpga_sys` (`fpga_common.py`).

Sin placa: `ensure_bitstream` y el puerto se sustituyen por dobles. Lo que se fija
es que los tres abren el puerto igual, verifican la versión del monitor con el
nombre del backend en el mensaje, y descubren sus versiones de las carpetas.
"""

import sys
import unittest
from collections import namedtuple
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backends import board, fpga_cpu, fpga_gpu, fpga_sys  # noqa: E402
from backends.fpga_common import MonitorBackend  # noqa: E402

REPOSITORY = ROOT.parent
Version = namedtuple("Version", "major minor")


class PuertoFalso:
    def __init__(self, **opciones):
        self.opciones = opciones

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def monitor_falso(version):
    class Cliente:
        def __init__(self, connection):
            self.connection = connection

        def get_version(self):
            return Version(*version)

    return SimpleNamespace(
        serial=SimpleNamespace(Serial=PuertoFalso, EIGHTBITS=8, PARITY_NONE="N",
                               STOPBITS_ONE=1),
        BAUDRATE=115200, MonitorClient=Cliente)


BACKENDS = (
    (fpga_cpu, fpga_cpu.FpgaCpuBackend, "fpga-cpu"),
    (fpga_gpu, fpga_gpu.FpgaGpuBackend, "fpga-gpu"),
    (fpga_sys, fpga_sys.FpgaSysBackend, "fpga-sys"),
)


class ConstruccionTest(unittest.TestCase):
    def test_los_tres_son_backends_de_monitor(self):
        for modulo, clase, nombre in BACKENDS:
            with self.subTest(backend=nombre):
                self.assertTrue(issubclass(clase, MonitorBackend))
                self.assertEqual(clase.NAME, nombre)
                self.assertIs(clase.VERSIONS, modulo.VERSIONS)
                self.assertIn(clase.DEFAULT_VERSION, modulo.VERSIONS)

    def test_una_version_desconocida_nombra_al_backend(self):
        for _, clase, nombre in BACKENDS:
            with self.subTest(backend=nombre), \
                    self.assertRaisesRegex(ValueError, nombre):
                clase(REPOSITORY, "COM3", 1.0, version="inexistente")

    def test_comprueba_el_bitstream_una_vez_con_su_nombre(self):
        for _, clase, nombre in BACKENDS:
            with self.subTest(backend=nombre), \
                    mock.patch.object(board, "ensure_bitstream") as ensure:
                backend = clase(REPOSITORY, "COM3", 1.0)
                ensure.assert_called_once()
                self.assertEqual(ensure.call_args.args[5], nombre)
                self.assertEqual(ensure.call_args.args[6], backend.version)


class ConexionTest(unittest.TestCase):
    def crear(self, clase, monitor):
        with mock.patch.object(board, "ensure_bitstream"):
            backend = clase(REPOSITORY, "COM3", 1.0)
        backend.monitor = monitor
        return backend

    def test_con_la_version_esperada_devuelve_el_cliente(self):
        for _, clase, nombre in BACKENDS:
            with self.subTest(backend=nombre):
                backend = self.crear(clase, None)
                backend.monitor = monitor_falso(
                    backend.configuration["monitor_version"])
                with backend.connect() as client:
                    self.assertEqual(
                        (client.get_version().major, client.get_version().minor),
                        backend.configuration["monitor_version"])

    def test_con_otra_version_falla_diciendo_cual_hace_falta(self):
        for _, clase, nombre in BACKENDS:
            with self.subTest(backend=nombre):
                backend = self.crear(clase, None)
                backend.monitor = monitor_falso((99, 99))
                with self.assertRaisesRegex(
                        RuntimeError, rf"--version {nombre}={backend.version}"):
                    with backend.connect():
                        pass


if __name__ == "__main__":
    unittest.main()
