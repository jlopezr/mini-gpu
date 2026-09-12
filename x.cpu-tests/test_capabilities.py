"""Pruebas del mecanismo de capacidades.

Un caso declara en `requires` lo que necesita del sistema; cada backend publica
lo que tiene. Esto se puede probar entero sin placa y sin simulador, que es
justo lo que lo hace merecer un fichero propio: el resto de la suite necesita
hardware o al menos construir un backend.

Lo que se comprueba, y por que importa cada cosa:

  - que una capacidad desconocida se rechaza al CARGAR el caso, no al
    ejecutarlo. Un `requires: ["vidio"]` mal escrito que se ignorara en
    silencio haria que el caso pasara en sitios donde no deberia correr;
  - que las capacidades tienen arquitectura, y mezclarlas es un error;
  - que `frame_capture` implica `video`, para que un backend solo declare lo
    que de verdad implementa;
  - que cada bitstream declara lo suyo y el simulador rechaza las graficas;
  - que `run_until.swap` exige `frame_capture`, porque es quien declara que
    existe el registro HALT_AT.
"""

import json
import tempfile
import unittest
from pathlib import Path

from backends import fpga, simulator
from run_gpu_tests import (
    CAPABILITIES,
    expand_capabilities,
    load_case,
    parse_requires,
    parse_run_until,
)


