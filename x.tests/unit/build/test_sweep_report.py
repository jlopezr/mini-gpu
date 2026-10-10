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

ROOT = Path(__file__).resolve().parents[3]
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
    def _correr(self, achieved_fuente, achieved_por_semilla, seeds=(1, 2), extra=()):
        """Corre el barrido con nextpnr simulado y devuelve lo que imprime.

        Los comandos que habria lanzado quedan en `self.comandos`."""
        import tempfile

        self.comandos = []

        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            fuente = montar_build(raiz, achieved_fuente)
            salidas = iter(achieved_por_semilla)

            def falso_nextpnr(command, **kwargs):
                # nextpnr escribe su informe donde se lo pidan: --report.
                self.comandos.append(command)
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
                               "--seeds", *(str(s) for s in seeds), *extra]), \
                 patch.object(sys, "stdout", texto):
                sweep_report.main()
            return texto.getvalue()

    def test_las_opciones_de_nextpnr_llegan_al_comando_y_se_anotan(self):
        self._correr(85.0, [90.0, 91.0],
                     extra=["--nextpnr-options", "tmg-ripup", "placer-heap-timingweight=30"])
        for comando in self.comandos:
            self.assertEqual(comando[comando.index("--tmg-ripup") - 2:comando.index("--tmg-ripup") + 3],
                             ["--seed", comando[comando.index("--seed") + 1], "--tmg-ripup",
                              "--placer-heap-timingweight", "30"])
        self.assertEqual(len(self.comandos), 2)

    def test_sin_opciones_el_comando_es_el_de_siempre(self):
        self._correr(85.0, [90.0, 91.0])
        self.assertNotIn("--tmg-ripup", self.comandos[0])
        self.assertEqual(self.comandos[0][self.comandos[0].index("--seed") + 2], "--json")

    def test_nextpnr_flags_rechaza_lo_que_ya_pone_el_barrido(self):
        self.assertEqual(sweep_report.nextpnr_flags(["router=router1", "no-tmdriv"]),
                         ["--router", "router1", "--no-tmdriv"])
        for prohibido in ("seed=3", "json=x", "force"):
            with self.assertRaises(SystemExit):
                sweep_report.nextpnr_flags([prohibido])

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


def resultados(*achieved, primera=1, constraint=80):
    return [dict(seed=primera + i, clocks=reloj(a, constraint), passes=a >= constraint)
            for i, a in enumerate(achieved)]


