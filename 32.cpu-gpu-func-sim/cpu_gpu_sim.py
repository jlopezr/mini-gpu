#!/usr/bin/env python3
"""Simulador funcional de MiniCPU + MiniGPU sobre una RAM compartida.

No reimplementa ningún núcleo: importa `CPU` de `2.cpu-sim-func` y `System` de
`11.gpu-sim-func` y les pone en medio lo que les falta para convivir —una sola
RAM y un bus MMIO v2 con el mapa y los permisos de `1.isa/mmio.md`—.

Qué se comparte
---------------
- La RAM: **el mismo `bytearray`** en la CPU y en todas las lanes de la GPU. Lo
  que escribe uno lo lee el otro sin copias ni caché (§18: el modelo funcional
  hace visible cada escritura al retirarse la instrucción).
- SYSTEM, SERIAL, VIDEO e INPUT: los mismos objetos de `tools/sim_devices.py`,
  accesibles desde las dos (§15). El reloj sintético de los dispositivos avanza
  una vez por instrucción retirada, sea de la CPU o de un warp.

Dónde se sincronizan
--------------------
Solo en el MMIO de la GPU (§14), que es lo que hace el hardware:

- La CPU escribe los descriptores en `GPU WARPS` y lanza con
  `GPU_CONTROL.RUN` o `WARP_START`.
- La CPU sondea `GPU_STATUS`, `WARP_LIVE` y `WARP_DONE`. `WARP_DONE` es pegajoso
  y se limpia escribiendo unos (W1C).

No hay ningún otro canal: ni hilos, ni callbacks, ni estado compartido fuera de
la RAM y de esos registros.

Planificación
-------------
Determinista y de un solo hilo: cada ronda ejecuta `cpu_steps` instrucciones de
CPU y luego `gpu_steps` instrucciones de warp (un warp por instrucción, el
round-robin de `11`). Con la misma entrada el resultado se repite siempre, pero
el reparto de velocidades es una elección del modelo, no una medida: el
simulador cuenta instrucciones, no ciclos ni esperas.

Qué no hace (aún)
-----------------
CPU PERFORMANCE, GPU PERFORMANCE, CPU DEBUG, TIMER, INTC, DMA, FABRIC y SDRAM no
existen: acceder a ellos es error, no cero (§17). La regla de §4.2 —una sola
lane activa en un acceso MMIO desde SIMT— tampoco la comprueba `11`.
"""

from __future__ import annotations

import argparse
import sys
from contextlib import nullcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _folder in (ROOT, ROOT / "2.cpu-sim-func", ROOT / "11.gpu-sim-func"):
    if str(_folder) not in sys.path:
        sys.path.insert(0, str(_folder))

import minicpu_sim as cpu_sim  # noqa: E402
import minigpu_sim as gpu_sim  # noqa: E402
from gpu_trace import TextTrace, instruction_text  # noqa: E402
from tools import mmio_map as mm  # noqa: E402
from tools import sim_peripherals  # noqa: E402
from tools.sim_devices import VideoDevice  # noqa: E402
from tools.sysid_device import SysIdDevice, declared_devices  # noqa: E402

FOLDER = 32
MAX_LANES = 8       # NUM_LANES son ocho bits en GPU_CAPS, pero CONTEXT.lane son tres
MAX_WARPS = 8       # el simulador de 11 admite como máximo ocho

# Valores provisionales: mmio.md §22 pospone los bits de CPU_ISA, CPU_FEATURES,
# GPU_ISA y GPU_FEATURES "junto a MiniISA", y no define el formato de VERSION.
# Los IDs son el número de carpeta del modelo, como en `sysid_device.py`.
CPU_ID = 2
GPU_ID = 11
CORE_VERSION = 1

# GPU_STATUS (§14.1)
STATUS_RUNNING = 1 << 0
STATUS_HALTED = 1 << 1
STATUS_IDLE = 1 << 2
STATUS_ERROR = 1 << 3
STATUS_LIVE_SHIFT = 8

# GPU_CONTROL (§14.1)
CTRL_RUN = 1 << 0
CTRL_HALT = 1 << 1
CTRL_RESUME = 1 << 2
CTRL_STEP = 1 << 3
CTRL_RESET = 1 << 4
CTRL_MASK = (1 << 5) - 1

# CPU_STATUS: provisional, igual que los demás registros de identidad.
CPU_STATUS_HALTED = 1 << 0
CPU_STATUS_ERROR = 1 << 1


class InstructionLimitExceeded(RuntimeError):
    """`run` llegó al límite de instrucciones sin que el sistema parara."""


class AccessFault(RuntimeError):
    """Acceso MMIO inválido (§4.3). Los núcleos lo convierten en su error 0x02."""


# ---------------------------------------------------------------------------
# Bus MMIO
# ---------------------------------------------------------------------------

