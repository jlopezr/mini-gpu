"""Backend de FPGA basado en el cliente del monitor UART."""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from types import ModuleType

from . import board


# `capabilities` dice que tiene cada bitstream, y es lo que el runner contrasta
# con el `requires` de cada caso. Declarar solo lo que de verdad se implementa:
# `frame_capture` ya implica `video`, y el runner lo expande.
VERSIONS = {
    "ebr": {
        "monitor_path": Path("6.fpga-cpu/monitor.py"),
        "monitor_version": (1, 6),
        "description": "FPGA con 16 KiB de EBR para programa y datos",
        "capabilities": (),
    },
    "sdram": {
        "monitor_path": Path("10.fpga-cpu-ram/monitor.py"),
        "monitor_version": (1, 5),
        "description": "FPGA con mapa unificado sobre 32 MiB de SDRAM",
        "capabilities": (),
    },
    "hdmi": {
        "monitor_path": Path("16.fpga-cpu-hdmi/monitor.py"),
        "monitor_version": (1, 10),
        "description": "Como sdram, mas video HDMI; 100 MHz y 1 Mbaud",
        "clock_hz": 100_000_000,
        # Tiene scanout y ventana de registros, pero no HALT_AT ni SWAP_COUNT,
        # asi que no puede parar en un intercambio concreto.
        "capabilities": ("video",),
    },
    "bl8": {
        "monitor_path": Path("18.fpga-cpu-hdmi-bl8/monitor.py"),
        "monitor_version": (1, 12),
        "description": "Como hdmi, con memoria en rafagas BL8; 80 MHz y 1 Mbaud",
        "capabilities": ("frame_capture",),
        # Unica version con los contadores 0x36/0x37. Las anteriores son hitos
        # cerrados y no se tocan, asi que su CPI no se puede medir: se estima
        # desde el numero de instrucciones y el tiempo de pared.
        "perf_counters": True,
        "clock_hz": 80_000_000,
    },
    "subword": {
        "monitor_path": Path("19.fpga-cpu-hdmi-ls/monitor.py"),
        # 1.13 y no 1.12 aunque el protocolo sea identico al de la 18: es lo
        # unico que el runner puede preguntar para saber que bitstream tiene
        # delante, y un caso de `extensions` en la 18 pararia con opcode
        # invalido en vez de cargar el bitstream que toca. 1.14 anade ademas los`r`n        # paquetes SEND_BYTES/RECV_BYTES del puerto serie.
        "monitor_version": (1, 14),
        "description": (
            "Como bl8, mas LOADB/LOADH/STOREB/STOREH y sus unsigned, "
            "mas JAL/JALR/JR"
        ),
        "capabilities": ("frame_capture", "subword_memory", "calls", "serial"),
        "perf_counters": True,
        "clock_hz": 80_000_000,
    },
    "alu": {
        "monitor_path": Path("21.fpga-cpu-hdmi-alu/monitor.py"),
        # 1.15. Sube por lo mismo que 1.13 --el PC no puede negociar el juego
        # de instrucciones-- mas un motivo que las anteriores no tenian: R0
        # cableado a cero es un cambio INCOMPATIBLE, no aditivo. Un programa
        # que use R0 como registro general no para con error en la 19; da otro
        # resultado. Sin este numero, el runner cargaria el bitstream que no es
        # y el caso fallaria culpando al programa.
        "monitor_version": (1, 15),
        "description": (
            "Como subword, mas MULHI/DIVU/REM/REMU, SHLI/SHRI/SARI "
            "y R0 cableado a cero"
        ),
        "capabilities": ("frame_capture", "subword_memory", "calls", "serial",
                         "shift_immediate", "alu_extended", "zero_register"),
        "perf_counters": True,
        "clock_hz": 80_000_000,
    },
}
DEFAULT_VERSION = "ebr"

