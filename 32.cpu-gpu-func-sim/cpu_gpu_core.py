"""Núcleo del sistema CPU + GPU: bus MMIO, dispositivos de control y planificador.

`cpu_gpu_sim.py` explica el modelo, añade la línea de órdenes y lo reexporta:
quien use el simulador sigue importando `cpu_gpu_sim`. Este módulo lo compila
además el backend Codon de `sim-sys`, así que no usa `sys.path`, `argparse` ni
`from __future__` (tools/codon/LIMITACIONES.md, l14 y l15); necesita en
`sys.path` la raíz del repositorio y las carpetas de los dos núcleos y del
desensamblador, que pone quien lo importa.
"""
import minicpu_core as cpu_sim
import minigpu_core as gpu_sim
from gpu_trace import TextTrace
from minigpu_isa import disassemble_word
# `import paquete.módulo as x` y no `from paquete import módulo`: Codon no admite
# lo segundo (tools/codon/LIMITACIONES.md, l18).
import tools.mmio_map as mm
import tools.sim_profile as sim_profile
from tools.mmio_device import MachineHooks, MmioDevice
from tools.sim_devices import InputDevice, SerialDevice, VideoDevice
from tools.sysid_device import SysIdDevice, declared_devices

FOLDER = 32
MAX_LANES = 8       # NUM_LANES son ocho bits en GPU_CAPS, pero CONTEXT.lane son tres
MAX_WARPS = 8       # el simulador de 11 admite como máximo ocho
# «Sin límite» en `run`: un número que ningún contador alcanza, para que
# `_check_limits`, que va antes de cada instrucción, sea solo una comparación.
NO_LIMIT = 1 << 62

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

class _Port(MmioDevice):
    """Un dispositivo visto por un master: aplica el permiso y delega.

    Tiene la interfaz que ya usan los dos simuladores (`BASE`, `contains`,
    `validate`, `read`, `write`), así que ni la CPU de 2 ni las lanes de 11
    saben que hay un bus.
    """

    # Declarados: `MmioBus` y los núcleos los usan como tipo de campo, y Codon no
    # lo admite con una clase de campos inferidos (tools/codon/LIMITACIONES.md, l19).
    device: MmioDevice
    master: str
    mode: str
    # Periférico con reloj (vídeo, serie, entrada): antes de cada acceso, el
    # sistema le pasa los ticks pendientes (`MachineHooks.sync_devices`).
    clocked: bool
    hooks: MachineHooks

    def __init__(self, device: MmioDevice, master: str, mode: str, clocked: bool,
                 hooks: MachineHooks):
        super().__init__(device.BASE, device.SIZE)
        self.device = device
        self.master = master
        self.mode = mode
        self.clocked = clocked
        self.hooks = hooks

    def contains(self, address: int) -> bool:
        return self.device.contains(address)

    def _check(self, offset: int, writing: bool) -> None:
        if ("w" if writing else "r") not in self.mode:
            raise AccessFault(
                f"{self.master} no puede {'escribir' if writing else 'leer'} "
                f"{self.BASE + offset:#010x}")
        if self.master == "gpu" and not self.device.gpu_may_read(offset):
            raise AccessFault(
                f"gpu no puede acceder a {self.BASE + offset:#010x}")

    def validate(self, offset: int, writing: bool = False) -> None:
        self._check(offset, writing)
        if self.clocked:
            self.hooks.sync_devices()
        self.device.validate(offset, writing=writing)

    def read(self, offset: int) -> int:
        self._check(offset, False)
        if self.clocked:
            self.hooks.sync_devices()
        return self.device.read(offset)

    def write(self, offset: int, value: int) -> None:
        self._check(offset, True)
        if self.clocked:
            self.hooks.sync_devices()
        self.device.write(offset, value)
        if self.clocked:
            self.hooks.devices_changed()