class _Port:
    """Un dispositivo visto por un master: aplica el permiso y delega.

    Tiene la interfaz que ya usan los dos simuladores (`BASE`, `contains`,
    `validate`, `read`, `write`), así que ni la CPU de 2 ni las lanes de 11
    saben que hay un bus.
    """

    def __init__(self, device, master: str, mode: str):
        self.device = device
        self.master = master
        self.mode = mode
        self.BASE = device.BASE
        self.SIZE = device.SIZE

    def contains(self, address: int) -> bool:
        return self.device.contains(address)

    def _check(self, offset: int, writing: bool) -> None:
        if ("w" if writing else "r") not in self.mode:
            raise AccessFault(
                f"{self.master} no puede {'escribir' if writing else 'leer'} "
                f"{self.BASE + offset:#010x}")
        if self.master == "gpu":
            readable = getattr(self.device, "gpu_readable", None)
            if readable is not None and offset not in readable:
                raise AccessFault(
                    f"gpu no puede acceder a {self.BASE + offset:#010x}")

    def validate(self, offset: int, writing: bool = False) -> None:
        self._check(offset, writing)
        self.device.validate(offset, writing=writing)

    def read(self, offset: int) -> int:
        self._check(offset, False)
        return self.device.read(offset)

    def write(self, offset: int, value: int) -> None:
        self._check(offset, True)
        self.device.write(offset, value)


class MmioBus:
    """Mapa global de §2 y política de visibilidad de §15."""

    def __init__(self):
        self._entries: list[tuple[object, dict[str, _Port]]] = []

    def attach(self, device, *, cpu: str, gpu: str) -> None:
        if device is None:
            return
        self._entries.append((device, {
            "cpu": _Port(device, "cpu", cpu),
            "gpu": _Port(device, "gpu", gpu),
        }))

    def device_for(self, master: str, address: int):
        for device, ports in self._entries:
            if device.contains(address):
                return ports[master]
        return None


class _BlockDevice:
    """Un bloque de 64 KiB: dirección y tamaño."""

    BASE = 0
    SIZE = mm.MMIO_BLOCK_SIZE

    def contains(self, address: int) -> bool:
        return self.BASE <= address < self.BASE + self.SIZE

    def tick(self) -> None:
        """Sin reloj propio: avanza con las instrucciones de los núcleos."""


def _bad(base: int, offset: int, why: str) -> AccessFault:
    return AccessFault(f"{why}: {base + offset:#010x}")


# ---------------------------------------------------------------------------
# CPU CORE
# ---------------------------------------------------------------------------

class CpuCoreDevice(_BlockDevice):
    """`0x81000000`: identidad y estado de la CPU, todo de solo lectura."""

    BASE = mm.MMIO_CPU_BASE
    _REGISTERS = (mm.MMIO_CPU_ID_OFF, mm.MMIO_CPU_VERSION_OFF,
                  mm.MMIO_CPU_ISA_OFF, mm.MMIO_CPU_FEATURES_OFF,
                  mm.MMIO_CPU_STATUS_OFF)

    def __init__(self, cpu):
        self.cpu = cpu

    def validate(self, offset: int, writing: bool = False) -> None:
        if writing:
            raise _bad(self.BASE, offset, "registro de solo lectura")
        if offset not in self._REGISTERS:
            raise _bad(self.BASE, offset, "registro MMIO inexistente")

    def read(self, offset: int) -> int:
        self.validate(offset)
        if offset == mm.MMIO_CPU_ID_OFF:
            return CPU_ID
        if offset == mm.MMIO_CPU_VERSION_OFF:
            return CORE_VERSION
        if offset == mm.MMIO_CPU_ISA_OFF:
            return cpu_sim.SIMULATOR_ISA_PROFILE
        if offset == mm.MMIO_CPU_FEATURES_OFF:
            return 0
        return ((CPU_STATUS_HALTED if self.cpu.halted else 0)
                | (CPU_STATUS_ERROR if self.cpu.error else 0))

    def write(self, offset: int, value: int) -> None:
        self.validate(offset, writing=True)


# ---------------------------------------------------------------------------
# La GPU como la ve el contrato
# ---------------------------------------------------------------------------

class _GpuSystem(gpu_sim.System):
    """El `System` de 11 con la RAM y los dispositivos del bus en vez de los suyos."""

    def __init__(self, memory: bytearray, bus: MmioBus, num_warps: int,
                 warp_size: int, **depths):
        # Memoria mínima: se sustituye enseguida por la compartida. Pasar la
        # buena haría reservar otros 32 MiB para tirarlos.
        super().__init__(4, num_warps, warp_size, **depths)
        self.bus = bus
        self.memory = memory
        sm = self.streaming_multiprocessor
        sm.memory = memory
        for warp in sm.warps:
            warp.memory = memory
            for lane in warp.processors:
                lane.memory = memory

    def device_for(self, address: int):
        return self.bus.device_for("gpu", address)

    def tick_devices(self) -> None:
        """Los dispositivos los avanza el sistema completo, una vez por instrucción."""


