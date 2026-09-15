#!/usr/bin/env python3
"""Modelo de CICLOS del SM de la MiniGPU.

Qué es y qué no
---------------
NO es un simulador funcional: no ejecuta la ISA. Para eso usa el de
`11.gpu-sim-func`, que ya hace ese trabajo y no se toca. Este modelo decide
QUÉ warp avanza y CUÁNTO cuesta, y le pide al funcional que ejecute.

Existe para responder preguntas de parámetros que en RTL cuestan una
reescritura más diez minutos de simulación cada una:

  - ¿cuántos warps hacen falta para llenar un cauce de N etapas?
  - ¿cuál es la ocupación real de la etapa de ejecución, que es el techo?
  - ¿cuánto ganaría de verdad segmentar el cauce?

El contrato: validar antes de predecir
--------------------------------------
Un modelo que no reproduce el diseño ACTUAL no puede decir nada creíble sobre
uno que no existe. Por eso `validate.py` compara contra las cifras medidas en
RTL, y mientras no cuadren, los números del modo `pipelined` son ficción.

Limitación conocida y deliberada: el simulador funcional ejecuta los accesos a
memoria al instante, así que este modelo les pone la latencia POR ENCIMA, sin
modelar el reordenamiento real entre warps. Para cargas donde cada hilo escribe
sus propias palabras (todas las que hay hoy) da igual; para un programa con
warps que se pisen, no.
"""
from __future__ import annotations

import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "11.gpu-sim-func"))

import minigpu_sim as func  # noqa: E402


# ---------------------------------------------------------------------------
# Calibración
#
# Todo lo de aquí sale de medidas, no de suposiciones. Las referencias están en
# 22.fpga-gpu-bl8/profiling.md y en los comentarios del RTL.
# ---------------------------------------------------------------------------

@dataclass
class Config:
    model: str = "baseline"          # "baseline" (11 estados) o "pipelined"
    warps: int = 8
    lanes: int = 8

    # --- coste del cauce actual, contando estados de gpu_sm.v ---
    # PICK, CONTEXT, RECON, FETCH, FETCH_WAIT, RF_WAIT, DECODE, START
    front_cycles: int = 8
    # FINISH, RETIRE
    back_cycles: int = 2
    # Ciclos de la lane desde `step_request` hasta `instruction_retired`, que
    # es lo que espera el SM en EXEC.
    #
    # Eran SEIS: HALTED -> FETCH_REQUEST -> FETCH_WAIT -> DECODE -> EXECUTE
    # -> RETIRE. Los dos de busqueda sobraban —el SM ya le daba la instruccion—
    # y se quitaron con `gpu_lane #(.EXTERNAL_FETCH(1))`. Quedan CUATRO:
    #   HALTED -> DECODE -> EXECUTE -> RETIRE
    #
    # El modelo predijo -11,9% y el RTL dio -11,2%. Poner aqui 6 reproduce el
    # diseno anterior, por si hace falta comparar.
    exec_base: int = 4

    # --- coste del cauce propuesto (sm-pipeline.md) ---
    # S, F, I, D antes de X; W despues.
    pipe_front: int = 4
    pipe_back: int = 1

    # --- operaciones multiciclo, de gpu_lane.v ---
    mul_cycles: int = 4              # MUL_PRODUCTS/CROSS/COMBINE/WRITE
    div_cycles: int = 32             # DIV_STEP, un bit por ciclo
    shift_per_bit: int = 1           # STATE_SHIFT_STEP

    # --- memoria, calibrada en 22 ---
    # 17 ciclos por transaccion de 16 bytes medidos con un solo cliente
    # (sdram_bandwidth_tb.v).
    mem_cycles: int = 17
    # Trafico de video: 40 transacciones por linea fuente cada 1588 ciclos,
    # que son los 9,2 MB/s del framebuffer 320x240 RGB565 a 60 Hz.
    video_burst: int = 40
    video_period: int = 1588
    video_on: bool = True


MEM_OPCODES = {0x15, 0x16}           # LOAD, STORE
# 0x0B/0x0D/0x0E/0x0F (MULHI, DIVU, REM, REMU) NO los implementa gpu_lane.v:
# caen en su `default` y dan ERROR_INVALID_OPCODE. Se dejan aqui porque el
# ensamblador si los emite y el core nuevo los traera.
MUL_OPCODES = {0x03, 0x0A, 0x0B}
DIV_OPCODES = {0x0C, 0x0D, 0x0E, 0x0F}
SHIFT_OPCODES = {0x07, 0x08, 0x09}
BRANCH_OPCODES = {0x20, 0x21, 0x22, 0x23, 0x24, 0x25}
BRA_OPCODE = 0x2F
# Resueltas en el DECODE del SM: no llegan a pisar las lanes, asi que no
# ocupan la etapa de ejecucion. SSY, BAR, EXIT, HALT.
SM_ONLY_OPCODES = {0x31, 0x32, 0x33, 0x3F}
BAR_OPCODE = 0x32