class MmioBus:
    """Mapa global de §2 y política de visibilidad de §15."""

    # Declarados (l19), como en `_Port`.
    _ports: dict[str, list[_Port]]
    _lowest: int
    _hooks: MachineHooks

    def __init__(self, hooks: MachineHooks):
        #: El sistema, al que los puertos de los periféricos piden sincronizar.
        self._hooks = hooks
        #: Por master, un puerto por dispositivo, en orden de conexión. Solo
        #: puertos, sin el dispositivo: una tupla con dispositivos de clases
        #: distintas no tiene tipo en Codon (tools/codon/LIMITACIONES.md, l11).
        self._ports: dict[str, list[_Port]] = {"cpu": [], "gpu": []}
        #: La base más baja conectada. Por debajo no responde nadie y
        #: `device_for` contesta sin recorrer la lista: la CPU y las lanes
        #: preguntan en cada acceso, también al leer cada instrucción de la RAM.
        self._lowest = 1 << 32

    def attach(self, device: MmioDevice | None, *, cpu: str, gpu: str,
               clocked: bool = False) -> None:
        if device is None:
            return
        self._ports["cpu"].append(_Port(device, "cpu", cpu, clocked, self._hooks))
        self._ports["gpu"].append(_Port(device, "gpu", gpu, clocked, self._hooks))
        self._lowest = min(self._lowest, device.BASE)

    def device_for(self, master: str, address: int) -> _Port | None:
        if address < self._lowest:
            return None
        for port in self._ports[master]:
            if port.contains(address):
                return port
        return None


class _BlockDevice(MmioDevice):
    """Un bloque de 64 KiB en `base`, sin reloj propio: avanza con los núcleos."""

    def __init__(self, base: int):
        super().__init__(base, mm.MMIO_BLOCK_SIZE)


def _bad(base: int, offset: int, why: str) -> AccessFault:
    return AccessFault(f"{why}: {base + offset:#010x}")


# ---------------------------------------------------------------------------
# CPU CORE
# ---------------------------------------------------------------------------

CPU_CORE_REGISTERS = (mm.MMIO_CPU_ID_OFF, mm.MMIO_CPU_VERSION_OFF,
                      mm.MMIO_CPU_ISA_OFF, mm.MMIO_CPU_FEATURES_OFF,
                      mm.MMIO_CPU_STATUS_OFF)


class CpuCoreDevice(_BlockDevice):
    """`0x81000000`: identidad y estado de la CPU, todo de solo lectura."""

    def __init__(self, cpu):
        super().__init__(mm.MMIO_CPU_BASE)
        self.cpu = cpu

    def validate(self, offset: int, writing: bool = False) -> None:
        if writing:
            raise _bad(self.BASE, offset, "registro de solo lectura")
        if offset not in CPU_CORE_REGISTERS:
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

    # Declarado: si no, Codon toma `self.memory = memory` (un campo heredado) por
    # una declaración nueva y falla (tools/codon/LIMITACIONES.md, l17).
    bus: MmioBus

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
        #: Avisado tras cada instrucción de warp retirada.
        self.hooks = MachineHooks()
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

    @property
    def halted(self) -> bool:
        """Sin ejecución posible: ociosa, detenida por control o con error.

        WARP_LIVE ya se actualiza al lanzar y retirar instrucciones; no hace
        falta volver a recorrer todos los warps en cada paso de la CPU.
        Esperar en una barrera no es estar detenido: sigue habiendo vivos.
        """
        return (not self.live or self.system.peripheral_halted
                or self.system.fault is not None)

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
        if self.halted:
            return False
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
        self.hooks.on_retire()

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
            retired = self.system.streaming_multiprocessor._step_warp(warp, self.system)
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


GPU_CORE_READ = (mm.MMIO_GPU_ID_OFF, mm.MMIO_GPU_VERSION_OFF, mm.MMIO_GPU_ISA_OFF,
                 mm.MMIO_GPU_FEATURES_OFF, mm.MMIO_GPU_CAPS_OFF,
                 mm.MMIO_GPU_STATUS_OFF, mm.MMIO_GPU_CONTROL_OFF,
                 mm.MMIO_GPU_WARP_LIVE_OFF, mm.MMIO_GPU_WARP_DONE_OFF)
GPU_CORE_WRITE = (mm.MMIO_GPU_CONTROL_OFF, mm.MMIO_GPU_WARP_START_OFF,
                  mm.MMIO_GPU_WARP_DONE_OFF)