class CompareTest(unittest.TestCase):
    def test_un_cambio_mayor_que_el_ruido_es_mejora_o_empeora(self):
        mejora = "\n".join(sweep_report.compare_sweeps(
            resultados(80, 82, 84), resultados(90, 92, 94)))
        self.assertIn("MEJORA", mejora)
        empeora = "\n".join(sweep_report.compare_sweeps(
            resultados(90, 92, 94), resultados(80, 82, 84)))
        self.assertIn("EMPEORA", empeora)
        self.assertIn("peor 90.00 -> 80.00 (-10.00)", empeora)

    def test_un_cambio_dentro_del_rango_es_ruido(self):
        """Con seeds dispersas, +1 MHz de mediana es otra semilla, no el RTL."""
        salida = "\n".join(sweep_report.compare_sweeps(
            resultados(70, 80, 90), resultados(71, 81, 91)))
        self.assertIn("dentro del ruido", salida)
        self.assertNotIn("MEJORA", salida)

    def test_compara_solo_semillas_comunes_y_pide_al_menos_dos(self):
        salida = "\n".join(sweep_report.compare_sweeps(
            resultados(80, 82, 84), resultados(82, 84, primera=2)))
        self.assertIn("2 semillas comunes: 2 3", salida)
        with self.assertRaises(SystemExit):
            sweep_report.compare_sweeps(resultados(80, 82), resultados(80, primera=2))

    def test_compare_con_otras_semillas_se_niega_antes_de_barrer(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            anterior = Path(temp) / "sweep-x"
            anterior.mkdir()
            (anterior / "results.json").write_text(json.dumps(resultados(80, 82, 84)))
            with patch.object(sys, "argv", ["sweep_report", "-p", "x", "--seeds", "1", "2",
                                            "--compare", str(anterior)]):
                with self.assertRaises(SystemExit) as error:
                    sweep_report.main()
            self.assertIn("mismas semillas", str(error.exception))


def montar_barrido(raiz: Path, build: str, nombre: str, achieved, pedidas=None) -> Path:
    carpeta = raiz / "reports" / build / nombre
    carpeta.mkdir(parents=True)
    resultados_ = resultados(*achieved)
    (carpeta / "results.json").write_text(json.dumps(resultados_))
    seeds = pedidas or [r["seed"] for r in resultados_]
    (carpeta / "metadata.json").write_text(json.dumps({"seeds": seeds}))
    for seed in seeds:
        (carpeta / f"seed-{seed}").mkdir()
        if seed in [r["seed"] for r in resultados_]:
            (carpeta / f"seed-{seed}" / "summary.json").write_text("{}")
    return carpeta


class ColorTest(unittest.TestCase):
    VERDE, ROJO, AMARILLO, FIN = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

    def test_show_pinta_cada_valor_segun_llegue_o_no_a_lo_exigido(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            carpeta = montar_barrido(Path(temp), "20260929-100000-000000-build",
                                     "sweep-20260929-101500-000001", [70, 90])
            con = sweep_report.show_sweep(carpeta, color=True)
            sin = sweep_report.show_sweep(carpeta, color=False)
        texto = "\n".join(con)
        self.assertIn(f"{self.ROJO}NO{self.FIN}", texto)
        self.assertIn(f"{self.VERDE}OK{self.FIN}", texto)
        self.assertIn(f"{self.AMARILLO}Cumplen 1 de 2{self.FIN}", texto)
        self.assertIn(f"peor {self.ROJO}70.00{self.FIN}", texto)
        self.assertIn(f"mejor {self.VERDE}90.00{self.FIN}", texto)
        self.assertNotIn("\033", "\n".join(sin))

    def test_las_columnas_no_se_desalinean_al_pintar(self):
        import re
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            montar_barrido(raiz, "20260929-100000-000000-build", "sweep-20260929-101500-000001", [70, 90])
            con = sweep_report.list_sweeps(raiz, color=True)
            sin = sweep_report.list_sweeps(raiz, color=False)
        quitar = lambda linea: re.sub(r"\033\[\d+m", "", linea)  # noqa: E731
        self.assertEqual([quitar(linea) for linea in con], sin)
        self.assertIn(f"{self.AMARILLO}1/2{self.FIN}", con[1])

    def test_compare_pinta_el_veredicto(self):
        mejora = "\n".join(sweep_report.compare_sweeps(
            resultados(80, 82, 84), resultados(90, 92, 94), color=True))
        self.assertIn(f"{self.VERDE}MEJORA{self.FIN}", mejora)
        empeora = "\n".join(sweep_report.compare_sweeps(
            resultados(90, 92, 94), resultados(80, 82, 84), color=True))
        self.assertIn(f"{self.ROJO}EMPEORA{self.FIN}", empeora)

    def test_sin_terminal_o_con_no_color_no_hay_codigos(self):
        with patch.object(sys.stdout, "isatty", return_value=True, create=True), \
             patch.dict("os.environ", {"NO_COLOR": "1"}):
            self.assertFalse(sweep_report._use_color())
        with patch.object(sys, "stdout", io.StringIO()):
            self.assertFalse(sweep_report._use_color())


class ConsultaTest(unittest.TestCase):
    def _correr(self, raiz, *argumentos):
        texto = io.StringIO()
        with patch.object(sweep_report, "resolve_prototype", return_value=raiz), \
             patch.object(sweep_report, "find_repo_root", return_value=raiz), \
             patch.object(sys, "argv", ["sweep_report", "-p", "x", *argumentos]), \
             patch.object(sys, "stdout", texto):
            sweep_report.main()
        return texto.getvalue()

    def test_list_muestra_una_fila_por_barrido_y_reloj(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            montar_barrido(raiz, "20260929-100000-000000-build", "sweep-20260929-101500-000001",
                           [70, 80, 90])
            montar_barrido(raiz, "20260930-100000-000000-build", "sweep-20260930-101500-000001",
                           [85, 86], pedidas=[1, 2, 3])
            salida = self._correr(raiz, "--list")
        self.assertIn("20260929-101500", salida)
        self.assertRegex(salida, r"20260929-100000\s+20260929-101500\s+3\s+2/3\s+clk\s+70\.00\s+80\.00\s+90\.00")
        # Una semilla pedida que no dio informe se ve como 2/3, no se esconde.
        self.assertRegex(salida, r"20260930-101500\s+2/3\s+2/2\s+clk")

    def test_last_resume_el_ultimo_barrido_de_cada_prototipo_con_barridos(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            uno, dos, sin = raiz / "1.uno", raiz / "2.dos", raiz / "3.sin"
            montar_barrido(uno, "20260929-100000-000000-build", "sweep-20260929-101500-000001", [70, 90])
            montar_barrido(uno, "20260930-100000-000000-build", "sweep-20260930-101500-000001", [84, 88])
            montar_barrido(dos, "20260929-110000-000000-build", "sweep-20260929-111500-000001", [80, 81])
            sin.mkdir()
            # Un segundo reloj en 2.dos: su fila no repite prototipo ni datos del barrido.
            resultados_dos = json.loads((dos / "reports/20260929-110000-000000-build/"
                                         "sweep-20260929-111500-000001/results.json").read_text())
            for r in resultados_dos:
                r["clocks"]["otro"] = {"constraint": 25, "achieved": 30}
            (dos / "reports/20260929-110000-000000-build/sweep-20260929-111500-000001/"
             "results.json").write_text(json.dumps(resultados_dos))
            texto = io.StringIO()
            with patch.object(sweep_report, "find_repo_root", return_value=raiz), \
                 patch.object(sweep_report, "list_prototypes", return_value=[uno, dos, sin]), \
                 patch.object(sys, "argv", ["sweep_report", "--last"]), \
                 patch.object(sys, "stdout", texto):
                sweep_report.main()
        salida = texto.getvalue()
        self.assertRegex(salida, r"1\.uno\s+20260930-100000\s+20260930-101500\s+2\s+2/2\s+clk\s+84\.00")
        self.assertNotIn("20260929-101500", salida)  # el barrido viejo de 1.uno no sale
        self.assertRegex(salida, r"2\.dos\s+.*\+0\.0 %")
        self.assertRegex(salida, r"1\.uno .*\+5\.0 %")
        self.assertNotIn("3.sin", salida)
        # Una línea en blanco entre prototipos, y ninguna al final.
        lineas = salida.rstrip("\n").split("\n")
        self.assertEqual(lineas.count(""), 1)
        self.assertEqual(lineas[lineas.index("") - 1].split()[0], "1.uno")
        self.assertEqual(lineas[lineas.index("") + 1].split()[0], "2.dos")
        self.assertEqual(sum("2.dos" in linea for linea in lineas), 1)
        self.assertTrue(lineas[-1].lstrip().startswith("otro"))

    def test_list_sin_barridos_lo_dice(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            self.assertIn("No hay barridos", self._correr(Path(temp), "--list"))

    def test_show_detalla_cada_semilla_y_las_que_no_dieron_informe(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            montar_barrido(raiz, "20260929-100000-000000-build", "sweep-20260929-101500-000001",
                           [70, 90], pedidas=[1, 2, 3])
            salida = self._correr(raiz, "--show", "latest")
            por_trozo = self._correr(raiz, "--show", "101500")
        self.assertEqual(salida, por_trozo)
        self.assertRegex(salida, r"1\s+NO\s+clk 70\.00/80 \(-12\.5 %\)")
        self.assertRegex(salida, r"2\s+OK\s+clk 90\.00/80 \(\+12\.5 %\)")
        self.assertIn("Sin informe (nextpnr falló o se interrumpió): seed-3", salida)
        self.assertIn("Cumplen 1 de 2", salida)

    def test_show_con_un_nombre_ambiguo_o_inexistente_se_niega(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            montar_barrido(raiz, "20260929-100000-000000-build", "sweep-20260929-101500-000001", [80, 81])
            montar_barrido(raiz, "20260930-100000-000000-build", "sweep-20260930-101500-000001", [80, 81])
            with self.assertRaises(SystemExit):
                self._correr(raiz, "--show", "101500")
            with self.assertRaises(SystemExit):
                self._correr(raiz, "--show", "no-existe")


if __name__ == "__main__":
    unittest.main()
