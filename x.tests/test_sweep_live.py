"""`build-sweep --live`: barrer la síntesis de un build que aún está rutando.

Lo que se vigila es que no se barra una síntesis que no es la de lo que hay en
disco: la de un build anterior, una a medio escribir, o una de unas fuentes que
alguien ha editado después de arrancar.
"""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / 'tools'):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import sweep_report  # noqa: E402


def _touch(path: Path, when: float):
    os.utime(path, (when, when))


class LiveSweepTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proto = Path(self.tmp.name) / '99.demo'
        (self.proto / '_build' / 'default').mkdir(parents=True)
        self.top = self.proto / 'top.v'
        self.top.write_text('module top; endmodule\n', encoding='utf-8')
        digest = hashlib.sha256(self.top.read_bytes()).hexdigest()
        reports = self.proto / 'reports'
        self.finished = reports / '20260101-000000-old'
        self.live = reports / '20260102-000000-new'
        for folder in (self.finished, self.live):
            folder.mkdir(parents=True)
            (folder / 'sources.zip').write_bytes(b'z')
            (folder / 'metadata.json').write_text(
                json.dumps({'source_sha256': {'top.v': digest}}), encoding='utf-8')
        # Solo el acabado tiene el resumen que se escribe al terminar.
        (self.finished / 'summary.json').write_text('{}', encoding='utf-8')
        self.started = 1_000_000.0
        _touch(self.live / 'sources.zip', self.started)
        build = self.proto / '_build' / 'default'
        (build / 'hardware.json').write_text('{"modules": {}}\n', encoding='utf-8')
        (build / 'scons.params').write_text('p', encoding='utf-8')
        for name in ('hardware.json', 'scons.params'):
            _touch(build / name, self.started + 120)

    def test_elige_el_build_en_curso_y_no_el_terminado(self):
        self.assertEqual(self.live, sweep_report.live_report_dir(self.proto))

    def test_sin_build_en_curso_falla(self):
        (self.live / 'summary.json').write_text('{}', encoding='utf-8')
        with self.assertRaises(SystemExit) as caught:
            sweep_report.live_report_dir(self.proto)
        self.assertIn('en curso', str(caught.exception))

    def test_devuelve_los_ficheros_de_la_sintesis(self):
        hardware, params = sweep_report.live_synthesis(self.proto, self.live)
        self.assertEqual(self.proto / '_build' / 'default' / 'hardware.json', hardware)
        self.assertEqual(self.proto / '_build' / 'default' / 'scons.params', params)

    def test_una_sintesis_anterior_al_arranque_no_vale(self):
        """Si yosys aun no ha terminado, `_build/default` conserva la del build de antes."""
        _touch(self.proto / '_build' / 'default' / 'hardware.json', self.started - 3600)
        with self.assertRaises(SystemExit) as caught:
            sweep_report.live_synthesis(self.proto, self.live)
        self.assertIn('no es de este build', str(caught.exception))

    def test_un_hardware_json_a_medio_escribir_no_vale(self):
        (self.proto / '_build' / 'default' / 'hardware.json').write_text(
            '{"modules": {"top": {"cells": ', encoding='utf-8')
        _touch(self.proto / '_build' / 'default' / 'hardware.json', self.started + 120)
        with self.assertRaises(SystemExit) as caught:
            sweep_report.live_synthesis(self.proto, self.live)
        self.assertIn('incompleto', str(caught.exception))

    def test_fuentes_editadas_despues_de_arrancar_no_valen(self):
        self.top.write_text('module top; wire x; endmodule\n', encoding='utf-8')
        with self.assertRaises(SystemExit) as caught:
            sweep_report.live_synthesis(self.proto, self.live)
        self.assertIn('top.v', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