@dataclass
class Counters:
    """Los mismos que expone el hardware en 0x80000300, para poder comparar."""
    cycles: int = 0
    retired: int = 0
    lane_ops: int = 0
    lsu_tx: int = 0
    video_tx: int = 0
    stall_no_warp: int = 0           # ciclos sin warp elegible (burbuja)
    exec_busy: int = 0               # ciclos con la etapa de ejecucion ocupada

    def report(self) -> str:
        lines = ["=== MODELO DE CICLOS ==="]
        for name in ("cycles", "retired", "lane_ops", "lsu_tx", "video_tx",
                     "stall_no_warp", "exec_busy"):
            lines.append(f"  {name:<14} {getattr(self, name):>12,}")
        if self.retired:
            lines.append("")
            lines.append(f"  ciclos por instruccion  {self.cycles / self.retired:>8.2f}")
            lines.append(f"  lanes por instruccion   {self.lane_ops / self.retired:>8.2f}   de 8")
        if self.cycles:
            lines.append(f"  utilizacion de las ALU  {self.lane_ops / (self.cycles * 8) * 100:>8.2f} %")
            lines.append(f"  burbujas sin warp       {self.stall_no_warp / self.cycles * 100:>8.2f} %")
            lines.append(f"  ocupacion de EXEC       {self.exec_busy / self.cycles * 100:>8.2f} %")
        return "\n".join(lines)


class MemChannel:
    """El canal de memoria, serializado.

    `memory_fabric_4` admite UNA transaccion global en vuelo, asi que basta con
    una cola: cada transaccion ocupa el canal `mem_cycles` y las demas esperan.
    El video se inyecta a rafagas y con prioridad (`urgent`), igual que en el
    fabric.
    """

    def __init__(self, cfg: Config, counters: Counters):
        self.cfg = cfg
        self.counters = counters
        self.busy_until = 0
        self.video_pending = 0
        self.next_video = cfg.video_period

    def tick(self, now: int) -> None:
        if not self.cfg.video_on:
            return
        if now >= self.next_video:
            self.next_video += self.cfg.video_period
            self.video_pending = self.cfg.video_burst
        # El video gana al resto mientras tenga rafaga pendiente.
        if self.video_pending and now >= self.busy_until:
            self.video_pending -= 1
            self.busy_until = now + self.cfg.mem_cycles
            self.counters.video_tx += 1

    def issue(self, now: int, transactions: int) -> int:
        """Encola `transactions` y devuelve el ciclo en que acaba la ultima."""
        start = max(now, self.busy_until)
        self.busy_until = start + transactions * self.cfg.mem_cycles
        self.counters.lsu_tx += transactions
        return self.busy_until


def exec_cycles(cfg: Config, instr: int, opcode: int, warp) -> int:
    """Ciclos que una instruccion ocupa la etapa de ejecucion.

    Contando estados de `gpu_lane.v`. `exec_base` son los cuatro del camino
    corto (HALTED, DECODE, EXECUTE, RETIRE) y lo que se suma encima son los
    estados INTERMEDIOS de cada familia.

    Vive aqui, y no como metodo, porque `24.gpu-sim-pipeline` necesita
    exactamente lo mismo: tenia su propia copia, con los mismos cuatro errores
    de cuenta que se detectaron al hacer la tabla instruccion a instruccion de
    `sm-pipeline.md`:

      - saltos: faltaban BRANCH_COMPARE y BRANCH_COMMIT (+2). El peor de los
        cuatro, porque son el 6,4% de las instrucciones del frame.
      - `BRA`: faltaba BRANCH_COMMIT (+1).
      - desplazamientos: faltaba SHIFT_WRITE (+1), ademas de los n pasos.
      - `DIV`: faltaba MUL_WRITE, donde se escribe el cociente (+1).

    Corregirlo llevo el modelo de -8,1% a -7,0% frente al RTL.
    """
    if opcode in SM_ONLY_OPCODES:
        # SSY, BAR, EXIT y HALT se resuelven en el DECODE del SM: no llegan a
        # las lanes, asi que no ocupan la etapa de ejecucion.
        return 0
    if opcode in MUL_OPCODES:
        # PRODUCTS, CROSS, COMBINE, WRITE.
        return cfg.exec_base + cfg.mul_cycles
    if opcode in DIV_OPCODES:
        # 32 x DIV_STEP, y luego MUL_WRITE para el cociente.
        return cfg.exec_base + cfg.div_cycles + 1
    if opcode in SHIFT_OPCODES:
        # Un bit por ciclo, y el numero de bits sale de un registro: se toma el
        # peor de las lanes activas, que es lo que ve el SM al esperar a
        # `&done`. Un desplazamiento de 0 se salta los pasos pero sigue pagando
        # SHIFT_WRITE.
        rb = (instr >> 11) & 0x1F
        worst = 0
        for lane in warp.processors:
            if warp.active_mask & (1 << lane.core_id):
                worst = max(worst, lane.regs[rb] & 0x1F)
        return cfg.exec_base + worst * cfg.shift_per_bit + 1
    if opcode in BRANCH_OPCODES:
        return cfg.exec_base + 2
    if opcode == BRA_OPCODE:
        return cfg.exec_base + 1
    return cfg.exec_base


