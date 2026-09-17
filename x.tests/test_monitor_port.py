"""Deteccion de puerto serie, sin hardware.

`tools/run_board.py` ya filtraba por fabricante, pero los trece `monitor.py` y
`profile.py` iban por su cuenta y cogian el primer puerto del SISTEMA. Eso fallo
de la peor manera posible: con la placa desenchufada la lista empezaba por el
puerto serie de la placa base y dos enlaces Bluetooth, y el sintoma era un
timeout de escritura -- que se parece mucho a "la FPGA no tiene monitor" y nada
a "no has enchufado la placa".

Ahora la logica vive UNA vez en tools/serial_ports.py y los monitores la
importan.
"""

import importlib.util
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import serial_ports  # noqa: E402
from backends import board  # noqa: E402


def fake_port(device, vid):
    return SimpleNamespace(device=device, description="serial", vid=vid)


# El orden real que tenia la maquina el dia que esto se rompio: la placa NO es
# el primer puerto, y los dos del medio son Bluetooth.
REAL_WORLD = [
    fake_port("COM1", vid=None),
    fake_port("COM6", vid=0x0A5C),
    fake_port("COM8", vid=0x0A5C),
    fake_port("COM3", vid=serial_ports.FTDI_VENDOR_ID),
]


class DetectPortTest(unittest.TestCase):
    def test_picks_the_ftdi_port_not_the_first_one(self):
        with mock.patch("serial.tools.list_ports.comports", return_value=REAL_WORLD):
            self.assertEqual(serial_ports.detect_port(), "COM3")

    def test_no_ftdi_says_the_board_is_not_connected(self):
        ports = [p for p in REAL_WORLD if p.vid != serial_ports.FTDI_VENDOR_ID]
        with mock.patch("serial.tools.list_ports.comports", return_value=ports):
            with self.assertRaises(serial_ports.PortError) as caught:
                serial_ports.detect_port()
        self.assertIn("no esta conectada", str(caught.exception))

    def test_several_ftdi_asks_which_one(self):
        ports = [
            fake_port("COM3", vid=serial_ports.FTDI_VENDOR_ID),
            fake_port("COM4", vid=serial_ports.FTDI_VENDOR_ID),
        ]
        with mock.patch("serial.tools.list_ports.comports", return_value=ports):
            with self.assertRaises(serial_ports.PortError) as caught:
                serial_ports.detect_port()
        self.assertIn("--port", str(caught.exception))

    def test_available_ports_marks_the_board(self):
        with mock.patch("serial.tools.list_ports.comports", return_value=REAL_WORLD):
            listing = serial_ports.available_ports()
        self.assertIn("COM3 (FTDI)", listing)
        self.assertNotIn("COM1 (FTDI)", listing)

    def test_agrees_with_the_copy_in_backends(self):
        """backends/board.py tiene su propia copia y tiene que decir lo mismo.

        Son dos a proposito: x.tests no depende de tools/ (la dependencia va al
        reves), y board.py recibe el monitor.py del prototipo como modulo, asi
        que un import desde el monitor haria un ciclo.
        """
        self.assertEqual(serial_ports.FTDI_VENDOR_ID, board.FTDI_VENDOR_ID)
        with mock.patch("serial.tools.list_ports.comports", return_value=REAL_WORLD):
            self.assertEqual(serial_ports.detect_port(), board.detect_port())


