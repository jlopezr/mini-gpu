"""CPU y GPU sobre una misma RAM, vistas como un solo objetivo de depuración.

`SystemTarget` envuelve el `CpuGpuSystem` de `32.cpu-gpu-func-sim` y le da al
depurador lo que éste espera de una máquina --estado, registros, memoria, un
paso-- más lo que un sistema con dos núcleos añade: un **foco** (quién recibe
`step`, `regs`, `set`...) y una tabla de warps.

Cuatro decisiones, las mismas que se acordaron para el depurador:

* **Parada total.** `run` hace avanzar a los dos núcleos con el reparto del
  simulador (`cpu_steps`/`gpu_steps`) y en cuanto uno para --breakpoint, error--
  paran los dos. El foco se mueve al núcleo responsable.
* **`step` solo mueve el núcleo con foco.** Con el foco en la CPU, la GPU queda
  congelada; con el foco en la GPU avanza *un warp* (el del foco) y ningún otro.
  Si ese warp espera en una barrera o ha terminado, el foco pasa al siguiente
  que pueda avanzar y se avisa.
* **Una sola lista de breakpoints.** Es una dirección; salta el núcleo que
  llegue a ella. No hay ISA por núcleo: el listado es el del fuente.
* **Dos resets.** `reset gpu` (blando: warps, errores y barreras, pero no los
  descriptores ni la memoria) y `reset` (duro: RAM a cero, imagen recargada,
  todo como tras el reset del sistema).

El módulo no importa el simulador: trabaja con el objeto que le pasan, así que
la prueba y la placa --cuando haya un monitor que dé los registros de lane--
pueden poner otro detrás.
"""
from __future__ import annotations

from tools.debug_target import (
    CAPS_RESET, CAPS_RESET_GPU, CAPS_WRITE_MEMORY, CAPS_WRITE_PC,
    CAPS_WRITE_REGISTER, POLL_BREAKPOINT, POLL_ERROR, POLL_HALT, POLL_IDLE,
    POLL_STALLED, SCOPE_WARP, DebugTarget, LaneGrid, TargetError, TargetState,
    VideoLayout, WarpRow,
)

CPU = "cpu"
GPU = "gpu"
#: Quién «ejecutó» en un `advance` que solo dio el turno de parada a un warp.
PENDING = "pending"


def _first_lane(mask: int) -> int:
    return (mask & -mask).bit_length() - 1 if mask else 0


