"""Backend de FPGA basado en el cliente del monitor UART."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
from pathlib import Path
from types import ModuleType

from . import board, video_stop

_REPOSITORY = Path(__file__).resolve().parents[2]
if str(_REPOSITORY) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY))

from tools.rtl_facts import (  # noqa: E402 (necesita _REPOSITORY en sys.path)
    backend_from_rtl,
    capabilities_from_rtl,
    clock_hz_from_rtl,
    load_capability_signals,
    monitor_version_from_rtl,
    monitor_cycle_counters_from_rtl,
    readme_title,
)


# Ni siquiera la lista de versiones se declara aquí: cada versión es una
# carpeta de prototipo con un `version.json` (`{"alias": ...}`, y opcionalmente
# `"description"` si el título del README no basta). Eso es lo único que se
# elige a mano; todo lo demás --`monitor_version`, `capabilities`, `clock_hz`,
# `monitor_cycle_counters`, y la descripción por defecto-- se lee de esa carpeta
# al importar este módulo, con las mismas funciones que usa
# `tools/prototype_report.py` (`tools/rtl_facts.py`).
#
# Registrar una versión nueva es soltar `version.json` en su carpeta: no hace
# falta tocar este fichero. Un `cpu.v`/`monitor.v` sin `version.json` NO
# cuenta -es la señal de "esto es un target de test soportado", no solo "hay
# RTL sintetizable ahí": `17.fpga-gpu-ram-v2` tiene ambos y no es un target,
# es un camino crítico alternativo de la 14.
#
# `R0` CABLEADO A CERO NO ES UNA CAPACIDAD. Lo fue mientras solo lo tenia la 21;
# con el backport hecho lo tienen las seis versiones, asi que paso a ser una
# regla de la MiniISA --1.isa/isa.md seccion 1-- y dejo de ser algo que un
# backend pueda o no tener. La capacidad `zero_register` ya no existe.
def _prototype_number(directory: Path) -> int:
    match = re.match(r"(\d+)", directory.name)
    return int(match.group(1)) if match else 0


def _build_versions() -> dict:
    signals = load_capability_signals(_REPOSITORY)
    manifests = sorted(
        _REPOSITORY.glob("*/version.json"), key=lambda p: _prototype_number(p.parent)
    )
    versions = {}
    for manifest_path in manifests:
        directory = manifest_path.parent
        if backend_from_rtl(directory) != "cpu":
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        monitor_version = monitor_version_from_rtl(directory)
        if monitor_version is None:
            raise RuntimeError(
                f"no se pudo leer VERSION_MAJOR/VERSION_MINOR de "
                f"{directory / 'monitor.v'}"
            )
        entry = {
            "monitor_path": directory.relative_to(_REPOSITORY) / "monitor.py",
            "monitor_version": monitor_version,
            "description": manifest.get("description") or readme_title(directory),
            "capabilities": capabilities_from_rtl(directory, signals),
        }
        clock_hz = clock_hz_from_rtl(directory)
        if clock_hz is not None:
            entry["clock_hz"] = clock_hz
        if monitor_cycle_counters_from_rtl(directory):
            entry["monitor_cycle_counters"] = True
        versions[manifest["alias"]] = entry
    return versions


VERSIONS = _build_versions()
DEFAULT_VERSION = "alu"

# Registros de video, en direcciones de byte. Solo los usan las versiones que
# declaran `video`; estan aqui y no en el monitor porque son del sistema, no
# del protocolo.
# Las direcciones salen del mapa generado (`1.isa/mmio.md` §20), no escritas a
# mano: eran una cuarta copia junto al decodificador Verilog, `monitor.py` y
# cada `.asm`. De momento es el mapa de TRANSICION --bases de v2, offsets de
# v1-- porque `video_registers.v` aun no ha movido sus registros.
#
# AVISO PARA LAS OTRAS NUEVE CARPETAS: este fichero lo comparten todos los
# prototipos con placa. Al cambiarlo, los bitstreams de 6, 10, 16, 18 y 19
# --que siguen en v1-- dejan de responder donde el arnes los busca, hasta que
# se migren. Es sabido y aceptado, no una regresion.
from tools.mmio_map import (  # noqa: E402
    MMIO_VIDEO_BASE, MMIO_VIDEO_FB_FRONT_OFF, MMIO_VIDEO_FB_BACK_OFF,
    MMIO_VIDEO_STATUS_OFF, MMIO_VIDEO_SWAP_COUNT_OFF, MMIO_VIDEO_HALT_AT_OFF,
    MMIO_VIDEO_CTRL_OFF, MMIO_CPU_PERF_BASE, MMIO_PERF_CYCLES_OFF,
    MMIO_PERF_RETIRED_OFF, MMIO_VIDEO_FRAME_COUNT_OFF,
    MMIO_VIDEO_HALT_TARGET_OFF,
    MMIO_PERF_IMEM_HITS_OFF, MMIO_PERF_IMEM_MISSES_OFF, MMIO_PERF_MEM_TX_OFF,
    MMIO_PERF_STALL_MEM_OFF, MMIO_PERF_STALL_FETCH_OFF, MMIO_PERF_STALL_MMIO_OFF,
)

VIDEO_FB_FRONT = MMIO_VIDEO_BASE + MMIO_VIDEO_FB_FRONT_OFF
VIDEO_FB_BACK = MMIO_VIDEO_BASE + MMIO_VIDEO_FB_BACK_OFF
VIDEO_STATUS = MMIO_VIDEO_BASE + MMIO_VIDEO_STATUS_OFF
VIDEO_SWAP_COUNT = MMIO_VIDEO_BASE + MMIO_VIDEO_SWAP_COUNT_OFF
VIDEO_HALT_AT = MMIO_VIDEO_BASE + MMIO_VIDEO_HALT_AT_OFF
# En v2 los frames tienen registro propio de 32 bits. Ya NO estan en STATUS[31:16]:
# leerlos de ahi da cero siempre, que es lo que este fichero hacia hasta hoy.
VIDEO_FRAME_COUNT = MMIO_VIDEO_BASE + MMIO_VIDEO_FRAME_COUNT_OFF
# Quien se para cuando salta la alarma. Arranca a CERO, o sea que armar HALT_AT
# y no escribir esto --que era suficiente en v1-- no detiene a nadie.
VIDEO_HALT_TARGET = MMIO_VIDEO_BASE + MMIO_VIDEO_HALT_TARGET_OFF
VIDEO_HALT_TARGET_CPU = 1 << 0
VIDEO_CTRL = MMIO_VIDEO_BASE + MMIO_VIDEO_CTRL_OFF
# Modos de salida. Tras el reset la placa arranca en PATTERN --ver
# video_registers.v-- y el arnes enciende SCANOUT antes de cada caso de video.
MODE_BLANK = 0
MODE_PATTERN = 1
MODE_SCANOUT = 2
# Contadores de rendimiento. Los MISMOS offsets que en la MiniGPU: el bloque de
# CPU es un prefijo del de GPU, con CYCLES en +0x00 y RETIRED en +0x04.
PERF_CYCLES = MMIO_CPU_PERF_BASE + MMIO_PERF_CYCLES_OFF
PERF_RETIRED = MMIO_CPU_PERF_BASE + MMIO_PERF_RETIRED_OFF
# Los contadores de espera (capacidad `perf_stalls`, mmio.md §13.2). Con
# CYCLES se reparte el tiempo: CYCLES = calculo + STALL_MEM + STALL_MMIO, y de
# STALL_MEM se separan la busqueda (STALL_FETCH) y los datos (el resto).
PERF_STALL_COUNTERS = {
    "imem_hits": MMIO_CPU_PERF_BASE + MMIO_PERF_IMEM_HITS_OFF,
    "imem_misses": MMIO_CPU_PERF_BASE + MMIO_PERF_IMEM_MISSES_OFF,
    "mem_tx": MMIO_CPU_PERF_BASE + MMIO_PERF_MEM_TX_OFF,
    "stall_mem": MMIO_CPU_PERF_BASE + MMIO_PERF_STALL_MEM_OFF,
    "stall_fetch": MMIO_CPU_PERF_BASE + MMIO_PERF_STALL_FETCH_OFF,
    "stall_mmio": MMIO_CPU_PERF_BASE + MMIO_PERF_STALL_MMIO_OFF,
}
REGISTROS_VIDEO = video_stop.Registros(
    status=VIDEO_STATUS, swap_count=VIDEO_SWAP_COUNT,
    fb_front=VIDEO_FB_FRONT, fb_back=VIDEO_FB_BACK)
# RGB565 de 320x240.
FRAME_BYTES = 320 * 240 * 2


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No se puede cargar el módulo {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Los registros de video son de 32 bits, pero el monitor accede byte a byte:
# una palabra son cuatro comandos. Se usa `write_memory`/`read_memory` porque
# son los mismos que ya atraviesan el adaptador y la ventana MMIO.
def _write_register(client, address: int, value: int) -> None:
    """Byte a byte, no por bloque.

    Los registros de video no son memoria: viven fuera de las regiones que
    `write_memory` valida, y el monitor solo los atiende con WRITE_BYTE. Por
    bloque el cliente lo rechaza antes de enviar nada.
    """
    for offset, byte in enumerate(value.to_bytes(4, "little")):
        client.write_byte(address + offset, byte)


def _read_register(client, address: int, palabra: bool = False) -> int:
    """Con READ_WORD cuando el monitor lo tiene; si no, cuatro READ_BYTE.

    La diferencia no es de velocidad sino de coherencia: hay registros que
    siguen vivos con el nucleo parado -STATUS lleva el contador de frames en
    los bits altos, y el scanout cuelga de `reset`, no de `core_reset`-, asi
    que entre el primer byte y el cuarto pasa cerca de un milisegundo y el
    valor montado puede no haber existido nunca. READ_WORD es una sola
    transaccion de bus, y por tanto atomico por construccion.

    El camino de bytes se queda porque no todos los prototipos tienen el
    comando: la capacidad se detecta del RTL, no se supone.
    """
    if palabra:
        return client.read_word(address)
    return int.from_bytes(
        bytes(client.read_byte(address + offset) for offset in range(4)),
        "little")


def expand_for(names) -> frozenset:
    """Expande las capacidades implicadas.

    El import va dentro para no crear una dependencia circular: `run_tests`
    importa los backends al arrancar.
    """
    from run_tests import expand_capabilities

    return expand_capabilities(names)


def capabilities(version: str = DEFAULT_VERSION) -> frozenset:
    """Lo que tiene esta versión, con las implicaciones ya expandidas."""
    return expand_for(VERSIONS[version]["capabilities"])


def incompatibility(case: dict, version: str = DEFAULT_VERSION) -> str | None:
    """Rechaza un caso que no cabe en el mapa, antes de tocar la placa.

    El mapa lo declara el `monitor.py` de cada versión, que es quien lo
    implementa; aquí solo se lee su constante, sin abrir el puerto.
    """
    disponibles = capabilities(version)
    faltan = [name for name in case.get("requires", []) if name not in disponibles]
    if faltan:
        # El motivo dice qué versión sí lo tiene, que es lo que uno quiere
        # saber cuando ve el SKIP. La versión que falla ya sale en el
        # prefijo "[version]" del SKIP, así que no se repite aquí.
        con_ello = sorted(
            name for name, config in VERSIONS.items()
            if set(faltan) <= expand_for(config["capabilities"])
        )
        sugerencia = f" (la tienen: {', '.join(con_ello)})" if con_ello else ""
        return f"sin {', '.join(faltan)}{sugerencia}"

    monitor = _load_module(
        f"fpga_monitor_{version}_for_regions",
        Path(__file__).resolve().parents[2] / VERSIONS[version]["monitor_path"],
    )
    return board.region_incompatibility(case, monitor.ARCHITECTURAL_REGIONS)


class FpgaBackend:
    """Carga, ejecuta e inspecciona un caso en la FPGA real."""

    ARCHITECTURE = "cpu"

    def __init__(
        self,
        repository: Path,
        port: str,
        serial_timeout: float,
        version: str = DEFAULT_VERSION,
        upload_policy: board.UploadPolicy | None = None,
    ):
        try:
            self.configuration = VERSIONS[version]
        except KeyError as error:
            choices = ", ".join(sorted(VERSIONS))
            raise ValueError(
                f"Versión del backend FPGA desconocida {version!r}; "
                f"opciones: {choices}"
            ) from error

        self.version = version
        self.monitor = _load_module(
            f"fpga_monitor_{version}_for_tests",
            repository / self.configuration["monitor_path"],
        )
        self.port = port
        self.serial_timeout = serial_timeout
        # Una sola comprobación por ejecución, antes de correr ningún caso.
        board.ensure_bitstream(
            self.monitor, port, serial_timeout,
            self.configuration["monitor_version"],
            repository / self.configuration["monitor_path"].parent,
            "cpu-fpga", version, upload_policy or board.UploadPolicy(),
        )

    def run(self, *args, **kwargs) -> dict:
        # Si la parada por intercambios sale imprecisa, el caso se repite: ver
        # `video_stop`. Sin `run_until` no hay parada que pueda serlo.
        return video_stop.con_reintentos(lambda: self._run_una_vez(*args, **kwargs))

    def _run_una_vez(
        self,
        program: bytes,
        initial_memory: list[tuple[int, bytes]],
        register_numbers: set[int],
        memory_ranges: list[tuple[int, int]],
        max_instructions: int,
        timeout_seconds: float,
        video: dict | None = None,
        stdin: bytes = b"",
    ) -> dict:
        del max_instructions  # La FPGA se limita mediante timeout de pared.
        capacidades = capabilities(self.version)
        tiene_captura = "frame_capture" in capacidades
        tiene_video = "video" in capacidades
        # Los registros de video se leen de una pieza donde se pueda: STATUS
        # lleva el contador de frames, que avanza aunque el nucleo este parado.
        tiene_palabra = "read_word" in capacidades

        serial = self.monitor.serial
        with serial.Serial(
            port=self.port,
            baudrate=self.monitor.BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.serial_timeout,
            write_timeout=self.serial_timeout,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        ) as connection:
            client = self.monitor.MonitorClient(connection)

            def leer_registro(direccion: int) -> int:
                return _read_register(client, direccion, tiene_palabra)

            actual_version = client.get_version()
            expected_version = self.configuration["monitor_version"]
            actual_tuple = (actual_version.major, actual_version.minor)
            if actual_tuple != expected_version:
                expected_text = ".".join(map(str, expected_version))
                raise RuntimeError(
                    f"La FPGA conectada responde con monitor {actual_version}, "
                    f"pero --version cpu-fpga={self.version} requiere "
                    f"{expected_text}. Carga el bitstream correspondiente."
                )

            client.reset_cpu()

            # Las regiones que el caso va a volcar se ponen a CERO antes de
            # nada. El simulador construye su memoria con `bytearray(tamano)`,
            # o sea toda a cero, y los `expected.hex` lo dan por hecho: el de
            # `bresenham-circles-core` tiene 673 de sus 896 palabras a cero, que
            # son las que el programa NO escribe. En la placa esas palabras
            # llevan lo que dejara el caso anterior, porque `reset_cpu` no toca
            # la SDRAM.
            #
            # Medido: `bresenham-lines-core` a solas daba 47 en 0x00100008, y
            # despues de `bresenham-circles-core` daba 32. Poniendo la region a
            # cero a mano, los dos pasan. El sintoma era un valor que cambiaba
            # en cada ejecucion y que no se parecia a su causa.
            #
            # Es propiedad del ARNES, igual que encender SCANOUT o borrar el
            # underflow: el caso declara lo que espera, no como dejar la placa
            # preparada. Y afecta a los 31 casos con `memory_dumps`, no solo a
            # los dos que fallaban: a los otros el residuo les cuadraba por
            # suerte, que es peor que fallar.
            #
            # Va ANTES del programa y de `initial_memory` para que los dos
            # ganen si alguna region los solapa.
            for address, size in memory_ranges:
                if size:
                    client.write_memory(address, bytes(size))

            client.write_memory(0, program)

            for address, data in initial_memory:
                client.write_memory(address, data)

            # Parada del ARNES tras N intercambios. Cero = no se usa. Se arma
            # mas abajo solo si el caso pide `run_until: {swap: N}` y la carpeta
            # tiene `frame_capture`.
            parar_tras_swaps = 0
            por_hardware = False
            # SWAP_COUNT y FRAME_COUNT son del DISPOSITIVO DE VIDEO, no de la
            # CPU: `reset_cpu` no los toca y solo el reset de la placa los pone a
            # cero. Asi que llevan la cuenta acumulada de toda la sesion --se han
            # visto valores de cinco cifras-- y hay que medir contra la linea
            # base de ESTE caso. El simulador no tiene el problema porque
            # construye un dispositivo nuevo por caso, y por eso sus contadores
            # son per-caso; estos hay que restarlos para que sean comparables.
            swaps_base = 0
            frames_base = 0

            if video:
                # Borrar el underflow de la ejecucion anterior ANTES de
                # arrancar. Es pegajoso, asi que sin esto el primer caso que lo
                # provoque hace fallar a todos los demas de la sesion y no se
                # sabe cual fue. En las versiones sin `frame_capture` STATUS es
                # de solo lectura y la escritura se ignora, que es inofensivo.
                _write_register(client, VIDEO_STATUS, 1)
                # Las bases NO se tocan: el framebuffer lo elige el programa.
                # Esto las ponia por `band` y `bounce`, los dos unicos que las
                # heredaban, y de paso tapaba que solo el reset de la placa las
                # reinicia --un caso que dejara un numero IMPAR de intercambios
                # se las pasaba cruzadas al siguiente--. Eso ya no importa:
                # cada programa escribe las suyas al arrancar, asi que ninguno
                # depende de lo que dejara el anterior.
                # Y encender el scanout, porque tras el reset el modo es
                # PATTERN. No es cosmetica: en PATTERN el barrido NO lee la
                # memoria, asi que no puede haber underflow y un
                # `expect.video.underflow: false` pasaria sin comprobar nada.
                # Lo que este arnes mide --si el camino de datos alimenta al
                # barrido a tiempo-- solo existe en SCANOUT.
                #
                # Se escribe aqui y no se le pide al programa porque es
                # propiedad del ARNES: el caso declara lo que espera, no como
                # dejar la placa preparada. Un programa puede cambiarlo despues
                # si lo que prueba es el propio cambio de modo.
                _write_register(client, VIDEO_CTRL, MODE_SCANOUT)
                # HALT_AT y SWAP_COUNT solo existen donde hay `frame_capture`.
                # Ya no es un problema de ALCANCE --desde la fase 3.5 las cuatro
                # decodifican la pagina MMIO entera y un registro que no existe
                # lee cero y se traga la escritura-- pero armar una parada que
                # nadie va a atender seria mentirle al caso.
                if tiene_captura:
                    # `run_until: {swap: N}` es una condicion de OBSERVACION del
                    # arnes --«captura el frame tras el intercambio N»-- y hay
                    # dos formas de pararla, segun lo que declare el RTL:
                    #
                    #   halt_on_swap  HALT_AT cuenta intercambios (§9.6): se
                    #                 arma y la CPU se para sola, en el ciclo
                    #                 del intercambio N. Es exacto.
                    #   sin ella      HALT_AT cuenta FRAMES --asi lo dejo la
                    #                 v2--, que no es lo mismo: el numero de
                    #                 swaps al disparar depende de lo rapido
                    #                 que dibuje el programa. Se sondea
                    #                 SWAP_COUNT desde el host (video_stop.py).
                    #
                    # Por el segundo camino escribir los swaps en HALT_AT era
                    # ademas incorrecto por partida doble: contaba frames, y
                    # HALT_TARGET arranca a cero, asi que no paraba a nadie. El
                    # sintoma era un timeout de 20-30 s por caso de video, que
                    # no se parece a la causa.
                    parar_tras_swaps = video.get("run_until_swap") or 0
                    por_hardware = bool(
                        parar_tras_swaps and "halt_on_swap" in capacidades)
                    # Los dos a cero, siempre, tambien cuando el caso no usa la
                    # alarma: solo el reset de la placa los reinicia y un caso
                    # heredaria la alarma del anterior.
                    _write_register(client, VIDEO_HALT_AT, 0)
                    _write_register(client, VIDEO_HALT_TARGET, 0)
                    # La linea base, despues de desarmar y justo antes de
                    # arrancar. Sin esto la condicion `swaps >= N` es cierta en
                    # el primer sondeo --el contador ya vale miles-- y el caso
                    # para sin haber dibujado nada: nueve frames en blanco que
                    # fallan en el pixel 0. Con la alarma de hardware sirve
                    # para el informe: armar no toca SWAP_COUNT.
                    swaps_base = _read_register(client, VIDEO_SWAP_COUNT,
                                                tiene_palabra)
                    frames_base = _read_register(client, VIDEO_FRAME_COUNT,
                                                 tiene_palabra)
                    if por_hardware:
                        # HALT_TARGET primero: arranca a cero y sin el bit de
                        # CPU la alarma se consume sin parar a nadie. Y lo
                        # ultimo antes de arrancar, porque armar pone a cero la
                        # cuenta de la alarma.
                        _write_register(client, VIDEO_HALT_TARGET,
                                        VIDEO_HALT_TARGET_CPU)
                        _write_register(client, VIDEO_HALT_AT, parar_tras_swaps)

            # Un caso que NO usa video no puede heredar el scanout encendido de
            # uno que si. El modo de VIDEO_CTRL sobrevive a `reset_cpu` --solo
            # lo reinicia el reset de la placa-- y con SCANOUT el barrido lee la
            # SDRAM y compite con la CPU: un programa de 13 instrucciones tardaba
            # a veces 250-279 ciclos en vez de 210, de forma intermitente (3 de
            # cada 40 ejecuciones), y las medidas de CPI de los casos cortos
            # saltaban hasta un 35 % entre pasadas con el mismo RTL. Se vuelve al
            # estado de reset: modo PATTERN, que no lee memoria, y underflow
            # limpio. Va aqui y no en cada caso de video porque lo que hay que
            # garantizar es el punto de partida del SIGUIENTE, sea cual sea.
            if tiene_video and not video:
                _write_register(client, VIDEO_STATUS, 1)
                _write_register(client, VIDEO_CTRL, MODE_PATTERN)

            # El puerto serie se llena ANTES de arrancar, no mientras corre.
            # Asi el caso es determinista: la CPU encuentra su entrada entera
            # desde el primer ciclo, igual que el simulador, y lo que salga no
            # depende de cuando haya sondeado el PC. Por eso `load_case` limita
            # `stdin` a la profundidad de la cola.
            #
            # Vaciar antes es necesario: las colas sobreviven a RESET_CPU --son
            # del sistema, no de la CPU-- y un caso heredaria lo que dejara el
            # anterior.
            if hasattr(client, "recv_bytes"):
                while client.recv_bytes(255):
                    pass
                if stdin:
                    client.send_all(stdin)

            hay_serie = hasattr(client, "recv_bytes")
            salida_serie = b"" if hay_serie else None

            client.run_cpu()
            deadline = time.monotonic() + timeout_seconds

            while True:
                status = client.get_status()
                if status.halted:
                    break
                # La parada del arnes: sondear SWAP_COUNT mientras la CPU corre
                # y pararla al llegar. Los registros MMIO responden con el nucleo
                # en marcha --el que no responde es la MEMORIA, que el monitor
                # solo posee con la CPU parada-- asi que esto es leer un contador,
                # no tocar el programa.
                if parar_tras_swaps and not por_hardware:
                    if video_stop.hay_que_parar(leer_registro, REGISTROS_VIDEO,
                                                swaps_base, parar_tras_swaps):
                        status = video_stop.parar(client)
                        break
                if time.monotonic() >= deadline:
                    client.halt_cpu()
                    raise TimeoutError(
                        f"La CPU no terminó en {timeout_seconds:g} segundos"
                    )
                # Hay que vaciar MIENTRAS corre. La cola de salida son 64
                # bytes y un programa interactivo escribe mucho mas que eso;
                # si se deja llenar, el programa se queda esperando hueco y el
                # caso muere por timeout en vez de por lo que estuviera
                # probando. Esto no cambia el flujo de bytes, solo cuando se
                # recogen, asi que sigue siendo comparable con el simulador.
                if hay_serie:
                    salida_serie += client.recv_bytes(255)
                else:
                    time.sleep(0.01)

            # Se vacia lo que quede: lo que la CPU escribiera al final esta ahi
            # desde que paro, y un solo RECV_BYTES se queda en 255.
            if hay_serie:
                while True:
                    trozo = client.recv_bytes(255)
                    if not trozo:
                        break
                    salida_serie += trozo

            registers = {
                number: client.read_register(number)
                for number in sorted(register_numbers)
            }
            memory = {
                (address, size): client.read_memory(address, size)
                for address, size in memory_ranges
            }

            # Los contadores, antes que nada lo demas que toque la memoria: la
            # CPU ya esta parada, asi que no se mueven, pero leerlos aqui deja
            # claro que miden el programa y no lo que haga el monitor despues.
            #
            # Salen del MMIO, no de los comandos 0x36/0x37, que ya no existen:
            # son un dispositivo como los demas --ver cpu_perf_counters.v-- y la
            # capacidad se detecta del RTL igual que el resto.
            cycles = instructions = None
            esperas = None
            if "perf_counters" in capacidades:
                cycles = _read_register(client, PERF_CYCLES, tiene_palabra)
                instructions = _read_register(client, PERF_RETIRED, tiene_palabra)
            # Los de espera solo donde el RTL los tiene: leer una ranura sin
            # contador da error de MMIO, no un cero.
            if "perf_stalls" in capacidades:
                esperas = {
                    nombre: _read_register(client, direccion, tiene_palabra)
                    for nombre, direccion in PERF_STALL_COUNTERS.items()
                }

            video_result = None
            if video:
                # ANTES de leer nada, esperar a que no quede intercambio
                # pendiente. Parar la CPU no para el doble buffer: una peticion
                # de SWAP se atiende en la frontera de frame siguiente, que la
                # decide el barrido. Mientras siga pendiente, SWAP_COUNT y
                # FB_FRONT pueden cambiar entre dos lecturas nuestras, y
                # entonces la cuenta y la base que leemos son de instantes
                # distintos: el contador dice que no hubo intercambio de mas y
                # la base ya esta volteada.
                #
                # Eso hacia que `video-swap-demo-fast` fallara UNA DE CADA DOS
                # veces despues de corregir la paridad, que es peor que el
                # fallo original porque parece ruido.
                #
                # Con la CPU parada y sin nada pendiente, el dispositivo de
                # video esta quieto y todo lo que se lea es coherente. Un frame
                # son 16,7 ms; 200 ms es margen de sobra y no se agota nunca
                # salvo que el barrido este detenido, en cuyo caso seguir
                # esperando tampoco arreglaria nada.
                if tiene_captura:
                    video_stop.esperar_sin_pendiente(leer_registro,
                                                     REGISTROS_VIDEO)

                # Se lee DESPUES de que la CPU haya parado. Los registros
                # responden tambien con la CPU en marcha, pero el frame no: el
                # monitor solo posee la memoria con la CPU parada.
                estado = _read_register(client, VIDEO_STATUS, tiene_palabra)
                video_result = {
                    "underflow": bool(estado & 1),
                    # De FRAME_COUNT, no de STATUS[31:16]. En v1 los frames
                    # vivian en la mitad alta de STATUS y daban la vuelta a los
                    # 65536 --unos 18 minutos--; en v2 tienen registro propio de
                    # 32 bits. Leerlos del sitio viejo devuelve cero SIEMPRE, sin
                    # error y sin ruido, que es el peor modo de fallo posible.
                    # Los dos contra la linea base del caso, por lo que dice el
                    # comentario de `swaps_base`: son contadores del dispositivo
                    # de video y sobreviven a `reset_cpu`.
                    "frames": ((_read_register(client, VIDEO_FRAME_COUNT,
                                               tiene_palabra)
                                - frames_base) & 0xFFFFFFFF
                               if tiene_captura else estado >> 16),
                    "swaps": ((_read_register(client, VIDEO_SWAP_COUNT,
                                              tiene_palabra)
                               - swaps_base) & 0xFFFFFFFF
                              if tiene_captura else None),
                    "fb_front": _read_register(client, VIDEO_FB_FRONT, tiene_palabra),
                    "frame": None,
                }
                if video.get("capture_frame"):
                    # Desde FB_FRONT, no desde una direccion fija: tras el
                    # intercambio N el buffer visible alterna segun la paridad.
                    #
                    # Y con una correccion, porque parar la CPU NO para el
                    # doble buffer. Una peticion de intercambio se atiende en la
                    # frontera de frame siguiente, que la decide el BARRIDO; si
                    # el programa escribio SWAP justo antes de que llegara el
                    # `halt_cpu` del arnes, el intercambio se completa con la
                    # CPU ya parada y FB_FRONT acaba apuntando al buffer que el
                    # programa estaba pintando a medias.
                    #
                    # Solo muerde a los programas rapidos, y por eso tardo en
                    # verse: `swap_demo` repinta 240 lineas y tarda 96 ms en
                    # volver a pedir intercambio, asi que la parada siempre cae
                    # dentro de esa ventana. `swap_demo_fast` repinta 32 y
                    # vuelve a pedirlo en 13 ms, que es el orden del viaje de
                    # ida y vuelta por el puerto serie. Medido: la lenta para
                    # con `swaps=24` y la rapida con `swaps=25`, y el frame
                    # capturado salia con la banda dos filas mas abajo.
                    #
                    # La correccion es de paridad y no una heuristica: cada
                    # intercambio de mas cambia de sitio el buffer que buscamos,
                    # que es el que quedo completo tras el intercambio N. La CPU
                    # esta parada, asi que su contenido ya no cambia.
                    #
                    # La corrección vive en `video_stop.frame_tras_swap`, que
                    # además falla con `ParadaImprecisa` si se pasó de largo en
                    # dos o más: antes se corregía por paridad sin mirar cuánto.
                    pedidos = parar_tras_swaps if (
                        parar_tras_swaps
                        and video_result["swaps"] is not None) else None
                    video_result["frame"] = video_stop.frame_tras_swap(
                        client, leer_registro, REGISTROS_VIDEO,
                        video_result["swaps"], pedidos, FRAME_BYTES)

        return {
            "halted": status.halted,
            "error": status.error,
            "error_code": status.error_code,
            "pc": status.pc,
            "registers": registers,
            "memory": memory,
            "video": video_result,
            "stdout": salida_serie,
            "cycles": cycles,
            "instructions": instructions,
            # `None` en las versiones sin contadores de espera.
            "stalls": esperas,
            "clock_hz": self.configuration.get("clock_hz"),
        }