def _cargar_simulador():
    """El simulador se carga por ruta, como hace el backend."""
    import importlib.util
    from run_gpu_tests import REPOSITORY

    ruta = REPOSITORY / "2.cpu-sim-func" / "minicpu_sim.py"
    spec = importlib.util.spec_from_file_location("minicpu_sim_for_caps", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class CapabilitiesTest(unittest.TestCase):

    def test_capacidad_desconocida_se_rechaza_al_cargar(self):
        with self.assertRaises(ValueError) as error:
            parse_requires({"requires": ["vidio"]}, "cpu")
        self.assertIn("vidio", str(error.exception))
        # Y el mensaje dice cuales hay, que es lo unico util cuando te has
        # equivocado escribiendo una.
        self.assertIn("video", str(error.exception))

    def test_capacidad_de_otra_arquitectura(self):
        # `atomic_warp_faults` es de GPU; pedirla en un caso de CPU no es que
        # falte, es que no tiene sentido.
        with self.assertRaises(ValueError):
            parse_requires({"requires": ["atomic_warp_faults"]}, "cpu")
        with self.assertRaises(ValueError):
            parse_requires({"requires": ["video"]}, "gpu")

    def test_repetidas(self):
        with self.assertRaises(ValueError):
            parse_requires({"requires": ["video", "video"]}, "cpu")

    def test_sin_requires(self):
        self.assertEqual(parse_requires({}, "cpu"), [])

    def test_frame_capture_implica_video(self):
        self.assertEqual(
            expand_capabilities(["frame_capture"]), {"frame_capture", "video"})
        # Y no al reves: tener video no da la captura.
        self.assertEqual(expand_capabilities(["video"]), {"video"})

    def test_capacidades_por_bitstream(self):
        # La 6 y la 10 no tienen video en absoluto.
        self.assertEqual(fpga.capabilities("ebr"), frozenset())
        self.assertEqual(fpga.capabilities("sdram"), frozenset())
        # La 16 tiene video pero no con que capturar.
        self.assertEqual(fpga.capabilities("hdmi"), {"video"})
        # La 18 tiene las dos.
        self.assertEqual(fpga.capabilities("bl8"), {"video", "frame_capture"})

    # `incompatibility` mira tambien si el caso cabe en el mapa de memoria, asi
    # que necesita un caso con forma, no solo el `requires`.
    @staticmethod
    def _caso(requires):
        return {
            "requires": requires,
            "program": b"\x00\x00\x00\xfc",
            "initial_memory": [],
            "expected": {"memory": {}},
        }

    def test_un_caso_de_video_se_omite_donde_no_lo_hay(self):
        caso = self._caso(["video"])
        for version in ("ebr", "sdram"):
            motivo = fpga.incompatibility(caso, version)
            self.assertIsNotNone(motivo)
            self.assertIn("video", motivo)
        # Donde si lo hay, la capacidad no puede ser el motivo. Podria haberlo
        # por otra cosa, asi que se comprueba que no habla de capacidades.
        for version in ("hdmi", "bl8"):
            motivo = fpga.incompatibility(caso, version)
            if motivo is not None:
                self.assertNotIn("no tiene", motivo)

    def test_captura_solo_en_la_18(self):
        caso = self._caso(["frame_capture"])
        motivo = fpga.incompatibility(caso, "hdmi")
        self.assertIsNotNone(motivo)
        self.assertIn("frame_capture", motivo)
        # El motivo tiene que decir donde SI esta, que es lo que uno quiere
        # saber al leer el SKIP.
        self.assertIn("bl8", motivo)

    def test_el_simulador_acepta_video(self):
        """Desde que `minicpu_sim.py` tiene `VideoDevice`, los acepta.

        Antes los rechazaba, y este test comprobaba el rechazo. Ahora comprueba
        lo contrario, que es lo que permite correr los casos de video sin placa.
        """
        for capacidad in ("video", "frame_capture"):
            self.assertIsNone(
                simulator.incompatibility({"requires": [capacidad]}))
        self.assertIsNone(simulator.incompatibility({"requires": []}))

    def test_el_simulador_no_modela_el_tiempo(self):
        """Y esto es la letra pequena de lo anterior.

        El simulador valida QUE dibuja un programa, no CUANDO. No hay barrido
        leyendo la memoria por su cuenta, asi que `underflow` no puede ocurrir:
        es siempre cero, pase lo que pase.

        Se comprueba explicitamente para que quede constancia de que un verde
        del simulador en `expect.video.underflow` no significa que eso se haya
        probado. Solo significa algo en hardware.
        """
        modulo = _cargar_simulador()
        video = modulo.VideoDevice()
        # Ni siquiera pidiendo intercambios sin parar.
        for _ in range(10):
            video.write(video.SWAP, 1)
            for _ in range(video.frame_instructions):
                video.tick()
        self.assertEqual(video.swap_count, 10)
        self.assertEqual(video.read(video.STATUS) & 1, 0)

    def test_el_reloj_de_frames_es_sintetico_pero_coherente(self):
        """El periodo no cambia lo que ve un programa que SINCRONIZA.

        Es la propiedad que hace legitimo que el simulador declare
        `frame_capture`: un programa que espera a que su intercambio se aplique
        --todos los de cases/video-- nunca dibuja con uno pendiente, asi que la
        secuencia de frames es la misma sea cual sea el periodo. Lo unico que
        cambia es cuantas vueltas da el bucle de espera.
        """
        modulo = _cargar_simulador()
        for periodo in (1, 7, 1000):
            video = modulo.VideoDevice(frame_instructions=periodo)
            frentes = []
            for _ in range(4):
                video.write(video.SWAP, 1)
                # Como haria el programa: esperar a que se aplique.
                guarda = 0
                while video.read(video.SWAP) and guarda < 10000:
                    video.tick()
                    guarda += 1
                frentes.append(video.fb_front)
            self.assertEqual(video.swap_count, 4, f"periodo {periodo}")
            # La secuencia de buffers visibles es la misma con cualquier periodo.
            self.assertEqual(
                frentes,
                [0x0102_5800, 0x0100_0000, 0x0102_5800, 0x0100_0000],
                f"periodo {periodo}")

    def test_run_until_exige_frame_capture(self):
        with self.assertRaises(ValueError) as error:
            parse_run_until({"run_until": {"swap": 4}}, ["video"])
        self.assertIn("frame_capture", str(error.exception))
        self.assertEqual(
            parse_run_until({"run_until": {"swap": 4}}, ["frame_capture"]),
            {"swap": 4})

    def test_run_until_mal_formado(self):
        for malo in ({"swap": 0}, {"swap": "4"}, {"frame": 4}, {"swap": 4, "x": 1}):
            with self.assertRaises(ValueError):
                parse_run_until({"run_until": malo}, ["frame_capture"])
        self.assertIsNone(parse_run_until({}, []))

    @staticmethod
    def _escribir_caso(directorio, **extra):
        (directorio / "p.bin").write_bytes(b"\x00\x00\x00\xfc")
        caso = {
            "architecture": "cpu",
            "name": "video-demo",
            "program": "p.bin",
            "requires": ["frame_capture"],
            "run_until": {"swap": 4},
            "expect": {},
        }
        caso.update(extra)
        (directorio / "test.json").write_text(
            json.dumps(caso), encoding="utf-8")
        return directorio / "test.json"

    def test_caso_completo_de_video(self):
        """Un caso de verdad, cargado desde disco como lo hace el runner."""
        with tempfile.TemporaryDirectory() as tmp:
            caso = load_case(self._escribir_caso(Path(tmp)))
        self.assertEqual(caso["requires"], ["frame_capture"])
        self.assertEqual(caso["run_until"], {"swap": 4})
        # Sin `run_until`, el PC es obligatorio para un caso de CPU; con el, no
        # puede estar. Aqui se comprueba que efectivamente no quedo puesto.
        self.assertNotIn("pc", caso["expected"])

    def test_run_until_prohibe_declarar_pc(self):
        """La parada de HALT_AT es asincrona: el PC queda donde pille.

        Aceptar un `expect.pc` junto a `run_until` daria un caso que pasa o
        falla segun lo rapido que vaya la CPU ese dia. Es mejor rechazarlo al
        cargar que dejar que alguien persiga un fallo intermitente.
        """
        with tempfile.TemporaryDirectory() as tmp:
            ruta = self._escribir_caso(
                Path(tmp), expect={"pc": "0x00000004"})
            with self.assertRaises(ValueError) as error:
                load_case(ruta)
        self.assertIn("asincrona", str(error.exception))

    def test_expectativas_de_video_exigen_la_capacidad(self):
        """Pedir `underflow` sin declarar `video` seria un caso que no prueba
        nada allí donde no hay vídeo: se rechaza al cargar."""
        with tempfile.TemporaryDirectory() as tmp:
            ruta = self._escribir_caso(
                Path(tmp),
                requires=[],
                run_until=None,
                expect={"pc": "0x00000004", "video": {"underflow": False}})
            # `run_until: null` no es valido; se quita del JSON.
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            del datos["run_until"]
            ruta.write_text(json.dumps(datos), encoding="utf-8")
            with self.assertRaises(ValueError) as error:
                load_case(ruta)
        self.assertIn("video", str(error.exception))

    def test_todas_las_capacidades_tienen_arquitectura(self):
        # Una capacidad nueva sin arquitectura declarada se colaria en casos de
        # las dos, que es justo lo que este diccionario existe para impedir.
        for nombre, arquitectura in CAPABILITIES.items():
            self.assertIn(arquitectura, ("cpu", "gpu"), nombre)


if __name__ == "__main__":
    unittest.main()
