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
from run_tests import (
    CAPABILITIES,
    expand_capabilities,
    load_case,
    parse_requires,
    parse_run_until,
)


def _cargar_simulador():
    """El simulador se carga por ruta, como hace el backend."""
    import importlib.util
    from run_tests import REPOSITORY

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
        # `serial` solo lo tiene la CPU (19 y 21); en un caso GPU no es que
        # falte, es que no existe el dispositivo en esa familia.
        with self.assertRaises(ValueError):
            parse_requires({"requires": ["serial"]}, "gpu")

    def test_capacidad_de_las_dos_arquitecturas(self):
        # `video` lo tienen las dos familias, y por eso un caso GPU puede
        # declararlo. Es la condicion para que el mismo programa de video valga
        # en la 21 y en la 22 -- ver docs/unificacion-mmio.md.
        self.assertEqual(parse_requires({"requires": ["video"]}, "cpu"), ["video"])
        self.assertEqual(parse_requires({"requires": ["video"]}, "gpu"), ["video"])

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
        # `read_word` esta en las seis desde la fase 3.4 -- ver
        # test_read_word_en_todas.
        self.assertEqual(fpga.capabilities("ebr"), {"mul_div", "read_word"})
        # La 6 y la 10 no tienen video en absoluto, y la 10 tampoco MUL/DIV.
        self.assertEqual(fpga.capabilities("sdram"), {"read_word"})
        # La 16 tiene video pero no con que capturar.
        self.assertEqual(fpga.capabilities("hdmi"),
                         {"video", "mul_div", "read_word"})
        # La 18 tiene las dos.
        self.assertEqual(
            fpga.capabilities("bl8"),
            {"video", "frame_capture", "mul_div", "read_word"})
        # Y la 19 anade las extensiones de ISA y el puerto serie.
        self.assertEqual(
            fpga.capabilities("subword"),
            {"video", "frame_capture", "subword_memory", "calls", "serial",
             "mul_div", "read_word"})

    def test_read_word_en_todas(self):
        """READ_WORD no es una extension: es parte del contrato del monitor.

        Se detecta del RTL y no se supone por version porque la numeracion no
        es comparable entre familias -la 6 va por 1.x y la 22 por 2.x-, asi que
        "version >= N" no significa nada fuera de una carpeta. Si alguna se
        quedara sin el, `fpga._read_register` volveria a los cuatro READ_BYTE y
        el contador de frames podria salir desgarrado, en silencio; aqui sale
        con nombre.
        """
        sin_ella = [nombre for nombre in fpga.VERSIONS
                    if "read_word" not in fpga.capabilities(nombre)]
        self.assertEqual(sin_ella, [])

    def test_solo_la_10_no_tiene_mul_div(self):
        """`mul_div` es un HUECO, no una extension, y es el unico de la tabla.

        MUL, MULFX y DIV son instrucciones base de la MiniISA. La 10 se quedo
        sin ellas por temporizacion --ver 10.fpga-cpu-ram/cpu.v-- y es la unica.
        Si algun dia las implementa, esta capacidad desaparece entera en vez de
        extenderse a mas backends, que es lo contrario de lo que le pasa a una
        extension.
        """
        sin_ella = [nombre for nombre in fpga.VERSIONS
                    if "mul_div" not in fpga.capabilities(nombre)]
        self.assertEqual(sin_ella, ["sdram"])
        self.assertIn("mul_div", simulator.capabilities())

    def test_alu_extended_implica_mul_div(self):
        """MULHI sale del mismo multiplicador que MUL, y REM del divisor de DIV.

        Un backend con MULHI pero sin MUL no puede existir, asi que declarar
        `alu_extended` basta.
        """
        self.assertEqual(expand_capabilities(["alu_extended"]),
                         {"alu_extended", "mul_div"})
        # Y no al reves: tener MUL no da MULHI.
        self.assertEqual(expand_capabilities(["mul_div"]), {"mul_div"})

    def test_las_extensiones_de_isa_no_se_implican(self):
        """`calls` y `subword_memory` son independientes a proposito.

        Llegaron juntas en la 19, pero son extensiones separadas del mapa de
        opcodes: `0x18..0x1D` una y `0x2C..0x2E` la otra. Un backport a las
        versiones anteriores no tiene por que traer las dos, y encadenarlas
        aqui obligaria a mentir al bitstream que solo tuviera una.
        """
        self.assertEqual(expand_capabilities(["calls"]), {"calls"})
        self.assertEqual(
            expand_capabilities(["subword_memory"]), {"subword_memory"})

    def test_las_extensiones_se_omiten_en_los_bitstreams_anteriores(self):
        """Y el motivo tiene que decir donde SI estan.

        Sin el SKIP, estos casos no fallarian con un diagnostico util en un
        bitstream anterior: pararian con error 0x01, opcode invalido, que es lo
        mismo que produce un ensamblador roto o un salto a datos.
        """
        for capacidad in ("calls", "subword_memory"):
            caso = self._caso([capacidad])
            for version in ("ebr", "sdram", "hdmi", "bl8"):
                motivo = fpga.incompatibility(caso, version)
                self.assertIsNotNone(motivo, f"{capacidad} en {version}")
                self.assertIn(capacidad, motivo)
                self.assertIn("subword", motivo)
            self.assertIsNone(fpga.incompatibility(caso, "subword"))

    def test_el_serie_se_omite_en_los_bitstreams_anteriores(self):
        caso = self._caso(["serial"])
        for version in ("ebr", "sdram", "hdmi", "bl8"):
            motivo = fpga.incompatibility(caso, version)
            self.assertIsNotNone(motivo, f"serial en {version}")
            self.assertIn("serial", motivo)
        self.assertIsNone(fpga.incompatibility(caso, "subword"))

    def test_stdin_y_stdout_exigen_la_capacidad(self):
        """Sin `requires: ["serial"]` el caso se rechaza al CARGAR.

        Si no, un caso de consola pasaria en un backend sin puerto serie
        "comprobando" que no salio nada, que es lo mismo que no comprobar.
        """
        for extra in ({"stdin": "hola"}, {"expect": {"stdout": "hola"}}):
            with self.subTest(extra=extra):
                with tempfile.TemporaryDirectory() as tmp:
                    directorio = Path(tmp)
                    (directorio / "p.bin").write_bytes(b"\x00\x00\x00\xfc")
                    caso = {
                        "architecture": "cpu",
                        "name": "consola",
                        "program": "p.bin",
                        "expect": {"pc": "0x00000004"},
                    }
                    caso.update(extra)
                    if "expect" in extra:
                        caso["expect"]["pc"] = "0x00000004"
                    (directorio / "test.json").write_text(
                        json.dumps(caso), encoding="utf-8")
                    with self.assertRaises(ValueError) as error:
                        load_case(directorio / "test.json")
                self.assertIn("serial", str(error.exception))

    def test_stdin_no_puede_pasar_de_la_cola(self):
        """Mas de 64 bytes exigiria alimentar la cola con la CPU corriendo, y
        entonces lo que se capture depende de lo rapido que vaya."""
        with tempfile.TemporaryDirectory() as tmp:
            directorio = Path(tmp)
            (directorio / "p.bin").write_bytes(b"\x00\x00\x00\xfc")
            (directorio / "test.json").write_text(json.dumps({
                "architecture": "cpu",
                "name": "consola-larga",
                "program": "p.bin",
                "requires": ["serial"],
                "stdin": "x" * 65,
                "expect": {"pc": "0x00000004"},
            }), encoding="utf-8")
            with self.assertRaises(ValueError) as error:
                load_case(directorio / "test.json")
        self.assertIn("determinista", str(error.exception))

    def test_el_simulador_tiene_las_extensiones(self):
        """Va por delante del RTL, como debe: es donde se prueban primero."""
        for capacidad in ("calls", "subword_memory"):
            self.assertIsNone(
                simulator.incompatibility({"requires": [capacidad]}))

    def test_el_simulador_tambien_puede_omitir(self):
        """La comprobacion es real, no un `return None`.

        Hoy el simulador tiene todas las capacidades declaradas, asi que este
        camino no se ejercita con ninguna de ellas. Se comprueba con una
        inventada para que el dia que se anada una capacidad que el simulador
        no tenga, el SKIP funcione en vez de dejar correr el caso a medias.
        """
        motivo = simulator.incompatibility({"requires": ["inventada"]})
        self.assertIsNotNone(motivo)
        self.assertIn("inventada", motivo)

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
                self.assertNotIn("sin video", motivo)

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
        # Ahora el valor es una tupla -- declarar las dos es legitimo (`video`),
        # pero declarar ninguna o una desconocida sigue sin serlo.
        for nombre, arquitecturas in CAPABILITIES.items():
            self.assertIsInstance(arquitecturas, tuple, nombre)
            self.assertTrue(arquitecturas, nombre)
            for arquitectura in arquitecturas:
                self.assertIn(arquitectura, ("cpu", "gpu"), nombre)


if __name__ == "__main__":
    unittest.main()