class GpuUnit:
    """`System` de 11 + lo que MMIO v2 añade: descriptores, máscaras y comandos."""

    def __init__(self, memory: bytearray, bus: MmioBus, num_warps: int = 8,
                 warp_size: int = 8, **depths):
        if not 0 < num_warps <= MAX_WARPS:
            raise ValueError(f"num_warps debe estar entre 1 y {MAX_WARPS}")
        if not 0 < warp_size <= MAX_LANES:
            raise ValueError(f"warp_size debe estar entre 1 y {MAX_LANES}")
        self.system = _GpuSystem(memory, bus, num_warps, warp_size, **depths)
        self.num_warps = num_warps
        self.num_lanes = warp_size
        #: Descriptores de §14.2. Son configuración: `RESET` no los toca.
        #: También `logical_id` y `arg` (§14.2), que leen GETLWARP y GETARG.
        self.descriptors = [{"pc": 0, "active": 0, "group": 0,
                             "logical_id": 0, "arg": 0}
                            for _ in range(num_warps)]
        self.live = 0       # WARP_LIVE
        self.done = 0       # WARP_DONE, pegajoso
        self.context_warp = 0
        self.context_lane = 0
        #: Se llama tras cada instrucción de warp retirada.
        self.on_retire = lambda: None
        self.retired = 0

    @property
    def warps(self):
        return self.system.streaming_multiprocessor.warps

    @property
    def fault(self):
        return self.system.fault

    @property
    def halted_by_control(self) -> bool:
        return self.system.peripheral_halted

    def status(self) -> int:
        s = self.system
        running = self.live != 0 and not s.peripheral_halted and not s.error
        return ((STATUS_RUNNING if running else 0)
                | (STATUS_HALTED if s.peripheral_halted else 0)
                | (STATUS_IDLE if self.live == 0 else 0)
                | (STATUS_ERROR if s.error else 0)
                | (bin(self.live).count("1") << STATUS_LIVE_SHIFT))

    # -- ejecución ---------------------------------------------------------

    def step(self) -> bool:
        """Una instrucción de warp. Detecta los warps que acaban de terminar."""
        retired = self.system.step()
        if retired:
            self._retire()
        return retired

    def _retire(self) -> None:
        self.retired += 1
        for number, warp in enumerate(self.warps):
            bit = 1 << number
            if self.live & bit and warp.halted:
                self.live &= ~bit
                self.done |= bit
        self.on_retire()

    def step_warp(self, number: int) -> bool:
        """Una instrucción del warp `number` y de ningún otro (depuración).

        El round-robin de `step` no interviene: no elige warp ni avanza su
        puntero. Con la GPU detenida por `HALT` ejecuta igualmente, como el
        `STEP` de §14.1, y la deja detenida. False si ese warp no puede avanzar
        (no está vivo, espera en una barrera) o si la instrucción falla.
        """
        warp = self.warps[number]
        if not self.live >> number & 1:
            return False
        halted, self.system.peripheral_halted = self.system.peripheral_halted, False
        try:
            retired = self.system.streaming_multiprocessor._step_warp(warp)
        finally:
            self.system.peripheral_halted = halted or self.system.peripheral_halted
        if retired:
            self._retire()
        return retired

    def step_scheduled(self) -> int | None:
        """Una instrucción del warp que elegiría el planificador (depuración).

        Es el round-robin de `step` --el primer warp vivo y sin esperar desde
        `next_warp`--, que además avanza el puntero, pero ejecutando con la GPU
        detenida como el `STEP` de §14.1. Devuelve el warp que ejecutó, o None
        si ninguno puede avanzar.
        """
        scheduler = self.system.streaming_multiprocessor
        for offset in range(self.num_warps):
            number = (scheduler.next_warp + offset) % self.num_warps
            warp = self.warps[number]
            if self.live >> number & 1 and not warp.halted and warp.state == "READY":
                scheduler.next_warp = (number + 1) % self.num_warps
                self.step_warp(number)
                return number
        return None

    # -- comandos de §14.1 ------------------------------------------------

    def _launch(self, number: int) -> None:
        warp = self.warps[number]
        d = self.descriptors[number]
        warp.reset()
        warp.pc = d["pc"]
        warp.active_mask = warp.live_mask = d["active"]
        warp.workgroup_id = d["group"]
        warp.logical_warp_id = d["logical_id"]
        warp.arg = d["arg"]
        self.live |= 1 << number
        self.done &= ~(1 << number)

    def _require_no_error(self, what: str) -> None:
        if self.system.error:
            raise AccessFault(f"{what} con un error de GPU pendiente: haz RESET")

    def run(self) -> None:
        if self.live:
            raise AccessFault("RUN con warps vivos")
        self._require_no_error("RUN")
        for number, d in enumerate(self.descriptors):
            if d["active"]:
                self._launch(number)

    def halt(self) -> None:
        self.system.peripheral_halted = True

    def resume(self) -> None:
        if not self.system.peripheral_halted:
            raise AccessFault("RESUME con la GPU sin detener")
        self.system.peripheral_halted = False

    def step_debug(self) -> None:
        """STEP: una instrucción de warp con la GPU detenida, y la deja detenida."""
        if not self.system.peripheral_halted:
            raise AccessFault("STEP con la GPU sin detener")
        self.system.peripheral_halted = False
        try:
            self.step()
        finally:
            self.system.peripheral_halted = True

    def reset(self) -> None:
        """Descarta el estado runtime; los descriptores se conservan."""
        self.system.fault = None
        self.system.peripheral_halted = False
        self.system.streaming_multiprocessor.reset()
        self.live = 0
        self.done = 0

    def hard_reset(self) -> None:
        """El estado tras el reset del sistema (§19): también los descriptores."""
        self.reset()
        for descriptor in self.descriptors:
            for field in descriptor:
                descriptor[field] = 0
        self.context_warp = self.context_lane = 0
        self.retired = 0

    def warp_start(self, mask: int) -> None:
        if mask >> self.num_warps:
            raise AccessFault(f"WARP_START de warps no implementados: {mask:#x}")
        if mask & self.live:
            raise AccessFault(f"WARP_START de warps ya vivos: {mask & self.live:#x}")
        self._require_no_error("WARP_START")
        numbers = [n for n in range(self.num_warps) if mask >> n & 1]
        for n in numbers:
            if not self.descriptors[n]["active"]:
                raise AccessFault(f"WARP_START del warp {n} con ACTIVE = 0")
        for n in numbers:
            self._launch(n)