class SystemTarget(DebugTarget):
    """Un `CpuGpuSystem` parado, con un núcleo y un warp con el foco."""

    capabilities = frozenset({
        CAPS_WRITE_REGISTER, CAPS_WRITE_PC, CAPS_WRITE_MEMORY, CAPS_RESET,
        CAPS_RESET_GPU,
    })

    def __init__(self, system, image: bytes | None = None,
                 load_address: int = 0) -> None:
        self.system = system
        self.image = image
        self.load_address = load_address
        self._core = CPU
        self._warp = 0
        self._lane = 0
        # Posición en el ciclo `cpu_steps` + `gpu_steps` de `advance`.
        self._slot = 0
        # Quién ejecutó en el último `advance`: (CPU, 0) o (GPU, warp). Solo se
        # mira ese: otro warp que siga parado en una marca no debe volver a
        # saltar cada vez que se ejecuta cualquier otro.
        self._stepped: tuple[str, int] | None = None
        # Warps vivos antes de ese `advance`: los que no estaban acaban de ser
        # lanzados por la CPU, y un warp lanzado ya está *en* su primera
        # instrucción: si hay una marca ahí tiene que parar antes de ejecutarla.
        self._live_before = 0
        # Ámbito del último `advance` (None, "gpu" o "warp"): `poll` lo necesita.
        self._scope: str | None = None
        # Warps lanzados sobre una marca que todavía no han parado.
        self._pending: list[int] = []
        # (núcleo, warp, PC de la instrucción) del último `advance`; el PC de un
        # warp solo se recoge si `track_writer`, que es lo único que lo pide.
        self._writer_data: tuple[str, int, int | None] | None = None
        self._notices: list[str] = []

    # -- identidad y foco ---------------------------------------------------

    @property
    def name(self) -> str:  # type: ignore[override]
        if self._core == CPU:
            return "cpu+gpu CPU"
        return f"cpu+gpu GPU w{self._warp} l{self._lane}"

    @property
    def _gpu(self):
        return self.system.gpu

    def _warp_object(self):
        return self._gpu.warps[self._warp]

    def core(self) -> str:
        return self._core

    def focus_key(self) -> tuple | None:
        if self._core == CPU:
            return (CPU,)
        return (GPU, self._warp, self._lane)

    def set_core(self, core: str | None) -> None:
        if core is None:
            core = GPU if self._core == CPU else CPU
        if core not in (CPU, GPU):
            raise TargetError(f"núcleo desconocido: '{core}' (cpu o gpu)")
        self._core = core

    def select_warp(self, number: int | None) -> None:
        count = self._gpu.num_warps
        if number is None:
            number = (self._warp + 1) % count
        if not 0 <= number < count:
            raise TargetError(f"warp fuera de rango: {number} (0..{count - 1})")
        self._warp = number
        self._core = GPU
        warp = self._warp_object()
        if not warp.active_mask >> self._lane & 1 and warp.active_mask:
            self._lane = _first_lane(warp.active_mask)

    def select_lane(self, number: int | None) -> None:
        count = self._gpu.num_lanes
        if number is None:
            number = (self._lane + 1) % count
        if not 0 <= number < count:
            raise TargetError(f"lane fuera de rango: {number} (0..{count - 1})")
        self._lane = number
        self._core = GPU

    def _focus_warp(self, number: int) -> None:
        self._warp = number
        self._lane = _first_lane(self._gpu.warps[number].active_mask)

    # -- estado -------------------------------------------------------------

    def state(self) -> TargetState:
        if self._core == CPU:
            cpu = self.system.cpu
            return TargetState(
                pc=cpu.pc, halted=cpu.halted, error=cpu.error,
                error_code=cpu.error_code, error_pc=cpu.error_pc,
                instructions=cpu.instructions_executed)
        gpu = self._gpu
        fault = gpu.fault
        return TargetState(
            pc=self._warp_object().pc,
            # La GPU «está parada» para `step` si no queda nada vivo o hay un
            # error: que el warp con foco haya terminado no basta, otro puede
            # seguir y el foco se le pasa solo.
            halted=fault is not None or gpu.live == 0,
            error=fault is not None,
            error_code=fault.code if fault else 0,
            error_pc=fault.pc if fault else 0,
            instructions=self._warp_object().instructions_executed)

    def registers(self) -> list[int]:
        if self._core == CPU:
            return list(self.system.cpu.regs)
        return list(self._warp_object().processors[self._lane].regs)

    def read_memory(self, address: int, length: int) -> bytes:
        memory = self.system.memory
        if address < 0 or length < 0 or address + length > len(memory):
            raise TargetError(f"fuera de memoria: 0x{address:08X}+{length}")
        # Directo sobre el bytearray, como `SimTarget`: mirar no tiene efectos.
        return bytes(memory[address:address + length])

    def _gpu_blocker(self) -> str | None:
        """Por qué la GPU no puede avanzar, sea cual sea el foco."""
        if self._gpu.fault is not None:
            return "la GPU tiene un error pendiente (usa `reset gpu`)"
        if self._gpu.live == 0:
            return "la GPU no tiene warps vivos (la CPU los lanza con WARP_START)"
        return None

    def idle_reason(self) -> str | None:
        return None if self._core == CPU else self._gpu_blocker()

    def stop_location(self) -> str:
        if self._core == CPU:
            return " [CPU]"
        return f" [GPU warp {self._warp}]"

    def pop_notices(self) -> list[str]:
        notices, self._notices = self._notices, []
        return notices

    def summary(self) -> str:
        gpu = self._gpu
        if self._core == CPU:
            text = f"GPU {bin(gpu.live).count('1')}/{gpu.num_warps} vivos"
            if gpu.fault is not None:
                text += " ERROR"
            elif gpu.halted_by_control:
                text += " detenida"
            return text
        cpu = self.system.cpu
        return f"CPU PC=0x{cpu.pc:08X}" + (
            " ERROR" if cpu.error else " HALT" if cpu.halted else "")

    # -- tabla de warps -----------------------------------------------------

    def warp_rows(self) -> list[WarpRow]:
        gpu = self._gpu
        fault = gpu.fault
        rows = []
        for number, warp in enumerate(gpu.warps):
            descriptor = gpu.descriptors[number]
            live = bool(gpu.live >> number & 1)
            if fault is not None and fault.warp_id == number:
                state = "ERROR"
            elif live:
                state = warp.state
            elif gpu.done >> number & 1:
                state = "FIN"
            else:
                state = "CONFIG" if descriptor["active"] else "LIBRE"
            if live or state in ("FIN", "ERROR"):
                pc, active, live_mask = warp.pc, warp.active_mask, warp.live_mask
            else:
                # Sin lanzar se enseña el descriptor: lo que `WARP_START` va a
                # cargar, que es justo lo que se quiere revisar antes de lanzar.
                pc, active, live_mask = descriptor["pc"], descriptor["active"], 0
            rows.append(WarpRow(
                number=number, state=state, pc=pc, active_mask=active,
                live_mask=live_mask,
                region_depth=len(warp.region_stack),
                path_depth=len(warp.path_stack),
                logical_id=descriptor["logical_id"], arg=descriptor["arg"],
                focused=self._core == GPU and number == self._warp,
                runnable=live and warp.state == "READY" and fault is None,
                lanes=gpu.num_lanes))
        return rows

    def lane_grid(self) -> LaneGrid:
        warp = self._warp_object()
        return LaneGrid(
            warp=self._warp, lane=self._lane,
            active_mask=warp.active_mask, live_mask=warp.live_mask,
            regs=tuple(tuple(lane.regs) for lane in warp.processors))

    # -- ejecución con foco -------------------------------------------------

    def _runnable(self, number: int) -> bool:
        warp = self._gpu.warps[number]
        return bool(self._gpu.live >> number & 1) and warp.state == "READY" \
            and not warp.halted

    def _pick_warp(self) -> int | None:
        """El warp con foco si puede avanzar; si no, el siguiente que pueda."""
        count = self._gpu.num_warps
        for offset in range(count):
            number = (self._warp + offset) % count
            if self._runnable(number):
                return number
        return None

    def step(self) -> None:
        if self._core == CPU:
            self.system.step_cpu()
            return
        blocker = self._gpu_blocker()
        if blocker is not None:
            raise TargetError(blocker)
        number = self._pick_warp()
        if number is None:
            raise TargetError(
                "ningún warp puede avanzar: los vivos esperan en una barrera")
        if number != self._warp:
            old = self._warp_object()
            why = ("espera en una barrera" if self._gpu.live >> self._warp & 1
                   and old.state == "WAIT_BAR" else "ha terminado")
            self._notices.append(
                f"el warp {self._warp} {why}; sigo con el warp {number}")
            self._focus_warp(number)
        self._gpu.step_warp(number)

    def gpu_fault(self) -> bool:
        return self._gpu.fault is not None

    def round_warps(self) -> list[int]:
        blocker = self._gpu_blocker()
        if blocker is not None:
            raise TargetError(blocker)
        ran = []
        for number in range(self._gpu.num_warps):
            # Se mira en su turno: un warp que acaba de terminar o de esperar
            # en una barrera, o que otro acaba de liberar, cuenta como está ahora.
            if not self._runnable(number):
                continue
            self._gpu.step_warp(number)
            ran.append(number)
            if self._gpu.fault is not None:
                # Parada total: ninguno más ejecuta y el foco va al que falló.
                self.select_warp(number)
                break
        if not ran:
            raise TargetError(
                "ningún warp puede avanzar: los vivos esperan en una barrera")
        return ran

    def sched_step(self) -> int:
        blocker = self._gpu_blocker()
        if blocker is not None:
            raise TargetError(blocker)
        number = self._gpu.step_scheduled()
        if number is None:
            raise TargetError(
                "ningún warp puede avanzar: los vivos esperan en una barrera")
        # `select_warp` pone el foco en la GPU y conserva la lane si sigue activa.
        self.select_warp(number)
        return number

    # -- ejecución libre, parada total --------------------------------------

    def can_run(self) -> bool:
        system = self.system
        if system.cpu.error or system.gpu.fault is not None:
            return False
        return not system.finished

    def scope_blocker(self, scope: str) -> str | None:
        gpu = self._gpu
        blocker = self._gpu_blocker()
        if blocker is not None:
            return blocker
        if scope == SCOPE_WARP:
            number = self._warp
            if not gpu.live >> number & 1:
                return f"el warp {number} no esta vivo"
            if not self._runnable(number):
                return (f"el warp {number} espera en una barrera y no puede "
                        "avanzar solo")
        elif not any(self._runnable(n) for n in range(gpu.num_warps)):
            return "ningun warp puede avanzar: los vivos esperan en una barrera"
        return None

    def _advance_scoped(self, scope: str) -> bool:
        """Una instrucción de warp con la CPU quieta: del planificador, o del warp con foco."""
        gpu = self._gpu
        self._writer_data = None
        before = ([warp.pc for warp in gpu.warps]
                  if self.track_writer else None)
        if scope == SCOPE_WARP:
            number = self._warp
            ran = self._runnable(number) and gpu.step_warp(number)
            if not ran and gpu.fault is None:
                return False
        else:
            number = gpu.step_scheduled()
            if number is None:
                return False
        self._stepped = (GPU, number)
        self._writer_data = (GPU, number, before[number] if before else None)
        return True

    def advance(self, scope: str | None = None) -> bool:
        """Una instrucción de CPU o de warp, según el reparto del simulador.

        Con `scope`, solo la GPU (`gpu`) o solo el warp con foco (`warp`).
        """
        self._scope = scope
        self._stepped = None
        if scope is not None:
            return self._advance_scoped(scope)
        system = self.system
        total = system.cpu_steps + system.gpu_steps
        self._writer_data = None
        self._live_before = self._gpu.live
        if self._pending:
            # Un warp lanzado sobre una marca que aún no ha parado: no se
            # ejecuta nada, solo se le da su turno de parada.
            self._stepped = (PENDING, self._pending.pop(0))
            return True
        for _ in range(total):
            slot = self._slot
            self._slot = (slot + 1) % total
            if slot < system.cpu_steps:
                pc = system.cpu.pc
                if system.step_cpu() or system.cpu.error:
                    self._stepped = (CPU, 0)
                    self._writer_data = (CPU, 0, pc)
                    return True
                continue
            gpu = self._gpu
            scheduler = gpu.system.streaming_multiprocessor
            before = ([warp.pc for warp in gpu.warps]
                      if self.track_writer else None)
            if gpu.step():
                # `next_warp` apunta al siguiente al que acaba de ejecutar.
                number = (scheduler.next_warp - 1) % gpu.num_warps
                self._stepped = (GPU, number)
                self._writer_data = (
                    GPU, number, before[number] if before else None)
                return True
            if gpu.fault is not None:
                self._stepped = (GPU, gpu.fault.warp_id)
                self._writer_data = (GPU, gpu.fault.warp_id, gpu.fault.pc)
                return True
        return False

    def last_writer(self) -> str:
        if self._writer_data is None:
            return ""
        core, number, pc = self._writer_data
        who = "CPU" if core == CPU else f"GPU warp {number}"
        return who if pc is None else f"{who}, PC=0x{pc:08X}"

    def focus_last_actor(self) -> None:
        if self._stepped is None or self._stepped[0] == PENDING:
            return
        core, number = self._stepped
        self._core = core
        if core == GPU:
            self._focus_warp(number)

    def pcs(self) -> tuple[int, int | None]:
        gpu = self._gpu
        warp = self._warp_object()
        alive = bool(gpu.live >> self._warp & 1) and not warp.halted
        return self.system.cpu.pc, (warp.pc if alive else None)

    def _gpu_hit(self, number: int, marks: set[int]) -> bool:
        """Si el warp que acaba de ejecutar está parado en una marca (y toma el foco)."""
        warp = self._gpu.warps[number]
        # `READY` porque un warp que acaba de llegar a `BAR` conserva el PC de la
        # barrera: sin esto, una marca en ella saltaría dos veces.
        if not warp.halted and warp.state == "READY" and warp.pc in marks:
            self._core = GPU
            self._focus_warp(number)
            return True
        return False

    def _poll_scoped(self, marks: set[int]) -> str | None:
        gpu = self._gpu
        if gpu.fault is not None:
            self._core = GPU
            self._focus_warp(gpu.fault.warp_id)
            return POLL_ERROR
        if self._scope == SCOPE_WARP:
            finished = not gpu.live >> self._warp & 1
        else:
            finished = gpu.live == 0
        if finished:
            return POLL_IDLE
        if self._stepped is None:
            return POLL_STALLED
        return POLL_BREAKPOINT if self._gpu_hit(self._stepped[1], marks) else None

    def poll(self, marks: set[int]) -> str | None:
        if self._scope is not None:
            return self._poll_scoped(marks)
        system = self.system
        cpu, gpu = system.cpu, self._gpu
        if cpu.error:
            self._core = CPU
            return POLL_ERROR
        if gpu.fault is not None:
            self._core = GPU
            self._focus_warp(gpu.fault.warp_id)
            return POLL_ERROR
        if system.finished:
            return POLL_HALT
        if self._stepped is None:
            # Nada avanzó y no ha terminado: la CPU está parada y quedan warps
            # vivos que no pueden seguir (una barrera a la que no llegan todos).
            return POLL_STALLED
        core, number = self._stepped
        if core == CPU:
            if not cpu.halted and cpu.pc in marks:
                self._core = CPU
                return POLL_BREAKPOINT
            launched = gpu.live & ~self._live_before
            hits = [n for n, warp in enumerate(gpu.warps)
                    if launched >> n & 1 and warp.pc in marks]
            if hits:
                # Cada warp lanzado sobre una marca para una vez; los demás
                # esperan su turno en los siguientes `advance`.
                self._pending.extend(hits[1:])
                self._core = GPU
                self._focus_warp(hits[0])
                return POLL_BREAKPOINT
            return None
        if core == PENDING:
            warp = gpu.warps[number]
            if gpu.live >> number & 1 and warp.pc in marks:
                self._core = GPU
                self._focus_warp(number)
                return POLL_BREAKPOINT
            return None
        return POLL_BREAKPOINT if self._gpu_hit(number, marks) else None

    # -- escritura y reset --------------------------------------------------

    def set_register(self, index: int, value: int) -> None:
        if not 0 < index < 32:
            raise TargetError("R0 está cableado a cero" if index == 0
                              else f"registro fuera de rango: R{index}")
        if self._core == CPU:
            self.system.cpu.set_register(index, value & 0xFFFFFFFF)
        else:
            self._warp_object().processors[self._lane].regs[index] = \
                value & 0xFFFFFFFF

    def set_pc(self, value: int) -> None:
        if value & 3:
            raise TargetError(f"PC no alineado: 0x{value:08X}")
        if self._core == CPU:
            self.system.cpu.pc = value & 0xFFFFFFFF
        else:
            self._warp_object().pc = value & 0xFFFFFFFF

    def write_word(self, address: int, value: int) -> None:
        # Con los permisos de la CPU (mmio.md §15): una escritura que ella no
        # podría hacer es un error normal, no un fallo del núcleo.
        try:
            self.system.cpu.write_u32(address, value & 0xFFFFFFFF)
        except RuntimeError as exc:
            raise TargetError(str(exc)) from None

    def reset(self) -> None:
        if self.image is None:
            raise TargetError("no tengo la imagen del programa para recargarla")
        self.system.hard_reset(self.image, self.load_address)
        self._core = CPU
        self._warp = self._lane = 0
        self._slot = 0
        self._stepped = None
        self._scope = None
        self._pending.clear()
        self._notices.clear()

    def reset_gpu(self) -> None:
        self._gpu.reset()
        self._stepped = None
        self._scope = None
        self._pending.clear()

    # -- vídeo --------------------------------------------------------------

    def video_layout(self) -> VideoLayout | None:
        video = self.system.video
        if video is None:
            return None
        return VideoLayout(video.fb_front, video.fb_back)

    def video_swap_count(self) -> int | None:
        video = self.system.video
        return None if video is None else video.swap_count

    def simulated_machine(self):
        return self.system