# Registros de video, en direcciones de byte. Solo los usan las versiones que
# declaran `video`; estan aqui y no en el monitor porque son del sistema, no
# del protocolo.
VIDEO_FB_FRONT = 0x8000_0000
VIDEO_FB_BACK = 0x8000_0004
# Los valores que `video_registers.v` pone al resetear la placa. El backend los
# restaura antes de cada caso para que las ejecuciones sean independientes.
FB_FRONT_RESET = 0x0100_0000
FB_BACK_RESET = 0x0102_5800
VIDEO_STATUS = 0x8000_000C
VIDEO_SWAP_COUNT = 0x8000_0010
VIDEO_HALT_AT = 0x8000_0014
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


def _read_register(client, address: int) -> int:
    return int.from_bytes(
        bytes(client.read_byte(address + offset) for offset in range(4)),
        "little")


def expand_for(names) -> frozenset:
    """Expande las capacidades implicadas.

    El import va dentro para no crear una dependencia circular: `run_gpu_tests`
    importa los backends al arrancar.
    """
    from run_gpu_tests import expand_capabilities

    return expand_capabilities(names)


def capabilities(version: str = DEFAULT_VERSION) -> frozenset:
    """Lo que tiene este bitstream, con las implicaciones ya expandidas."""
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
        # saber cuando ve el SKIP.
        con_ello = sorted(
            name for name, config in VERSIONS.items()
            if set(faltan) <= expand_for(config["capabilities"])
        )
        sugerencia = f"; la tienen: {', '.join(con_ello)}" if con_ello else ""
        return (
            f"el bitstream {version!r} no tiene {', '.join(faltan)}{sugerencia}"
        )

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

    def run(
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
        tiene_captura = "frame_capture" in capabilities(self.version)

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
            client.write_memory(0, program)

            for address, data in initial_memory:
                client.write_memory(address, data)

            if video:
                # Borrar el underflow de la ejecucion anterior ANTES de
                # arrancar. Es pegajoso, asi que sin esto el primer caso que lo
                # provoque hace fallar a todos los demas de la sesion y no se
                # sabe cual fue. En las versiones sin `frame_capture` STATUS es
                # de solo lectura y la escritura se ignora, que es inofensivo.
                _write_register(client, VIDEO_STATUS, 1)
                # Y devolver las bases a su sitio, por el mismo motivo: solo el
                # reset de la placa las reinicia, asi que un caso que deje un
                # numero IMPAR de intercambios se las pasa cruzadas al
                # siguiente. Sin esto, `video-registers` falla una de cada dos
                # veces segun lo que corriera antes, y qué buffer es el frontal
                # depende del caso anterior en vez del propio.
                _write_register(client, VIDEO_FB_FRONT, FB_FRONT_RESET)
                _write_register(client, VIDEO_FB_BACK, FB_BACK_RESET)
                # HALT_AT y SWAP_COUNT solo existen donde hay `frame_capture`:
                # en la 16 la ventana de registros es de 16 bytes y escribir en
                # 0x80000014 seria un acceso fuera de ella.
                if tiene_captura:
                    swap = video.get("run_until_swap")
                    # Cero desarma la parada. Se escribe siempre, tambien cuando
                    # el caso no la usa, para no heredarla del caso anterior.
                    _write_register(client, VIDEO_HALT_AT, swap or 0)

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
            cycles = instructions = None
            if self.configuration.get("perf_counters"):
                cycles = client.get_cycles()
                instructions = client.get_instructions()

            video_result = None
            if video:
                # Se lee DESPUES de que la CPU haya parado. Los registros
                # responden tambien con la CPU en marcha, pero el frame no: el
                # monitor solo posee la memoria con la CPU parada.
                estado = _read_register(client, VIDEO_STATUS)
                video_result = {
                    "underflow": bool(estado & 1),
                    "frames": estado >> 16,
                    "swaps": (_read_register(client, VIDEO_SWAP_COUNT)
                              if tiene_captura else None),
                    "fb_front": _read_register(client, VIDEO_FB_FRONT),
                    "frame": None,
                }
                if video.get("capture_frame"):
                    # Desde FB_FRONT, no desde una direccion fija: tras el
                    # intercambio N el buffer visible alterna segun la paridad.
                    video_result["frame"] = client.read_memory(
                        video_result["fb_front"], FRAME_BYTES)

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
            "clock_hz": self.configuration.get("clock_hz"),
        }