class GpuCoreDevice(_BlockDevice):
    """`0x82000000`: GPU CORE / CONTROL (§14.1)."""

    BASE = mm.MMIO_GPU_BASE
    _READ = (mm.MMIO_GPU_ID_OFF, mm.MMIO_GPU_VERSION_OFF, mm.MMIO_GPU_ISA_OFF,
             mm.MMIO_GPU_FEATURES_OFF, mm.MMIO_GPU_CAPS_OFF,
             mm.MMIO_GPU_STATUS_OFF, mm.MMIO_GPU_CONTROL_OFF,
             mm.MMIO_GPU_WARP_LIVE_OFF, mm.MMIO_GPU_WARP_DONE_OFF)
    _WRITE = (mm.MMIO_GPU_CONTROL_OFF, mm.MMIO_GPU_WARP_START_OFF,
              mm.MMIO_GPU_WARP_DONE_OFF)
    #: Lo que un warp puede leer (§15, «GPU información R»). Scheduling y control
    #: quedan fuera: un warp no debe reprogramarse a sí mismo por accidente.
    gpu_readable = frozenset((mm.MMIO_GPU_ID_OFF, mm.MMIO_GPU_VERSION_OFF,
                              mm.MMIO_GPU_ISA_OFF, mm.MMIO_GPU_FEATURES_OFF,
                              mm.MMIO_GPU_CAPS_OFF, mm.MMIO_GPU_STATUS_OFF))

    def __init__(self, gpu: GpuUnit):
        self.gpu = gpu

    def validate(self, offset: int, writing: bool = False) -> None:
        if offset not in (self._WRITE if writing else self._READ):
            raise _bad(self.BASE, offset,
                       "registro de solo lectura o inexistente" if writing
                       else "registro de solo escritura o inexistente")

    def read(self, offset: int) -> int:
        self.validate(offset)
        gpu = self.gpu
        if offset == mm.MMIO_GPU_ID_OFF:
            return GPU_ID
        if offset == mm.MMIO_GPU_VERSION_OFF:
            return CORE_VERSION
        if offset == mm.MMIO_GPU_ISA_OFF:
            return gpu_sim.SIMULATOR_ISA_PROFILE
        if offset == mm.MMIO_GPU_FEATURES_OFF:
            return 0
        if offset == mm.MMIO_GPU_CAPS_OFF:
            return gpu.num_warps | (gpu.num_lanes << 8)
        if offset == mm.MMIO_GPU_STATUS_OFF:
            return gpu.status()
        if offset == mm.MMIO_GPU_CONTROL_OFF:
            return 0            # son comandos: leen cero
        if offset == mm.MMIO_GPU_WARP_LIVE_OFF:
            return gpu.live
        return gpu.done

    def write(self, offset: int, value: int) -> None:
        self.validate(offset, writing=True)
        gpu = self.gpu
        if offset == mm.MMIO_GPU_CONTROL_OFF:
            if value & ~CTRL_MASK:
                raise _bad(self.BASE, offset, "bits reservados en GPU_CONTROL")
            if value & (value - 1):
                raise _bad(self.BASE, offset, "comandos incompatibles en GPU_CONTROL")
            if value == CTRL_RUN:
                gpu.run()
            elif value == CTRL_HALT:
                gpu.halt()
            elif value == CTRL_RESUME:
                gpu.resume()
            elif value == CTRL_STEP:
                gpu.step_debug()
            elif value == CTRL_RESET:
                gpu.reset()
        elif offset == mm.MMIO_GPU_WARP_START_OFF:
            gpu.warp_start(value)
        else:
            if value >> gpu.num_warps:
                raise _bad(self.BASE, offset, "WARP_DONE: warps no implementados")
            gpu.done &= ~value