def popcount(x: int) -> int:
    return bin(x).count("1")


def coalesced_transactions(addresses: list[int]) -> int:
    """Transacciones de 16 bytes que necesita este grupo de direcciones.

    Es el mismo agrupamiento que hace gpu_lsu2: una por linea alineada de 16
    bytes distinta. Solo caben 4 palabras de 32 bits por linea, asi que una
    linea con mas de 4 lanes necesita mas de una vuelta.
    """
    lines: dict[int, int] = {}
    for addr in addresses:
        lines[addr >> 4] = lines.get(addr >> 4, 0) + 1
    return sum((count + 3) // 4 for count in lines.values())


class Model:
    def __init__(self, system: func.System, cfg: Config):
        self.system = system
        self.cfg = cfg
        self.counters = Counters()
        self.mem = MemChannel(cfg, self.counters)
        self.sm = system.streaming_multiprocessor
        self.warps = self.sm.warps
        self.busy_until: dict[int, int] = {w.warp_id: 0 for w in self.warps}
        self.cursor = 0

    def exec_cycles(self, instr: int, opcode: int, warp) -> int:
        return exec_cycles(self.cfg, instr, opcode, warp)

    def mem_addresses(self, instr: int, warp) -> list[int]:
        ra = (instr >> 16) & 0x1F
        imm = func.sign_extend(instr & 0xFFFF, 16)
        return [func.u32(lane.regs[ra] + imm)
                for lane in warp.processors
                if warp.active_mask & (1 << lane.core_id)]

    def peek(self, warp) -> tuple[int, int] | None:
        pc = warp.pc
        if pc < 0 or pc & 3 or pc + 4 > len(self.system.memory):
            return None
        instr = struct.unpack_from("<I", self.system.memory, pc)[0]
        return instr, instr >> 26

    def runnable(self, now: int):
        """Warps elegibles, en round-robin desde `cursor`."""
        for k in range(self.cfg.warps):
            warp = self.warps[(self.cursor + k) % self.cfg.warps]
            if warp.halted or warp.state == "WAIT_BAR":
                continue
            if self.busy_until[warp.warp_id] > now:
                continue
            yield warp

    def run(self, max_cycles: int = 200_000_000) -> Counters:
        cfg = self.cfg
        now = 0
        exec_free_at = 0
        while now < max_cycles and not self.system.halted:
            self.mem.tick(now)

            if exec_free_at > now:
                # La etapa de ejecucion esta ocupada: en el modelo baseline eso
                # bloquea todo, en el segmentado bloquea solo la emision.
                self.counters.exec_busy += 1
                now += 1
                continue

            warp = next(iter(self.runnable(now)), None)
            if warp is None:
                self.counters.stall_no_warp += 1
                now += 1
                continue

            peeked = self.peek(warp)
            if peeked is None:
                break
            instr, opcode = peeked
            mask = warp.active_mask
            lanes = popcount(mask)

            if opcode in MEM_OPCODES:
                addrs = [a for a in self.mem_addresses(instr, warp)
                         if a < len(self.system.memory)]
                tx = coalesced_transactions(addrs) if addrs else 0
                front = cfg.front_cycles if cfg.model == "baseline" else cfg.pipe_front
                done_at = self.mem.issue(now + front, tx) if tx else now + front
                # El warp queda esperando; otros pueden avanzar mientras.
                self.busy_until[warp.warp_id] = done_at + 1
                cost = front
            else:
                ex = self.exec_cycles(instr, opcode, warp)
                if cfg.model == "baseline":
                    cost = cfg.front_cycles + ex + cfg.back_cycles
                    exec_free_at = now + cost
                else:
                    # Segmentado: el cauce solo se ocupa durante X. El resto se
                    # solapa con otros warps.
                    cost = 1
                    exec_free_at = now + ex
                    self.busy_until[warp.warp_id] = now + cfg.pipe_front + ex + cfg.pipe_back

            if not warp.step():
                # El warp no avanzo (barrera, halt): no cobrar la instruccion.
                now += 1
                continue

            self.counters.retired += 1
            self.counters.lane_ops += lanes
            self.cursor = (warp.warp_id + 1) % cfg.warps
            now += cost
            self.sm.release_barriers() if hasattr(self.sm, "release_barriers") else None

        self.counters.cycles = now
        return self.counters
