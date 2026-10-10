"""Backend de MiniGPU en FPGA, sobre el cliente del monitor UART 2.1.

Es un backend propio y no una versión de `fpga_cpu.py` porque el runner lee
`ARCHITECTURE` del atributo de clase al construir `BACKEND_DEFINITIONS`, antes
de que exista una versión seleccionada: la arquitectura no puede depender de
`--version`. En este repositorio "versión" significa revisión de hardware de la
misma arquitectura (`ebr` y `sdram` son ambas CPU), igual que `sim_cpu.py` y
`sim_gpu.py` ya están separados por la misma razón.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from types import ModuleType

from . import board, frame_capture
from .common import capabilities_of, load_module as _load_module
from .fpga_common import (
    REPOSITORY as _REPOSITORY, MonitorBackend, architectural_size, build_versions,
    missing_with_hint, write_register as _write_register,
)

from tools.rtl_facts import (  # noqa: E402 (fpga_common ya puso REPOSITORY en sys.path)
    backend_from_rtl,
    capabilities_from_rtl,
)


# Registros de video, en direcciones de byte. LOS MISMOS OFFSETS que en
# `fpga_cpu.py`: ese es el contrato compartido, ahora MMIO v2 §9, y si algun dia
# dejaran de coincidir, el caso de `cases-shared` lo dice. Aqui no aparecen las
# bases de reset: el backend de CPU las restaura antes de cada caso, y un kernel
# de GPU se configura solo.
#
# OJO AL MIGRAR: en v1 `CTRL` era el ultimo registro (+0x18) y ahora es el
# PRIMERO (+0x00), asi que los cinco cambian de offset, no solo de base.
VIDEO_FB_FRONT = 0x8020_0004
VIDEO_FB_BACK = 0x8020_0008
VIDEO_STATUS = 0x8020_0010
VIDEO_SWAP_COUNT = 0x8020_0018
VIDEO_CTRL = 0x8020_0000
# La alarma (§9.6). En la GPU solo desde que `halt_on_swap` la implementa en
# `gpu_video_regs.v`; antes esos dos huecos leian cero y se tragaban la escritura.
VIDEO_HALT_AT = 0x8020_001C
VIDEO_HALT_TARGET = 0x8020_0020
VIDEO_HALT_TARGET_GPU = 1 << 1
REGISTROS_VIDEO = frame_capture.Registros(
    status=VIDEO_STATUS, swap_count=VIDEO_SWAP_COUNT,
    fb_front=VIDEO_FB_FRONT, fb_back=VIDEO_FB_BACK)
# RGB565 de 320x240.
FRAME_BYTES = 320 * 240 * 2


# Modo de VIDEO_CTRL tras el reset de la placa: patron de prueba, el barrido no
# lee memoria. Es el estado en que arrancan los casos.
VIDEO_MODE_PATTERN = 1


def _read_register(client, address: int) -> int:
    """Una palabra de 32 bits, en una sola transaccion.

    Aqui no hay camino de bytes de repuesto --a diferencia de `fpga_cpu.py`, que
    cubre seis versiones de CPU y alguna podria no tener READ_WORD-- porque las
    cuatro GPU lo tienen desde la fase 3.4. Y hace falta: STATUS lleva el
    contador de frames en los bits altos, y el barrido cuelga de `reset`, no de
    `core_reset`, asi que sigue avanzando con el nucleo parado. Leido en cuatro
    trozos podria salir un valor que nunca existio.
    """
    return client.read_word(address)


# Igual que en fpga_cpu.py: cada versión es una carpeta de prototipo con
# `version.json` (`{"alias": ...}`, y opcionalmente `"description"` si el
# título del README no basta); eso es lo único a mano. `monitor_version` se
# lee del RTL --ver tools/rtl_facts.py--. El backport de R0 cableado a cero
# subio las tres versiones de GPU: 12 a 2.3, y
# 14 y 17 a 2.4. No cambia ni un byte del protocolo; sube porque el cambio es
# INCOMPATIBLE y un bitstream viejo no para con error, da otro resultado en
# silencio. 14 y 17 siguen compartiendo numero, como antes: son funcionalmente
# identicas y solo se diferencian en el camino critico -y por eso 17 no tiene
# `version.json`: no es un target de test soportado, aunque tenga RTL-.
VERSIONS = build_versions(
    lambda directory: backend_from_rtl(directory) == "gpu",
    lambda directory, signals: capabilities_from_rtl(directory, signals))
DEFAULT_VERSION = "bram"


def capabilities(version: str = DEFAULT_VERSION) -> frozenset:
    """Lo que tiene esta version, con las implicaciones ya expandidas."""
    return capabilities_of(VERSIONS, version)


def incompatibility(case: dict, version: str = DEFAULT_VERSION) -> str | None:
    """Reject unavailable capabilities before opening a port or uploading."""
    config = VERSIONS[version]
    if case.get('simulator_options'):
        return 'las profundidades SIMT del caso requieren el simulador'
    # Antes de la comprobacion general: `atomic_warp_faults` no le falta a una
    # version, le falta a TODO el RTL, y su motivo lo explica. Dejarlo caer en
    # el caso general diria "sin atomic_warp_faults" sin decir por que.
    if 'atomic_warp_faults' in case.get('requires', []):
        return 'el caso exige fallos atómicos por warp; el RTL permite efectos parciales'
    # Igual que en `fpga_cpu.py`. Faltaba aqui: mientras `cases-gpu` fue el unico
    # origen de casos para placa, ninguno pedia una capacidad opcional y el
    # hueco no daba la cara. Con `cases-shared` si: `shared-double-buffer`
    # pide `video`, y la 12 --que no lo tiene-- lo ejecutaba hasta que la
    # placa contestaba `ff`, o sea un ERROR donde tocaba un SKIP.
    faltan = missing_with_hint(case, VERSIONS, version)
    if faltan:
        return faltan
    # El mapa lo declara el monitor de esta versión, que es quien lo implementa.
    monitor = _load_module(
        f'gpu_fpga_monitor_{version}_for_regions',
        Path(__file__).resolve().parents[2] / config['monitor_path'],
    )
    reason = board.region_incompatibility(case, monitor.ARCHITECTURAL_REGIONS)
    if reason:
        return reason
    observations = case['expected'].get('observations', {})
    if observations.get('fault.address') is not None or (
        'fault.address' in observations and case['expected']['error_code'] == 2
    ):
        return 'el monitor no expone la dirección efectiva de un fallo'
    # Use the same launch validator as the monitor, without touching hardware.
    model_path = Path(__file__).resolve().parents[2] / '11.gpu-sim-func/minigpu_sim.py'
    if 'gpu_trace' not in sys.modules:
        _load_module('gpu_trace', model_path.with_name('gpu_trace.py'))
    model_module = _load_module('gpu_fpga_launch_validation', model_path)
    try:
        model = model_module.System(architectural_size(monitor), 8, 8)
        model.configure_warps(case['warp_config'])
        if any(w.workgroup_id > 0xffffffff for w in model.streaming_multiprocessor.warps):
            return 'workgroup_id no cabe en 32 bits'
    except (ValueError, TypeError) as error:
        return f'lanzamiento incompatible con FPGA: {error}'
    return None


def warp_config_base(monitor: ModuleType) -> int:
    """Dónde están los descriptores de warp en esta versión.

    Se lee del `monitor.py` del prototipo, que es quien declara
    `MONITOR_REGIONS` y por tanto la única fuente que no puede quedarse
    desfasada sin que falle antes el cliente. Con MMIO v2 las cuatro carpetas
    de GPU la declaran en `0x82010000` (§14.2); el valor por defecto de aquí ya
    no lo usa nadie y se deja en la base de v2, no en la de v1, para que un
    prototipo nuevo que se olvide de declararla falle apuntando al mapa vigente.
    """
    return getattr(monitor, 'WARP_CONFIG_BASE', 0x8201_0000)


def simt_debug_base(monitor: ModuleType) -> int:
    """GPU SIMT DEBUG (§14.3). Igual que `warp_config_base`: del prototipo."""
    return getattr(monitor, 'SIMT_DEBUG_BASE', 0x8202_0000)


def gpu_perf_base(monitor: ModuleType) -> int:
    """GPU PERFORMANCE (§14.4). El contador GLOBAL de retiros vive aquí.

    En v1 estaba intercalado en el bloque de depuración, en `+0x108`, entre
    `LSU_SLOTS` y `FIRST_ERROR`; en v2 es de PERF y los tres registros que
    tenía debajo suben cuatro bytes. Es el cambio que hace que leer estas
    direcciones con los offsets viejos no dé error sino **otro registro**.
    """
    return getattr(monitor, 'GPU_PERF_BASE', 0x8203_0000)


def read_observations(client, status, requested: set[str], config_base: int,
                      simt_base: int, perf_base: int) -> dict:
    """Read actual hardware state; register traffic is limited to assertions."""
    def word(address):
        return int.from_bytes(client.read_memory(address, 4), 'little')

    result = {'fault.present': status.error,
              'instructions_executed': word(perf_base + 0x04)}
    if status.error:
        diagnostic = word(simt_base + 0x08)
        result.update({
            'fault.pc': word(simt_base + 0x0c),
            'fault.warp_id': (diagnostic >> 3) & 7,
            'fault.core_id': diagnostic & 7 if diagnostic & 0x40 else None,
        })
        # Only non-address faults have an architectural null address. Never
        # invent an effective memory address that this RTL does not retain.
        if status.error_code != 2:
            result['fault.address'] = None
    for warp in range(8):
        prefix = f'warp[{warp}]'
        data = client.read_memory(config_base + warp * 16, 16)
        result[f'{prefix}.pc'] = int.from_bytes(data[:4], 'little')
        result[f'{prefix}.active_mask'] = data[4]
        client.select_context(warp, 0)
        result[f'{prefix}.instructions_executed'] = word(simt_base + 0x10)
    registers = []
    for key in requested:
        match = re.fullmatch(r'warp\[(\d+)\]\.lane\[(\d+)\]\.R(\d+)', key)
        if match:
            registers.append((*map(int, match.groups()), key))
    selected = None
    for warp, lane, register, key in sorted(registers):
        if selected != (warp, lane):
            client.select_context(warp, lane)
            selected = (warp, lane)
        result[key] = client.read_register(register)
    return result


class FpgaGpuBackend(MonitorBackend):
    """Carga, ejecuta e inspecciona un caso GPU en la FPGA real."""

    ARCHITECTURE = "gpu"
    NAME = "fpga-gpu"
    VERSIONS = VERSIONS
    DEFAULT_VERSION = DEFAULT_VERSION
    def _run_una_vez(
        self,
        program: bytes,
        initial_memory: list[tuple[int, bytes]],
        register_numbers: set[int],
        memory_ranges: list[tuple[int, int]],
        max_instructions: int,
        timeout_seconds: float,
        warp_config: object,
        observation_fields: set[str] | None = None,
        video: dict | None = None,
    ) -> dict:
        # La FPGA se limita por timeout de pared, no por instrucciones.
        del max_instructions, register_numbers

        with self.connect() as client:
            client.reset_cpu()
            client.write_memory(0, program)

            for address, data in initial_memory:
                client.write_memory(address, data)

            # configure_warps valida el JSON contra el modelo, exige la GPU
            # detenida y hace su propio reset antes de escribir PC, máscara y
            # workgroup de cada warp. Por eso va después de cargar el programa.
            client.configure_warps(warp_config)

            # Devolver el video al estado de reset. `reset_cpu` no lo toca --el
            # scanout cuelga del reset de la placa, no del del nucleo-- asi que un
            # caso que deja SCANOUT encendido o el underflow pegado se lo pasa al
            # siguiente: `demo-mmio-selftest` hacia fallar a los dos casos
            # `shared-video-*` que corrian despues, y solo pasaban con la placa
            # recien cargada. Es propiedad del arnes, como en `fpga_cpu.py`: el caso
            # declara lo que espera, no como dejar la placa preparada.
            capacidades = self.configuration["capabilities"]
            if "video" in capacidades:
                _write_register(client, VIDEO_STATUS, 1)
                _write_register(client, VIDEO_CTRL, VIDEO_MODE_PATTERN)
            # Y la alarma desarmada: solo el reset de la placa la reinicia, y un
            # caso que se quedara sin consumirla --un timeout-- se la pasaria al
            # siguiente.
            if "halt_on_swap" in capacidades:
                _write_register(client, VIDEO_HALT_AT, 0)
                _write_register(client, VIDEO_HALT_TARGET, 0)

            def leer_registro(direccion: int) -> int:
                return _read_register(client, direccion)

            # SWAP_COUNT es del dispositivo de vídeo y sobrevive a `reset_cpu`:
            # la parada y el informe lo miden contra la base de ESTE caso.
            parar_tras_swaps = (video or {}).get("run_until_swap") or 0
            # Dos formas de parar, igual que en `fpga_cpu.py`: con `halt_on_swap`
            # `HALT_AT` cuenta intercambios (§9.6) y se arma; sin ella se sondea
            # SWAP_COUNT desde el host (frame_capture.py).
            por_hardware = bool(parar_tras_swaps and "halt_on_swap" in capacidades)
            swaps_base = (_read_register(client, VIDEO_SWAP_COUNT)
                          if video is not None else 0)
            if por_hardware:
                # HALT_TARGET primero: arranca a cero y sin el bit de GPU la
                # alarma se consume sin parar a nadie. Y HALT_AT lo ultimo antes
                # de arrancar, porque armar pone a cero la cuenta de la alarma.
                _write_register(client, VIDEO_HALT_TARGET, VIDEO_HALT_TARGET_GPU)
                _write_register(client, VIDEO_HALT_AT, parar_tras_swaps)

            started = time.monotonic()
            client.run_cpu()
            deadline = started + timeout_seconds

            while True:
                status = client.get_status()
                if status.halted:
                    break
                # La parada del arnés, igual que en `fpga_cpu.py`: un programa de
                # vídeo no termina solo. Con la alarma de hardware se espera a
                # que pare sola; sin ella se sondea SWAP_COUNT.
                sondeando = bool(parar_tras_swaps and not por_hardware)
                if sondeando:
                    if frame_capture.hay_que_parar(leer_registro, REGISTROS_VIDEO,
                                                swaps_base, parar_tras_swaps):
                        status = frame_capture.parar(client)
                        break
                if time.monotonic() >= deadline:
                    client.halt_cpu()
                    raise TimeoutError(
                        f"La GPU no terminó en {timeout_seconds:g} segundos"
                    )
                if not sondeando:
                    time.sleep(0.01)

            elapsed = time.monotonic() - started
            observations = read_observations(
                client, status, observation_fields or set(),
                warp_config_base(self.monitor),
                simt_debug_base(self.monitor),
                gpu_perf_base(self.monitor),
            )
            observations["duration_seconds"] = elapsed
            # Ciclos con la GPU corriendo e instrucciones de WARP retiradas, del
            # bloque GPU PERFORMANCE. Solo donde el RTL lo tiene: en 12/14/17 esa
            # direccion no responde, y un cero ahi seria una medida falsa.
            cycles = None
            if "perf_counters" in self.configuration["capabilities"]:
                cycles = _read_register(client, gpu_perf_base(self.monitor))

            memory = {
                (address, size): client.read_memory(address, size)
                for address, size in memory_ranges
            }

            video_result = None
            if video is not None:
                # Se lee DESPUES de que la GPU haya parado, igual que en la
                # familia CPU: los registros responden tambien en marcha, pero
                # la memoria no, porque el monitor solo la posee con el nucleo
                # detenido.
                # Parar el núcleo no para el doble buffer: se espera a que no
                # quede un intercambio pendiente antes de leer nada.
                frame_capture.esperar_sin_pendiente(leer_registro, REGISTROS_VIDEO)
                estado = _read_register(client, VIDEO_STATUS)
                video_result = {
                    "underflow": bool(estado & 1),
                    "frames": estado >> 16,
                    # HALT_AT no existe aqui, pero SWAP_COUNT si: esta dentro de
                    # la ventana en las cuatro GPU.
                    "swaps": frame_capture.swaps_desde(
                        leer_registro, REGISTROS_VIDEO, swaps_base),
                    "fb_front": _read_register(client, VIDEO_FB_FRONT),
                    "frame": None,
                }
                if video.get("capture_frame"):
                    # Desde FB_FRONT, no desde una direccion fija: tras el
                    # intercambio N el buffer visible alterna segun la paridad.
                    video_result["frame"] = frame_capture.frame_tras_swap(
                        client, leer_registro, REGISTROS_VIDEO,
                        video_result["swaps"], parar_tras_swaps or None,
                        FRAME_BYTES)

        return {
            "halted": status.halted,
            "error": status.error,
            "error_code": status.error_code,
            "pc": status.pc,
            "registers": {},
            "cycles": cycles,
            "instructions": (observations["instructions_executed"]
                             if cycles is not None else None),
            "clock_hz": self.configuration.get("clock_hz"),
            "stalls": None,
            "video": video_result,
            "observations": observations,
            "memory": memory,
        }