class GpuWarpsDevice(_BlockDevice):
    """`0x82010000`: los descriptores de warp y sus dos arrays de configuración (§14.2).

    - Un descriptor de 16 bytes por warp: `PC`, `ACTIVE`, `WORKGROUP_ID` y
      `SIMT_STATE` (este de solo lectura).
    - `LOGICAL_WARP_ID[n]` en `+0x200 + 4n` y `WARP_ARG[n]` en `+0x280 + 4n`, que
      leen `GETLWARP` y `GETARG`.
    """

    BASE = mm.MMIO_GPU_WARPS_BASE
    _FIELDS = {mm.MMIO_GPU_WARPS_PC_OFF: "pc",
               mm.MMIO_GPU_WARPS_ACTIVE_OFF: "active",
               mm.MMIO_GPU_WARPS_GROUP_OFF: "group",
               mm.MMIO_GPU_WARPS_SIMT_OFF: "simt"}
    #: Los dos arrays de una palabra por warp: (offset del array, nombre).
    _ARRAYS = ((mm.MMIO_GPU_WARPS_LOGICAL_ID_OFF, "logical_id"),
               (mm.MMIO_GPU_WARPS_ARG_OFF, "arg"))

    def __init__(self, gpu: GpuUnit):
        self.gpu = gpu

    def _locate(self, offset: int) -> tuple[int, str]:
        """(warp, nombre del registro). Todo lo demás es «registro inexistente»."""
        num_warps = self.gpu.num_warps
        if offset < mm.MMIO_GPU_WARPS_LOGICAL_ID_OFF:
            number, field = divmod(offset, mm.MMIO_GPU_WARPS_STRIDE)
            if number < num_warps and field in self._FIELDS:
                return number, self._FIELDS[field]
        else:
            for base, name in self._ARRAYS:
                if base <= offset < base + 4 * num_warps:
                    return (offset - base) // 4, name
        raise _bad(self.BASE, offset, "registro MMIO inexistente")

    def validate(self, offset: int, writing: bool = False) -> None:
        number, name = self._locate(offset)
        if writing and name == "simt":
            raise _bad(self.BASE, offset, "SIMT_STATE es de solo lectura")

    def read(self, offset: int) -> int:
        self.validate(offset)
        number, name = self._locate(offset)
        if name == "simt":
            warp = self.gpu.warps[number]
            return (len(warp.region_stack) & 0xFF
                    | (len(warp.path_stack) & 0xFF) << 8
                    | (warp.state == "WAIT_BAR") << 17)
        return self.gpu.descriptors[number][name]

    def write(self, offset: int, value: int) -> None:
        self.validate(offset, writing=True)
        number, name = self._locate(offset)
        # No es una interfaz para cambiar el contexto de un warp que ejecuta.
        if self.gpu.live >> number & 1:
            raise _bad(self.BASE, offset, f"descriptor del warp {number} en uso")
        if name == "pc" and value & 3:
            raise _bad(self.BASE, offset, "PC desalineado")
        if name == "active" and value >> self.gpu.num_lanes:
            raise _bad(self.BASE, offset, "ACTIVE con lanes no implementadas")
        self.gpu.descriptors[number][name] = value


class GpuSimtDebugDevice(_BlockDevice):
    """`0x82020000`: contexto de depuración y primer error (§14.3)."""

    BASE = mm.MMIO_GPU_SIMT_BASE
    _READ = (mm.MMIO_GPU_SIMT_CONTEXT_OFF, mm.MMIO_GPU_SIMT_LSU_SLOTS_OFF,
             mm.MMIO_GPU_SIMT_FIRST_ERROR_OFF,
             mm.MMIO_GPU_SIMT_FIRST_ERROR_PC_OFF,
             mm.MMIO_GPU_SIMT_WARP_RETIRED_OFF)

    def __init__(self, gpu: GpuUnit):
        self.gpu = gpu

    def validate(self, offset: int, writing: bool = False) -> None:
        if offset not in self._READ:
            raise _bad(self.BASE, offset, "registro MMIO inexistente")
        if writing and offset != mm.MMIO_GPU_SIMT_CONTEXT_OFF:
            raise _bad(self.BASE, offset, "registro de solo lectura")

    def read(self, offset: int) -> int:
        self.validate(offset)
        gpu = self.gpu
        fault = gpu.fault
        if offset == mm.MMIO_GPU_SIMT_CONTEXT_OFF:
            return gpu.context_lane | gpu.context_warp << 3
        if offset == mm.MMIO_GPU_SIMT_LSU_SLOTS_OFF:
            return 0            # la LSU funcional completa cada acceso al instante
        if offset == mm.MMIO_GPU_SIMT_FIRST_ERROR_OFF:
            if fault is None:
                return 0
            lane = fault.core_id
            return ((lane or 0) | fault.warp_id << 3
                    | (lane is not None) << 6 | fault.code << 8)
        if offset == mm.MMIO_GPU_SIMT_FIRST_ERROR_PC_OFF:
            return fault.pc if fault else 0
        # Provisional: §14.3 no dice de qué warp. Se toma el de CONTEXT.
        return gpu.warps[gpu.context_warp].instructions_executed

    def write(self, offset: int, value: int) -> None:
        self.validate(offset, writing=True)
        lane, warp = value & 7, value >> 3 & 7
        if value >> 6 or lane >= self.gpu.num_lanes or warp >= self.gpu.num_warps:
            raise _bad(self.BASE, offset, "CONTEXT fuera de rango")
        self.gpu.context_lane, self.gpu.context_warp = lane, warp


# ---------------------------------------------------------------------------
# El sistema
# ---------------------------------------------------------------------------

class _LinePrefix:
    """Antepone un texto a cada línea escrita: lo que `TextTrace` imprime es de la GPU."""

    def __init__(self, stream, prefix: str):
        self.stream = stream
        self.prefix = prefix
        self._at_line_start = True

    def write(self, text: str) -> int:
        for piece in text.splitlines(keepends=True):
            if self._at_line_start:
                self.stream.write(self.prefix)
            self.stream.write(piece)
            self._at_line_start = piece.endswith("\n")
        return len(text)

    def flush(self) -> None:
        self.stream.flush()