#: Lo que un warp puede leer (§15, «GPU información R»). Scheduling y control
#: quedan fuera: un warp no debe reprogramarse a sí mismo por accidente.
GPU_CORE_GPU_READABLE = (mm.MMIO_GPU_ID_OFF, mm.MMIO_GPU_VERSION_OFF,
                         mm.MMIO_GPU_ISA_OFF, mm.MMIO_GPU_FEATURES_OFF,
                         mm.MMIO_GPU_CAPS_OFF, mm.MMIO_GPU_STATUS_OFF)


class GpuCoreDevice(_BlockDevice):
    """`0x82000000`: GPU CORE / CONTROL (§14.1)."""

    def __init__(self, gpu: GpuUnit):
        super().__init__(mm.MMIO_GPU_BASE)
        self.gpu = gpu

    def gpu_may_read(self, offset: int) -> bool:
        return offset in GPU_CORE_GPU_READABLE

    def validate(self, offset: int, writing: bool = False) -> None:
        # Dos pertenencias y no `x in (A if writing else B)`: en Codon dos tuplas
        # de distinta longitud son tipos distintos (tools/codon/LIMITACIONES.md, l20).
        allowed = offset in GPU_CORE_WRITE if writing else offset in GPU_CORE_READ
        if not allowed:
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


GPU_WARPS_FIELDS = {mm.MMIO_GPU_WARPS_PC_OFF: "pc",
                    mm.MMIO_GPU_WARPS_ACTIVE_OFF: "active",
                    mm.MMIO_GPU_WARPS_GROUP_OFF: "group",
                    mm.MMIO_GPU_WARPS_SIMT_OFF: "simt"}
#: Los dos arrays de una palabra por warp: (offset del array, nombre).
GPU_WARPS_ARRAYS = ((mm.MMIO_GPU_WARPS_LOGICAL_ID_OFF, "logical_id"),
                    (mm.MMIO_GPU_WARPS_ARG_OFF, "arg"))


class GpuWarpsDevice(_BlockDevice):
    """`0x82010000`: los descriptores de warp y sus dos arrays de configuración (§14.2).

    - Un descriptor de 16 bytes por warp: `PC`, `ACTIVE`, `WORKGROUP_ID` y
      `SIMT_STATE` (este de solo lectura).
    - `LOGICAL_WARP_ID[n]` en `+0x200 + 4n` y `WARP_ARG[n]` en `+0x280 + 4n`, que
      leen `GETLWARP` y `GETARG`.
    """


    def __init__(self, gpu: GpuUnit):
        super().__init__(mm.MMIO_GPU_WARPS_BASE)
        self.gpu = gpu

    def _locate(self, offset: int) -> tuple[int, str]:
        """(warp, nombre del registro). Todo lo demás es «registro inexistente»."""
        num_warps = self.gpu.num_warps
        if offset < mm.MMIO_GPU_WARPS_LOGICAL_ID_OFF:
            number, field = divmod(offset, mm.MMIO_GPU_WARPS_STRIDE)
            if number < num_warps and field in GPU_WARPS_FIELDS:
                return number, GPU_WARPS_FIELDS[field]
        else:
            for base, name in GPU_WARPS_ARRAYS:
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
                    | int(warp.state == "WAIT_BAR") << 17)
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


GPU_SIMT_READ = (mm.MMIO_GPU_SIMT_CONTEXT_OFF, mm.MMIO_GPU_SIMT_LSU_SLOTS_OFF,
                 mm.MMIO_GPU_SIMT_FIRST_ERROR_OFF,
                 mm.MMIO_GPU_SIMT_FIRST_ERROR_PC_OFF,
                 mm.MMIO_GPU_SIMT_WARP_RETIRED_OFF)


class GpuSimtDebugDevice(_BlockDevice):
    """`0x82020000`: contexto de depuración y primer error (§14.3)."""

    def __init__(self, gpu: GpuUnit):
        super().__init__(mm.MMIO_GPU_SIMT_BASE)
        self.gpu = gpu

    def validate(self, offset: int, writing: bool = False) -> None:
        if offset not in GPU_SIMT_READ:
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
            # `int(...)`: Codon no desplaza un bool (tools/codon/LIMITACIONES.md, l21).
            return ((lane or 0) | fault.warp_id << 3
                    | int(lane is not None) << 6 | fault.code << 8)
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

    bus: MmioBus   # declarado, como en `_GpuSystem` (l17)

    def __init__(self, memory_size: int, bus: MmioBus):
        super().__init__(memory_size)
        self.bus = bus

    def _device(self, address: int):
        return self.bus.device_for("cpu", address)


