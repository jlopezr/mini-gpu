"""El barrido de semillas tiene que servir DESPUES de una regresión.

Es cuando hace falta: cuando un diseño deja de cumplir, lo que hay que
averiguar es si se ha vuelto lento o si lo que se cayó fue la semilla, y eso
sólo lo contesta correr todas y contar cuántas cumplen.

`sweep_report.py` no podía hacerlo. Se negaba a arrancar si el build de partida
no cumplía timing, y abortaba en la primera semilla que fallara, así que sólo
servía para confirmar un diseño ya sano. Pasó de verdad con la 19 tras la fase
3.5 —se fue a 72,06 MHz de 80— y el barrido hubo que rehacerlo a mano; el
resultado, tres de ocho entre 72,06 y 84,99, es exactamente el dato que la
herramienta no era capaz de producir.

Estos dos tests fijan ese comportamiento. Lo que NO se relajó es la
comprobación de que el build de partida sea de fiar: si falló, es sólo archivo
o las fuentes cambiaron mientras se construía, el netlist no representa a nada
y barrerlo no significaría nada.
"""

import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import sweep_report  # noqa: E402


def reloj(achieved, constraint=80):
    return {"clk": {"constraint": constraint, "achieved": achieved}}


def montar_build(directorio: Path, achieved: float) -> Path:
    """Un build archivado con lo mínimo que el barrido necesita leer."""
    fuente = directorio / "reports" / "20260917-000000-000000-build"
    fuente.mkdir(parents=True)
    (fuente / "metadata.json").write_text(json.dumps({"exit_code": 0}))
    (fuente / "hardware.pnr").write_text(json.dumps({"fmax": reloj(achieved)}))
    (fuente / "summary.json").write_text("{}")
    (fuente / "hardware.json").write_text("{}")
    (fuente / "scons.params").write_text("")
    with zipfile.ZipFile(fuente / "sources.zip", "w") as archivo:
        archivo.writestr("board.lpf", "constraint")
    return fuente


class SweepTest(unittest.TestCase):
    def _correr(self, achieved_fuente, achieved_por_semilla, seeds=(1, 2)):
        """Corre el barrido con nextpnr simulado y devuelve lo que imprime."""
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            fuente = montar_build(raiz, achieved_fuente)
            salidas = iter(achieved_por_semilla)

            def falso_nextpnr(command, **kwargs):
                # nextpnr escribe su informe donde se lo pidan: --report.
                destino = Path(command[command.index("--report") + 1])
                destino.write_text(json.dumps({"fmax": reloj(next(salidas))}))
                return MagicMock(returncode=0)

            texto = io.StringIO()
            with patch.object(sweep_report, "resolve_prototype", return_value=raiz), \
                 patch.object(sweep_report, "find_repo_root", return_value=raiz), \
                 patch.object(sweep_report, "find_toolchain_binary",
                              return_value=fuente / "hardware.json"), \
                 patch.object(sweep_report, "oss_cad_suite_env", return_value={}), \
                 patch.object(sweep_report, "read_ecp5_params",
                              return_value={"type": "85k", "package": "CABGA381",
                                            "speed": "6"}), \
                 patch.object(sweep_report, "extract_log_details"), \
                 patch.object(sweep_report.subprocess, "run", falso_nextpnr), \
                 patch.object(sys, "argv",
                              ["sweep_report", "-p", "x",
                               "--seeds", *(str(s) for s in seeds)]), \
                 patch.object(sys, "stdout", texto):
                sweep_report.main()
            return texto.getvalue()

    def test_barre_aunque_el_build_de_partida_no_cumpla(self):
        """El caso de la 19: partir de un netlist que falla es el motivo de
        barrer, no una razón para negarse."""
        salida = self._correr(72.06, [72.06, 84.99])
        self.assertIn("NO cumple timing", salida)
        self.assertIn("Cumplen 1 de 2", salida)
        self.assertIn("semilla 2", salida)

    def test_una_semilla_que_falla_no_aborta_el_barrido(self):
        """Antes se paraba en la primera, y entonces «cumplen tres de ocho»
        —la frase que se apunta en el apio.ini— era imposible de obtener."""
        salida = self._correr(85.0, [70.0, 90.0, 71.0], seeds=(1, 2, 3))
        self.assertIn("Cumplen 1 de 3", salida)
        # Las tres llegaron a medirse, no sólo la primera.
        self.assertIn("70.00", salida)
        self.assertIn("71.00", salida)

    def test_un_build_de_partida_no_fiable_si_para_el_barrido(self):
        """Esta guarda NO se relajó: un netlist de un build fallido, o de uno
        cuyas fuentes cambiaron a mitad, no representa a nada."""
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            fuente = montar_build(raiz, 85.0)
            (fuente / "metadata.json").write_text(
                json.dumps({"exit_code": 0, "sources_changed_during_build": True}))
            with patch.object(sweep_report, "resolve_prototype", return_value=raiz), \
                 patch.object(sweep_report, "find_repo_root", return_value=raiz), \
                 patch.object(sys, "argv", ["sweep_report", "-p", "x"]), \
                 patch.object(sys, "stdout", io.StringIO()):
                with self.assertRaises(SystemExit):
                    sweep_report.main()


if __name__ == "__main__":
    unittest.main()