class _GatedTrace(TextTrace):
    """El `TextTrace` de 11, pero cada línea pide sitio al contador común del sistema."""

    def __init__(self, stream, system: "CpuGpuSystem"):
        super().__init__(stream)
        self.system = system

    def __call__(self, event) -> None:
        if self.system.trace_has_room():
            super().__call__(event)


class _SystemCpu(cpu_sim.CPU):
    """La CPU de 2 con sus dispositivos servidos por el bus."""

    def __init__(self, memory_size: int, bus: MmioBus):
        super().__init__(memory_size)
        self.bus = bus

    def _device(self, address: int):
        return self.bus.device_for("cpu", address)


class CpuGpuSystem:
    """MiniCPU y MiniGPU sobre la misma RAM y el mismo mapa MMIO."""

    def __init__(self, memory_size: int = 32 * 1024 * 1024, num_warps: int = 8,
                 warp_size: int = 8, *, cpu_steps: int = 1, gpu_steps: int = 1,
                 video=None, serial=None, input_device=None,
                 simt_region_depth: int = gpu_sim.MAX_SIMT_REGIONS,
                 simt_path_depth: int = gpu_sim.MAX_SIMT_PATHS):
        if cpu_steps <= 0 or gpu_steps <= 0:
            raise ValueError("cpu_steps y gpu_steps deben ser positivos")
        self.cpu_steps = cpu_steps
        self.gpu_steps = gpu_steps
        self.video, self.serial, self.input = video, serial, input_device
        self.trace = None           # TextTrace de la GPU, con prefijo «GPU»
        self.trace_stream = None    # la salida sin prefijo, donde escribe la CPU
        self.trace_limit = None     # líneas de traza, de CPU y de warp juntas
        self.trace_lines = 0
        self._limits = (None, None)     # (CPU, warp), los fija `run`
        self.bus = MmioBus()
        self.cpu = _SystemCpu(memory_size, self.bus)
        self.memory = self.cpu.memory
        self.gpu = GpuUnit(self.memory, self.bus, num_warps, warp_size,
                           simt_region_depth=simt_region_depth,
                           simt_path_depth=simt_path_depth)
        self.gpu.on_retire = self.tick_devices
        if video is not None:
            # Los dos bits de HALT_TARGET: quién se detiene lo decide
            # `_apply_video_halt`, no el dispositivo.
            video.halt_owner = VideoDevice.HALT_TARGET_CPU | VideoDevice.HALT_TARGET_GPU
        self.sysid = SysIdDevice(
            folder=FOLDER, isa_profile=cpu_sim.SIMULATOR_ISA_PROFILE,
            devices=(declared_devices(serial=serial is not None,
                                      video=video is not None,
                                      input=input_device is not None)
                     | 1 << mm.MMIO_DEV_GPU_BIT),
            mem_base=0, mem_size=memory_size)
        self.bus.attach(self.sysid, cpu="r", gpu="r")
        for device in (serial, video, input_device):
            self.bus.attach(device, cpu="rw", gpu="rw")
        self.bus.attach(CpuCoreDevice(self.cpu), cpu="r", gpu="")
        self.bus.attach(GpuCoreDevice(self.gpu), cpu="rw", gpu="r")
        self.bus.attach(GpuWarpsDevice(self.gpu), cpu="rw", gpu="")
        # CONTEXT es RW dentro de un bloque que §15 da como R a la CPU: el
        # permiso grueso deja pasar y es el registro quien rechaza lo demás.
        self.bus.attach(GpuSimtDebugDevice(self.gpu), cpu="rw", gpu="")
        self.cpu_instructions = 0

    # -- carga ------------------------------------------------------------

    def load_cpu_program(self, data: bytes, address: int = 0) -> None:
        """Carga la imagen y pone el PC de la CPU en ella.

        La imagen lleva también el kernel de la GPU: es RAM compartida, y la CPU
        le da a cada warp la dirección de su etiqueta por el descriptor.
        """
        self.cpu.load_program(data, address)

    def hard_reset(self, image: bytes, address: int = 0) -> None:
        """Empezar de nuevo: RAM a cero, imagen recargada, CPU y GPU como tras el reset.

        Es lo que el depurador llama `reset`. Los dispositivos (vídeo, serie,
        entrada) conservan su estado: el anfitrión los configuró al arrancar
        (presencia de teclado, guiones) y el simulador no tiene un reset de
        sistema para ellos.
        """
        self.memory[:] = bytes(len(self.memory))
        self.cpu.reset()
        self.cpu.load_program(image, address)
        self.gpu.hard_reset()
        self.cpu_instructions = 0

    def enable_trace(self, stream, limit: int | None = None) -> None:
        """Traza intercalada: «CPU» delante de cada instrucción de CPU, «GPU» de cada de warp.

        `limit` son líneas de traza, de CPU y de warp juntas. Solo limita lo que
        se imprime: la ejecución sigue hasta el final.
        """
        if limit is not None and limit < 0:
            raise ValueError("trace-limit no puede ser negativo")
        self.trace_stream = stream
        self.trace_limit = limit
        self.trace_lines = 0
        self.trace = _GatedTrace(_LinePrefix(stream, "GPU     "), self)
        self.gpu.system.trace = self.trace

    def trace_has_room(self) -> bool:
        """Cuenta una línea de traza; False (y apaga la traza) al pasar del límite."""
        if self.trace_limit is not None and self.trace_lines >= self.trace_limit:
            print(f"... traza limitada a {self.trace_limit} líneas; la ejecución continúa",
                  file=self.trace_stream)
            # Apagarla del todo evita construir eventos que nadie va a imprimir.
            self.trace = self.gpu.system.trace = None
            return False
        self.trace_lines += 1
        return True

    def load_memory(self, data: bytes, address: int) -> None:
        if address & 3 or len(data) & 3:
            raise ValueError("el binario y su dirección deben estar alineados a 4")
        if address < 0 or address + len(data) > len(self.memory):
            raise ValueError("binario fuera de memoria")
        self.memory[address:address + len(data)] = data

    # -- estado -----------------------------------------------------------

    @property
    def instructions_executed(self) -> int:
        return self.cpu_instructions + self.gpu.retired

    @property
    def finished(self) -> bool:
        """Ni la CPU ni la GPU pueden cambiar ya nada por sí solas."""
        return self.cpu.halted and self.gpu.system.halted

    # -- dispositivos compartidos ------------------------------------------

    def tick_devices(self) -> None:
        """Un paso del reloj sintético, por instrucción retirada de cualquier núcleo."""
        if self.serial is not None:
            self.serial.tick()
        if self.input is not None:
            self.input.tick()
        if self.video is not None:
            self.video.tick()
            if self.video.halt_request:
                self._apply_video_halt()

    def _apply_video_halt(self) -> None:
        video = self.video
        video.halt_request = False
        # `stop_after_swaps` es una parada del arnés, no del contrato: para todo.
        harness = bool(video.stop_after_swaps
                       and video.swap_count >= video.stop_after_swaps)
        target = video.halt_target
        if harness or target & VideoDevice.HALT_TARGET_CPU:
            self.cpu.halted = True
        if harness or target & VideoDevice.HALT_TARGET_GPU:
            self.gpu.halt()

    # -- ejecución --------------------------------------------------------

    def step_cpu(self) -> bool:
        cpu = self.cpu
        if cpu.halted:
            return False
        pc = cpu.pc
        before = cpu.instructions_executed
        cpu.step()
        retired = cpu.instructions_executed != before
        if self.trace is not None:
            try:
                word = cpu.read_u32(pc)
            except RuntimeError:
                word = None
            outcome = f"ERROR 0x{cpu.error_code:02X}" if cpu.error else (
                "HALT" if cpu.halted else "")
            if self.trace_has_room():
                print(f"CPU     0x{pc:08X}  {instruction_text(word):<28} {outcome}",
                      file=self.trace_stream)
        if retired:
            self.cpu_instructions += 1
            self.tick_devices()
        return retired

    def step_round(self) -> bool:
        """`cpu_steps` instrucciones de CPU y `gpu_steps` de warp; True si hubo alguna.

        Los límites de `run` se comprueban antes de cada instrucción, no de cada
        ronda, así que con `cpu_steps` grande no se pasan.
        """
        progressed = False
        for _ in range(self.cpu_steps):
            self._check_limits()
            progressed |= self.step_cpu()
        for _ in range(self.gpu_steps):
            self._check_limits()
            progressed |= self.gpu.step()
        return progressed

    def _check_limits(self) -> None:
        cpu_limit, gpu_limit = self._limits
        # Un límite solo salta si ese núcleo aún podía ejecutar: con la CPU ya
        # parada, haber llegado a su tope no es un fallo.
        if (cpu_limit is not None and not self.cpu.halted
                and self.cpu_instructions >= cpu_limit):
            raise InstructionLimitExceeded(
                f"límite de {cpu_limit} instrucciones de CPU alcanzado "
                f"en PC=0x{self.cpu.pc:08X}")
        if (gpu_limit is not None and not self.gpu.system.halted
                and self.gpu.retired >= gpu_limit):
            raise InstructionLimitExceeded(
                f"límite de {gpu_limit} instrucciones de warp alcanzado")

    def run(self, max_instructions: int | None = 100_000_000, *,
            max_cpu_instructions: int | None = None,
            max_gpu_instructions: int | None = None) -> str:
        """Ejecuta hasta que todo para. Devuelve «halt» o «stalled».

        `max_instructions` es el límite de **cada** núcleo: N instrucciones de CPU
        y N de warp, no N entre las dos. `max_cpu_instructions` y
        `max_gpu_instructions` lo sustituyen para uno solo. Salta el primero que
        se alcance. «Instrucciones de warp» incluye las de los warps relanzados.

        «stalled» es una GPU con warps vivos que no pueden avanzar (una barrera
        a la que no llegan todos) con la CPU ya parada: nadie va a cambiar nada.
        """
        cpu_limit = max_instructions if max_cpu_instructions is None else max_cpu_instructions
        gpu_limit = max_instructions if max_gpu_instructions is None else max_gpu_instructions
        if any(limit is not None and limit < 0 for limit in (cpu_limit, gpu_limit)):
            raise ValueError("el límite de instrucciones no puede ser negativo")
        self._limits = (cpu_limit, gpu_limit)
        try:
            while not self.finished:
                if not self.step_round() and self.cpu.halted:
                    return "stalled"
            return "halt"
        finally:
            self._limits = (None, None)

    def dump_memory(self, address: int, size: int, filename: Path) -> None:
        self.cpu.dump_memory(address, size, filename)