class CpuGpuSystem(MachineHooks):
    """MiniCPU y MiniGPU sobre la misma RAM y el mismo mapa MMIO."""

    def __init__(self, memory_size: int = 32 * 1024 * 1024, num_warps: int = 8,
                 warp_size: int = 8, *, cpu_steps: int = 1, gpu_steps: int = 1,
                 video: VideoDevice | None = None, serial: SerialDevice | None = None,
                 input_device: InputDevice | None = None,
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
        self.profile = None         # sim_profile.Profile, con --profile
        # Los fija `run`; NO_LIMIT fuera de él.
        self._cpu_limit = NO_LIMIT
        self._gpu_limit = NO_LIMIT
        # Reloj por lotes de los periféricos (`tick_devices`): ticks que aún no
        # se les han pasado y, por periférico, cuántos faltan para su próximo
        # evento. Solo dentro de `run`; fuera, tick a tick.
        self._batching = False
        self._ticks_pending = 0
        self._ticks_quiet = 1
        self._serial_wait = NO_LIMIT
        self._input_wait = NO_LIMIT
        self._video_wait = NO_LIMIT
        self.bus = MmioBus(self)
        self.cpu = _SystemCpu(memory_size, self.bus)
        self.memory = self.cpu.memory
        self.gpu = GpuUnit(self.memory, self.bus, num_warps, warp_size,
                           simt_region_depth=simt_region_depth,
                           simt_path_depth=simt_path_depth)
        self.gpu.hooks = self
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
        # Uno por uno: son clases distintas (tools/codon/LIMITACIONES.md, l11).
        self.bus.attach(serial, cpu="rw", gpu="rw", clocked=True)
        self.bus.attach(video, cpu="rw", gpu="rw", clocked=True)
        self.bus.attach(input_device, cpu="rw", gpu="rw", clocked=True)
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
        self._attach_gpu_events()

    def enable_profile(self, profile) -> None:
        """Perfil por función (`tools/sim_profile.py`): cuenta cada instrucción de CPU y de warp."""
        self.profile = profile
        self._attach_gpu_events()

    def _attach_gpu_events(self) -> None:
        """La GPU entrega cada instrucción de warp a un solo consumidor: la traza, el perfil o los dos."""
        if self.profile is None:
            self.gpu.system.trace = self.trace
        else:
            self.gpu.system.trace = sim_profile.GpuEvents(self.profile, lambda: self.trace)

    def trace_has_room(self) -> bool:
        """Cuenta una línea de traza; False (y apaga la traza) al pasar del límite."""
        if self.trace_limit is not None and self.trace_lines >= self.trace_limit:
            print(f"... traza limitada a {self.trace_limit} líneas; la ejecución continúa",
                  file=self.trace_stream)
            # Apagarla del todo evita construir eventos que nadie va a imprimir (salvo el perfil).
            self.trace = None
            self._attach_gpu_events()
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
        return self.cpu.halted and self.gpu.halted

    # -- dispositivos compartidos ------------------------------------------

    def on_retire(self) -> None:
        """Instrucción de warp retirada: también avanza el reloj de los dispositivos."""
        self.tick_devices()

    def request_stop(self) -> None:
        """Para los dos núcleos en su próxima instrucción (ventana cerrada, F12...)."""
        self.cpu.halted = True
        self.gpu.halt()

    def tick_devices(self) -> None:
        """Un paso del reloj sintético, por instrucción retirada de cualquier núcleo.

        Dentro de `run` solo cuenta: los periféricos avanzan de una vez
        (`advance`) en el primer tick en el que alguno hace algo
        (`ticks_until_event`) o antes de que el bus acceda a uno de ellos. Es el
        «reloj por lotes» de tools/sim_devices.py, y da lo mismo que un `tick`
        por instrucción. Llamar a cada periférico en cada instrucción costaba
        una quinta parte del tiempo, y en el motor Codon, que los ve a través de
        un proxy, una llamada a Python en cada evento.
        """
        self._ticks_pending += 1
        if self._ticks_pending >= self._ticks_quiet:
            self.sync_devices()

    def sync_devices(self) -> None:
        """Pasa a los periféricos los ticks pendientes (ver `tick_devices`)."""
        ticks = self._ticks_pending
        if not ticks:
            return
        self._ticks_pending = 0
        if self.serial is not None:
            self.serial.advance(ticks)
            self._serial_wait -= ticks
            if self._serial_wait <= 0:
                self._serial_wait = self.serial.ticks_until_event()
        if self.input is not None:
            self.input.advance(ticks)
            self._input_wait -= ticks
            if self._input_wait <= 0:
                self._input_wait = self.input.ticks_until_event()
        if self.video is not None:
            self.video.advance(ticks)
            self._video_wait -= ticks
            if self._video_wait <= 0:
                self._video_wait = self.video.ticks_until_event()
            if self.video.halt_request:
                self._apply_video_halt()
        self._update_quiet()

    def devices_changed(self) -> None:
        """Vuelve a preguntar a los periféricos cuándo es su próximo evento."""
        if self.serial is not None:
            self._serial_wait = self.serial.ticks_until_event()
        if self.input is not None:
            self._input_wait = self.input.ticks_until_event()
        if self.video is not None:
            self._video_wait = self.video.ticks_until_event()
        self._update_quiet()

    def _update_quiet(self) -> None:
        if self._batching:
            self._ticks_quiet = min(self._serial_wait, self._input_wait, self._video_wait)
        else:
            self._ticks_quiet = 1

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
                text = "<FETCH>" if word is None else disassemble_word(word, pc)
                print(f"CPU     0x{pc:08X}  {text:<28} {outcome}",
                      file=self.trace_stream)
        if retired:
            self.cpu_instructions += 1
            if self.profile is not None:
                try:
                    word = cpu.read_u32(pc)
                except RuntimeError:
                    word = None
                self.profile.cpu(pc, word, cpu.pc)
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
        if self.gpu.halted:
            # `gpu.step` no haría nada y nada cambiaría entre una comprobación y
            # la siguiente: basta una. Con la GPU ociosa, que es lo habitual
            # mientras la CPU prepara un frame, ahorra un 8 % del tiempo.
            self._check_limits()
            return progressed
        for _ in range(self.gpu_steps):
            self._check_limits()
            progressed |= self.gpu.step()
        return progressed

    def _check_limits(self) -> None:
        # Un límite solo salta si ese núcleo aún podía ejecutar: con la CPU ya
        # parada, haber llegado a su tope no es un fallo. La comparación va
        # primero porque casi nunca se cumple.
        if self.cpu_instructions >= self._cpu_limit and not self.cpu.halted:
            raise InstructionLimitExceeded(
                f"límite de {self._cpu_limit} instrucciones de CPU alcanzado "
                f"en PC=0x{self.cpu.pc:08X}")
        if self.gpu.retired >= self._gpu_limit and not self.gpu.halted:
            raise InstructionLimitExceeded(
                f"límite de {self._gpu_limit} instrucciones de warp alcanzado")

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
        self._cpu_limit = NO_LIMIT if cpu_limit is None else cpu_limit
        self._gpu_limit = NO_LIMIT if gpu_limit is None else gpu_limit
        self._batching = True
        self.devices_changed()
        try:
            while not self.finished:
                if not self.step_round() and self.cpu.halted:
                    return "stalled"
            return "halt"
        finally:
            self._cpu_limit = NO_LIMIT
            self._gpu_limit = NO_LIMIT
            # Los ticks que quedan no llegan a ningún evento: no paran nada.
            self.sync_devices()
            self._batching = False
            self._update_quiet()

    def dump_memory(self, address: int, size: int, filename) -> None:
        # `filename` es un `Path` (sin anotar: el núcleo no importa pathlib).
        self.cpu.dump_memory(address, size, filename)