def load_monitor(prototype_dir: Path):
    path = prototype_dir / "monitor.py"
    spec = importlib.util.spec_from_file_location(
        "monitor_" + prototype_dir.name.replace(".", "_").replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    # Registrarlo ANTES de ejecutarlo: @dataclass mira sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MONITORS = sorted(ROOT.glob("*/monitor.py"), key=lambda p: p.parent.name)


class EveryMonitorTest(unittest.TestCase):
    """Los trece monitores, no solo el ultimo.

    El fallo original estaba en los trece a la vez; una prueba que solo mire el
    prototipo en el que se trabaja hoy no habria dicho nada.
    """

    def test_there_are_monitors_to_check(self):
        self.assertGreaterEqual(len(MONITORS), 13)

    def test_all_share_the_common_detection(self):
        for path in MONITORS:
            with self.subTest(prototype=path.parent.name):
                module = load_monitor(path.parent)
                self.assertIs(module.detect_port, serial_ports.detect_port)
                self.assertIs(module.available_ports, serial_ports.available_ports)

    def test_none_defaults_to_a_hardcoded_com_port(self):
        for path in MONITORS:
            with self.subTest(prototype=path.parent.name):
                self.assertNotIn('default="COM3"', path.read_text(encoding="utf8"))


GPU_PROTOTYPES = (
    "12.fpga-gpu",
    "14.fpga-gpu-ram",
    "17.fpga-gpu-ram-v2",
    "22.fpga-gpu-bl8",
)

# Las CPU que tienen ventana MMIO, y por tanto bloque de identificacion. La 6 y
# la 10 no estan porque no la tienen -- no es que les falte un dispositivo, es
# que el concepto no existe en su RTL. Ver docs/unificacion-mmio.md, fase 4a.
CPU_CON_MMIO = (
    "16.fpga-cpu-hdmi",
    "18.fpga-cpu-hdmi-bl8",
    "19.fpga-cpu-hdmi-ls",
    "21.fpga-cpu-hdmi-alu",
)

# Una ranura de ventana sin usar. La base es inalcanzable para una direccion de
# 32 bits, asi que la comparacion nunca se cumple.
UNUSED_WINDOW = (0x1_FFFF_FFFF, 0x0)

PARAMETER = re.compile(r"\.(\w+)\(33'h([0-9a-fA-F_]+)\)")
# La version tambien: divergio entre top_bl8.v y el banco de regiones sin que
# nada saltara, y rtl_facts leia la del banco por ir antes alfabeticamente.
VERSION_PARAMETER = re.compile(r"\.(VERSION_\w+)\(8'h([0-9a-fA-F]+)\)")


def monitor_instantiations(prototype: Path):
    """Los parametros de cada `monitor #(...)` del prototipo, por fichero."""
    for path in sorted(prototype.glob("*.v")):
        if path.name == "monitor.v":
            continue        # ahi el `#(` es la DECLARACION, no una instancia
        source = path.read_text(encoding="utf8")
        for match in re.finditer(r"\bmonitor\s*#\(", source):
            # emparejar parentesis: la lista lleva unos cuantos dentro
            depth, cursor = 1, match.end()
            while depth and cursor < len(source):
                depth += {"(": 1, ")": -1}.get(source[cursor], 0)
                cursor += 1
            lista = source[match.end():cursor]
            values = {
                name: int(digits.replace("_", ""), 16)
                for name, digits in PARAMETER.findall(lista)
            }
            values.update({
                name: int(digits, 16)
                for name, digits in VERSION_PARAMETER.findall(lista)
            })
            yield path, values


def rtl_windows(values: dict) -> set:
    windows = set()
    for slot in range(5):
        window = (values[f"WINDOW{slot}_BASE"], values[f"WINDOW{slot}_END"])
        if window != UNUSED_WINDOW:
            windows.add(window)
    return windows


class SharedMonitorTest(unittest.TestCase):
    """Los cuatro monitor.v de la familia GPU son COPIA IDENTICA.

    Se decidio copia y no fichero compartido para que cada carpeta siga siendo
    autocontenida. Lo que antes los diferenciaba --version, tamano de RAM y la
    lista de ventanas MMIO-- son ahora parametros que pone el top, asi que no
    queda ninguna razon legitima para que el texto difiera. Si diverge otra vez,
    salta aqui.
    """

    def test_las_cuatro_copias_son_identicas(self):
        canonical = (ROOT / "22.fpga-gpu-bl8" / "monitor.v").read_bytes()
        for name in GPU_PROTOTYPES:
            with self.subTest(prototype=name):
                self.assertEqual((ROOT / name / "monitor.v").read_bytes(), canonical)


class MonitorVersionTest(unittest.TestCase):
    """rtl_facts tiene que leer la version que se SINTETIZA.

    Al parametrizar monitor.v, lo que hay dentro del fichero paso a ser el valor
    por DEFECTO y el de verdad lo pone el top. rtl_facts seguia leyendo el
    localparam y devolvia 2.4 para las cuatro GPU cuando eran 2.5, 2.6, 2.6 y
    2.6. Despues, al mirar la instanciacion, cogia la del banco de pruebas por
    ir antes alfabeticamente que top.v.
    """

    def test_la_version_sale_del_top_y_no_del_defecto(self):
        from tools.rtl_facts import monitor_version_from_rtl

        for name in GPU_PROTOTYPES:
            prototype = ROOT / name
            tops = [
                values for path, values in monitor_instantiations(prototype)
                if not path.name.endswith("_tb.v")
            ]
            self.assertTrue(tops, f"{name} no tiene top que instancie monitor")
            esperado = (tops[0]["VERSION_MAJOR"], tops[0]["VERSION_MINOR"])
            with self.subTest(prototype=name):
                self.assertEqual(monitor_version_from_rtl(prototype), esperado)


class SysIdTest(unittest.TestCase):
    """SYS_ID tiene que ser el numero de la carpeta.

    Es lo que hace que "obligatorio" signifique algo dentro de seis meses. El ID
    sale del nombre del directorio, asi que no hay registro central que
    mantener, pero tampoco hay nada que impida teclearlo mal: esto lo impide.
    """

    FOLDER = re.compile(r"sysid\s*#\(\s*\.FOLDER\(8'd(\d+)\)")
    # En CPU el `sysid` vive DENTRO de `mmio_decoder`, asi que el numero de
    # carpeta viaja por el parametro del decodificador y no por el del bloque.
    FOLDER_CPU = re.compile(r"mmio_decoder\s*#\(\s*\.FOLDER\(8'd(\d+)\)")

    def test_el_id_es_el_numero_de_carpeta(self):
        for name in GPU_PROTOTYPES:
            esperado = int(name.split(".")[0])
            encontrados = []
            for path in sorted((ROOT / name).glob("*.v")):
                if path.name == "sysid.v":
                    continue        # ahi el `#(` es la DECLARACION
                encontrados += [
                    int(d) for d in self.FOLDER.findall(
                        path.read_text(encoding="utf8"))
                ]
            with self.subTest(prototype=name):
                self.assertTrue(encontrados, f"{name} no instancia sysid")
                self.assertEqual(set(encontrados), {esperado})

    # bit 0 MUL, bit 1 DIV, bit 2 subword, bit 3 SIMT. El fichero donde vive
    # cada uno importa: SSY/BAR/EXIT se decodifican en gpu_sm.v y NO en
    # gpu_lane.v, cosa que ya se presto a mirar el fichero equivocado.
    RASGOS = (
        (0, "gpu_lane.v", re.compile(r"OPCODE_MUL\b")),
        (1, "gpu_lane.v", re.compile(r"OPCODE_DIV\b")),
        (2, "gpu_lane.v", re.compile(r"OPCODE_LOADB|OPCODE_STOREB")),
        (3, "gpu_sm.v", re.compile(r"6'h31")),
    )
    PROFILE = re.compile(r"\.ISA_PROFILE\(32'h([0-9a-fA-F_]+)\)")

    def test_el_perfil_de_isa_sale_del_rtl(self):
        """Escrito a mano pero CONTRASTADO. Si alguien anade subword a un lane y
        no toca el perfil, el bloque de identificacion mentiria en silencio."""
        for name in GPU_PROTOTYPES:
            prototype = ROOT / name
            esperado = 0
            for bit, fichero, patron in self.RASGOS:
                ruta = prototype / fichero
                if ruta.exists() and patron.search(ruta.read_text(encoding="utf8")):
                    esperado |= 1 << bit

            declarados = set()
            for path in sorted(prototype.glob("*.v")):
                if path.name == "sysid.v":
                    continue
                declarados |= {
                    int(d.replace("_", ""), 16)
                    for d in self.PROFILE.findall(path.read_text(encoding="utf8"))
                }
            with self.subTest(prototype=name):
                self.assertEqual(declarados, {esperado},
                                 f"{name}: el RTL dice {esperado:#06x}")

    def test_sysid_es_copia_identica(self):
        canonical = (ROOT / "22.fpga-gpu-bl8" / "sysid.v").read_bytes()
        for name in GPU_PROTOTYPES + CPU_CON_MMIO + ("6.fpga-cpu",
                                                     "10.fpga-cpu-ram"):
            with self.subTest(prototype=name):
                self.assertEqual((ROOT / name / "sysid.v").read_bytes(), canonical)

    def test_el_id_es_el_numero_de_carpeta_sin_mmio(self):
        """6 y 10 instancian `sysid` DIRECTAMENTE en el top, no dentro de un
        decodificador que no tienen, asi que se comprueban con el mismo patron
        que la familia GPU."""
        for name in ("6.fpga-cpu", "10.fpga-cpu-ram"):
            esperado = int(name.split(".")[0])
            encontrados = []
            for path in sorted((ROOT / name).glob("*.v")):
                if path.name == "sysid.v":
                    continue        # ahi el `#(` es la DECLARACION
                encontrados += [
                    int(d) for d in self.FOLDER.findall(
                        path.read_text(encoding="utf8"))
                ]
            with self.subTest(prototype=name):
                self.assertTrue(encontrados, f"{name} no instancia sysid")
                self.assertEqual(set(encontrados), {esperado})

    def test_el_id_es_el_numero_de_carpeta_en_cpu(self):
        for name in CPU_CON_MMIO:
            esperado = int(name.split(".")[0])
            encontrados = []
            for path in sorted((ROOT / name).glob("*.v")):
                if path.name == "sysid.v":
                    continue
                encontrados += [
                    int(d) for d in self.FOLDER_CPU.findall(
                        path.read_text(encoding="utf8"))
                ]
            with self.subTest(prototype=name):
                self.assertTrue(encontrados, f"{name} no instancia mmio_decoder con FOLDER")
                self.assertEqual(set(encontrados), {esperado})

    # En CPU los rasgos viven en `cpu.v`, y el bit 3 NO se deriva: ver abajo.
    RASGOS_CPU = (
        (0, re.compile(r"OPCODE_MUL\b")),
        (1, re.compile(r"OPCODE_DIV\b")),
        (2, re.compile(r"OPCODE_LOADB|OPCODE_STOREB")),
    )

    def test_el_perfil_de_isa_de_cpu_sale_del_rtl_menos_el_bit_simt(self):
        """El bit 3 es CERO en CPU, y no por descuido.

        `OPCODE_SSY` casa hoy en las seis CPU, pero como NO-OP: se anadieron
        para poder compartir binarios con la GPU y no hay pila de reconvergencia
        detras. Derivar el bit con la misma regla que en GPU encenderia el bit y
        el bloque de identificacion diria al host que este nucleo diverge y
        reconverge, que es falso. De ahi que la regla de CPU sea otra, y que
        este test lo diga en vez de dejarlo al criterio de quien lo lea.
        """
        for name in CPU_CON_MMIO:
            prototype = ROOT / name
            cpu = (prototype / "cpu.v").read_text(encoding="utf8")
            esperado = 0
            for bit, patron in self.RASGOS_CPU:
                if patron.search(cpu):
                    esperado |= 1 << bit
            self.assertTrue(re.search(r"OPCODE_SSY\b", cpu),
                            f"{name}: si SSY desaparece, revisar este test")

            declarados = set()
            for path in sorted(prototype.glob("*.v")):
                if path.name == "sysid.v":
                    continue
                declarados |= {
                    int(d.replace("_", ""), 16)
                    for d in self.PROFILE.findall(path.read_text(encoding="utf8"))
                }
            with self.subTest(prototype=name):
                self.assertEqual(declarados, {esperado},
                                 f"{name}: el RTL dice {esperado:#06x}")
                self.assertFalse(esperado & 0b1000,
                                 f"{name}: el bit SIMT no va en CPU")


class SysIdObligatorioTest(unittest.TestCase):
    """Toda carpeta con juego de comandos tiene bloque de identificacion.

    La regla ERA "donde hay ventana MMIO", y 6 y 10 quedaban fuera porque en su
    RTL no existe el concepto. Dejo de valer al renumerar las versiones de
    monitor por JUEGO DE COMANDOS: con eso 6 y 10 contestan lo mismo, y la
    version --que era lo unico que las distinguia, 1.17 contra 1.18-- deja de
    identificar la placa. Sin SYS_ID, `--version ebr` daria por buena una 10
    flasheada y se medirian las prestaciones del hardware equivocado, que es
    literalmente el fallo que SYS_ID existe para cerrar.

    Lo que 6 y 10 NO ganan es MMIO. Su `sysid` cuelga del camino del MONITOR:
    la CPU no lo ve, no hay pagina de dispositivos y un programa no puede
    leerlo, asi que la leccion de esas carpetas --memoria plana, sin
    perifericos-- se queda intacta. Identidad si, dispositivos no.
    """

    PREFIJO_MMIO = re.compile(r"MMIO_PREFIX|mmio\s*=\s*address\[31:13\]")
    SIN_MMIO = ("6.fpga-cpu", "10.fpga-cpu-ram")

    def test_toda_carpeta_con_juego_de_comandos_tiene_sysid(self):
        for name in GPU_PROTOTYPES + CPU_CON_MMIO + self.SIN_MMIO:
            prototype = ROOT / name
            with self.subTest(prototype=name):
                self.assertTrue((prototype / "sysid.v").exists(),
                                f"{name} no tiene sysid.v")

    def test_la_identificacion_no_le_da_mmio_a_la_6_ni_a_la_10(self):
        """Que el bloque entre por la puerta pequena y no arrastre una pagina
        de dispositivos detras."""
        for name in self.SIN_MMIO:
            prototype = ROOT / name
            tiene_ventana = any(
                self.PREFIJO_MMIO.search(path.read_text(encoding="utf8"))
                for path in prototype.glob("*.v")
                if not path.name.endswith("_tb.v"))
            with self.subTest(prototype=name):
                self.assertFalse(tiene_ventana,
                                 f"{name} ha ganado una ventana MMIO")
                self.assertFalse((prototype / "mmio_decoder.v").exists())


class MonitorRegionsTest(unittest.TestCase):
    """Las ventanas del cliente tienen que ser las mismas que las del RTL.

    La lista vive DOS veces: en Python (MONITOR_REGIONS) y en los parametros que
    el top pasa al monitor. Anadir una ventana en un sitio y no en el otro es
    exactamente lo que dejo 0x200 y 0x300 rechazados en placa mientras en
    simulacion todo pasaba.
    """

    def test_python_and_rtl_agree(self):
        for name in GPU_PROTOTYPES:
            prototype = ROOT / name
            esperadas = set(load_monitor(prototype).MONITOR_REGIONS)
            instancias = list(monitor_instantiations(prototype))
            self.assertTrue(instancias, f"{name} no instancia monitor con parametros")
            for path, values in instancias:
                with self.subTest(prototype=name, fichero=path.name):
                    self.assertEqual(rtl_windows(values), esperadas)

    def test_todas_las_instancias_de_un_prototipo_coinciden(self):
        """La 22 tiene dos tops y un banco de pruebas; los tres han de decir lo
        mismo, o se depura un mapa que no es el que esta sintetizado."""
        for name in GPU_PROTOTYPES:
            with self.subTest(prototype=name):
                valores = [v for _, v in monitor_instantiations(ROOT / name)]
                for otros in valores[1:]:
                    self.assertEqual(otros, valores[0])


class BasesDeFramebufferTest(unittest.TestCase):
    """Las bases de framebuffer arrancan a cero, en las TRES copias del dato.

    Hasta la fase 3.5 el reset dejaba `0x01000000` y `0x01025800` cableados. Se
    quitaron porque la unica ventaja --que un programa dibujara sin configurar
    nada-- desaparecio al arrancar en PATTERN: quien quiera que se vea lo que
    dibuja tiene que escribir VIDEO_CTRL de todas formas. Y `0x01000000` no es
    valida en todos los mapas: en la 12, con 128 KiB de EBR, cae fuera.

    El dato vive en tres sitios independientes --el RTL, el simulador funcional
    de CPU y el de GPU-- y el riesgo es moverlos por separado: si un simulador
    regalase una base que el hardware no da, un programa que la heredase
    pasaria en simulacion y fallaria en la placa. El fallo apareceria como un
    framebuffer en la direccion cero, o sea el programa dibujandose encima.
    Esto es lo que impide que se separen.

    La direccion que elige el ARNES para los casos es otra cosa y sigue viva,
    en `backends/video_layout.py`: ahi es una decision de las pruebas, no un
    valor de encendido del hardware.
    """

    PARAMETRO = re.compile(
        r"parameter\s*\[31:0\]\s*(FB_(?:FRONT|BACK)_RESET)\s*=\s*32'h([0-9a-fA-F_]+)")

    def test_el_rtl_resetea_las_bases_a_cero(self):
        for name in CPU_CON_MMIO:
            ruta = ROOT / name / "video_registers.v"
            encontrados = self.PARAMETRO.findall(ruta.read_text(encoding="utf8"))
            with self.subTest(prototype=name):
                self.assertEqual(len(encontrados), 2, f"{name}: no veo los dos parametros")
                for parametro, digits in encontrados:
                    self.assertEqual(int(digits.replace("_", ""), 16), 0,
                                     f"{name}: {parametro} no es cero")

    def test_los_simuladores_arrancan_igual_que_el_rtl(self):
        import inspect

        for carpeta, modulo in (("2.cpu-sim-func", "minicpu_sim"),
                                ("11.gpu-sim-func", "minigpu_sim")):
            cargado = load_simulator(ROOT / carpeta / f"{modulo}.py", modulo)
            firma = inspect.signature(cargado.VideoDevice.__init__)
            with self.subTest(simulador=carpeta):
                self.assertEqual(firma.parameters["fb_front"].default, 0)
                self.assertEqual(firma.parameters["fb_back"].default, 0)
                # Y comprobado construyendolo, no solo leyendo la firma: un
                # `__init__` que ignorase el argumento pasaria lo de arriba.
                dispositivo = cargado.VideoDevice()
                self.assertEqual(dispositivo.fb_front, 0)
                self.assertEqual(dispositivo.fb_back, 0)


def load_simulator(path: Path, name: str):
    # `minigpu_sim` importa `gpu_trace` por nombre, asi que su carpeta tiene que
    # estar en el camino antes de cargarlo.
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    interno = f"{name}_para_bases"
    spec = importlib.util.spec_from_file_location(interno, path)
    module = importlib.util.module_from_spec(spec)
    # Registrarlo ANTES de ejecutarlo. `@dataclass` busca el modulo de la clase
    # en `sys.modules` mientras la procesa, y si no esta revienta con un
    # AttributeError sobre None que no dice nada del problema real.
    sys.modules[interno] = module
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