# ---------------------------------------------------------------------------
# Línea de órdenes
# ---------------------------------------------------------------------------

def load_program_file(path: Path) -> bytes:
    return cpu_sim.load_program_file(path)


def _hex(value: str) -> int:
    return int(value, 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Simulador funcional de MiniCPU + MiniGPU sobre una RAM compartida")
    parser.add_argument("program", type=Path,
                        help=".asm, .bin o .hex con el programa de la CPU y el kernel "
                             "de la GPU en una sola imagen, cargada en 0")
    parser.add_argument("--run-limit", type=int, default=100_000_000,
                        help="límite de instrucciones de CPU y de warp: N para cada "
                             "uno, no N entre los dos (100000000)")
    parser.add_argument("--cpu-run-limit", type=int,
                        help="sustituye --run-limit solo para la CPU")
    parser.add_argument("--gpu-run-limit", type=int,
                        help="sustituye --run-limit solo para los warps")
    parser.add_argument("--memory-size", type=_hex, default=32 * 1024 * 1024)
    parser.add_argument("--num-warps", type=int, default=8)
    parser.add_argument("--warp-size", type=int, default=8)
    parser.add_argument("--cpu-steps", type=int, default=1,
                        help="instrucciones de CPU por ronda (1)")
    parser.add_argument("--gpu-steps", type=int, default=1,
                        help="instrucciones de warp por ronda (1)")
    parser.add_argument("--dump", nargs=3, metavar=("ADDRESS", "SIZE", "FILE"))
    parser.add_argument("--trace", action="store_true",
                        help="traza intercalada CPU/warp por instrucción, a stderr")
    parser.add_argument("--trace-limit", type=int,
                        help="máximo de líneas de traza, de CPU y de warp juntas; implica "
                             "--trace y no limita la ejecución")
    parser.add_argument("--trace-file", type=Path,
                        help="como --trace, pero en un fichero UTF-8")
    sim_peripherals.add_arguments(parser)
    args = parser.parse_args(argv)

    try:
        system = CpuGpuSystem(
            args.memory_size, args.num_warps, args.warp_size,
            cpu_steps=args.cpu_steps, gpu_steps=args.gpu_steps,
            **sim_peripherals.from_arguments(args))
        system.load_cpu_program(load_program_file(args.program))
        sim_peripherals.start_display(system)
        tracing = (args.trace or args.trace_file is not None
                   or args.trace_limit is not None)
        output = (args.trace_file.open("w", encoding="utf-8") if args.trace_file
                  else nullcontext(sys.stderr))
        limited = stalled = None
        with output as stream:
            if tracing:
                system.enable_trace(stream, args.trace_limit)
            try:
                if system.run(args.run_limit,
                              max_cpu_instructions=args.cpu_run_limit,
                              max_gpu_instructions=args.gpu_run_limit) == "stalled":
                    stalled = "GPU con warps vivos sin progreso (¿barrera?)"
            except InstructionLimitExceeded as exc:
                limited = str(exc)
            except gpu_sim.SimulationError as exc:
                limited = str(exc)
            if tracing:
                print(f"FIN: {limited or stalled or 'HALT'}", file=stream, flush=True)
        sim_peripherals.write_outputs(args, system)
    except (OSError, ValueError) as exc:
        print(f"Simulador: {exc}", file=sys.stderr)
        return 2

    cpu, gpu = system.cpu, system.gpu
    if cpu.error:
        print(f"CPU: ERROR 0x{cpu.error_code:02X} en PC=0x{cpu.error_pc:08X} "
              f"tras {cpu.instructions_executed} instrucciones")
    else:
        print(f"CPU: {'HALT' if cpu.halted else 'en marcha'} tras "
              f"{cpu.instructions_executed} instrucciones, PC=0x{cpu.pc:08X}")
    if gpu.fault:
        f = gpu.fault
        print(f"GPU: ERROR 0x{f.code:02X} en PC=0x{f.pc:08X}, warp={f.warp_id}, "
              f"hilo={f.core_id}, dirección={f.address}", file=sys.stderr)
    state = ("con error" if gpu.fault else "detenida" if gpu.halted_by_control
             else "ociosa" if not gpu.live else "con warps vivos")
    print(f"GPU: {state}, {gpu.retired} instrucciones de warp, "
          f"WARP_DONE=0x{gpu.done:X} WARP_LIVE=0x{gpu.live:X}")
    for i, value in enumerate(cpu.regs):
        if value != 0:
            print(f"R{i:02d} = 0x{value:08X} ({value})")
    if args.dump:
        address, size, filename = args.dump
        system.dump_memory(int(address, 0), int(size, 0), Path(filename))
    sys.stdout.flush()
    sim_peripherals.finish_display(system)
    if limited or stalled:
        print(f"Simulador: {limited or stalled}", file=sys.stderr)
        return 2
    return 1 if cpu.error or gpu.fault else 0


if __name__ == "__main__":
    raise SystemExit(main())
