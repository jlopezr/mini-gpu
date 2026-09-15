#!/usr/bin/env python3
"""Modelo POR CICLOS del cauce del SM, con las etapas explícitas.

Diferencia con `23.gpu-sim-uarch`, que se queda donde está:

  - 23 es un modelo de COSTE: calcula cuándo acaba cada instrucción y salta el
    reloj. Rápido, validado, responde agregados (ciclos, ocupación, burbujas).
  - éste es ESTRUCTURAL: avanza un ciclo cada vez y cada etapa tiene su
    registro con la instrucción que lleva dentro. Más lento, pero se puede
    mirar, y con él se depura un riesgo mal resuelto ANTES de escribirlo en
    Verilog.

La calibración NO se duplica: `Config`, el canal de memoria y las constantes
derivadas del RTL se importan de 23. Costó trabajo sacarlas contando estados en
`gpu_lane.v` y midiendo en `sdram_bandwidth_tb.v`; tenerlas en dos sitios sería
garantizar que un día divergen.

Las etapas son las de `22.fpga-gpu-bl8/sm-pipeline.md`:

    S  elegir warp y leer su PC
    F  presentar la direccion al bufer de instrucciones
    I  capturar la instruccion y calcular los destinos de salto
    D  decodificar y leer el banco de registros
    X  ejecutar (longitud variable, recurso UNICO: las 8 lanes)
    W  resolver salto y divergencia, actualizar PC y mascara, retirar
"""
from __future__ import annotations

import argparse
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "11.gpu-sim-func"))
sys.path.insert(0, str(ROOT / "23.gpu-sim-uarch"))

import minigpu_sim as func  # noqa: E402
import uarch  # noqa: E402
from uarch import Config, Counters, MemChannel, coalesced_transactions, popcount  # noqa: E402


STAGES = ("S", "F", "I", "D", "X", "W")


@dataclass
class Packet:
    """Lo que viaja por el cauce: una instruccion de warp."""
    warp_id: int
    pc: int
    instr: int
    opcode: int
    mask: int = 0
    exec_left: int = 0        # ciclos que le quedan en X
    is_mem: bool = False
    stalled: bool = False     # solo para el diagrama

    def __str__(self) -> str:
        tag = f"w{self.warp_id}"
        return tag + ("*" if self.stalled else "")


class Pipeline:
    def __init__(self, system: func.System, cfg: Config):
        self.system = system
        self.cfg = cfg
        self.counters = Counters()
        self.mem = MemChannel(cfg, self.counters)
        self.sm = system.streaming_multiprocessor
        self.warps = self.sm.warps
        self.stage: dict[str, Packet | None] = {name: None for name in STAGES}
        self.in_flight: set[int] = set()
        self.wait_until: dict[int, int] = {w.warp_id: 0 for w in self.warps}
        self.cursor = 0
        self.now = 0
        self.log: list[str] = []

    # ---------------------------------------------------------------- utilidades
    def peek(self, warp) -> tuple[int, int] | None:
        pc = warp.pc
        if pc < 0 or pc & 3 or pc + 4 > len(self.system.memory):
            return None
        instr = struct.unpack_from("<I", self.system.memory, pc)[0]
        return instr, instr >> 26

    # El coste de ejecucion NO se duplica aqui: sale de `uarch.exec_cycles`.
    #
    # Habia una copia, y arrastraba los mismos cuatro errores de cuenta que la
    # original (saltos, `BRA`, desplazamientos, `DIV`). Duplicar la tabla de
    # costes garantiza que los dos modelos se contradigan en cuanto alguien
    # toque uno -- que es justo lo que no puede pasar, porque el sentido de
    # tener dos es que se contrasten.
    def exec_cycles(self, instr: int, opcode: int, warp) -> int:
        return uarch.exec_cycles(self.cfg, instr, opcode, warp)

    def pick(self):
        """Warp elegible: vivo, no esperando, y SIN instruccion en el cauce.

        Esa ultima condicion es la decision de diseno de sm-pipeline.md: una
        instruccion en vuelo por warp. Elimina los riesgos RAW y de control de
        golpe, y por eso este modelo no tiene ni un bypass.
        """
        for k in range(self.cfg.warps):
            warp = self.warps[(self.cursor + k) % self.cfg.warps]
            if warp.halted or warp.state == "WAIT_BAR":
                continue
            if warp.warp_id in self.in_flight:
                continue
            if self.wait_until[warp.warp_id] > self.now:
                continue
            return warp
        return None

    # ---------------------------------------------------------------- un ciclo
    def cycle(self) -> None:
        st = self.stage
        self.mem.tick(self.now)

        # Se avanza de ATRAS hacia DELANTE para no pisar lo que aun no ha salido.

        # --- W: resolver y retirar -------------------------------------------
        if st["W"] is not None:
            pkt = st["W"]
            self.counters.retired += 1
            self.counters.lane_ops += popcount(pkt.mask)
            self.in_flight.discard(pkt.warp_id)
            st["W"] = None

        # --- X: ejecutar ------------------------------------------------------
        if st["X"] is not None:
            pkt = st["X"]
            self.counters.exec_busy += 1
            pkt.exec_left -= 1
            if pkt.exec_left <= 0:
                st["W"], st["X"] = pkt, None
            else:
                pkt.stalled = True

        # --- D -> X -----------------------------------------------------------
        if st["X"] is None and st["D"] is not None:
            pkt = st["D"]
            warp = self.warps[pkt.warp_id]
            # La ejecucion funcional ocurre AQUI: es el momento en que el RTL
            # lanzaria las lanes. El codigo no se automodifica, asi que haber
            # leido la instruccion en F sigue siendo valido.
            if pkt.is_mem:
                ra = (pkt.instr >> 16) & 0x1F
                imm = func.sign_extend(pkt.instr & 0xFFFF, 16)
                addrs = [func.u32(lane.regs[ra] + imm)
                         for lane in warp.processors
                         if warp.active_mask & (1 << lane.core_id)]
                addrs = [a for a in addrs if a < len(self.system.memory)]
                tx = coalesced_transactions(addrs) if addrs else 0
                pkt.mask = warp.active_mask
                if warp.step():
                    done_at = self.mem.issue(self.now, tx) if tx else self.now
                    self.wait_until[pkt.warp_id] = done_at
                    # Un acceso a memoria no ocupa X: sale del cauce y el warp
                    # espera, igual que hoy con wait_mem.
                    self.in_flight.discard(pkt.warp_id)
                    self.counters.retired += 1
                    self.counters.lane_ops += popcount(pkt.mask)
                st["D"] = None
            else:
                pkt.mask = warp.active_mask
                pkt.exec_left = self.exec_cycles(pkt.instr, pkt.opcode, warp)
                if warp.step():
                    st["X"], st["D"] = pkt, None
                else:
                    # Barrera o halt: el warp no avanza, suelta el hueco.
                    self.in_flight.discard(pkt.warp_id)
                    st["D"] = None
        elif st["D"] is not None:
            st["D"].stalled = True

        # --- I -> D, F -> I, S -> F -------------------------------------------
        for src, dst in (("I", "D"), ("F", "I"), ("S", "F")):
            if st[dst] is None and st[src] is not None:
                st[dst], st[src] = st[src], None
            elif st[src] is not None:
                st[src].stalled = True

        # --- elegir warp y llenar S -------------------------------------------
        # S es una etapa de verdad: en el RTL propuesto lee `pc[w]` del array
        # por warp, que es un ciclo. Ocuparla importa para el diagrama y para
        # contar bien la latencia de punta a punta.
        if st["S"] is None:
            warp = self.pick()
            if warp is None:
                self.counters.stall_no_warp += 1
            else:
                peeked = self.peek(warp)
                if peeked is not None:
                    instr, opcode = peeked
                    st["S"] = Packet(warp.warp_id, warp.pc, instr, opcode,
                                     is_mem=opcode in uarch.MEM_OPCODES)
                    self.in_flight.add(warp.warp_id)
                    self.cursor = (warp.warp_id + 1) % self.cfg.warps

        self.now += 1

    # ---------------------------------------------------------------- ejecucion
    def run(self, max_cycles: int = 50_000_000,
            trace_from: int | None = None, trace_len: int = 40) -> Counters:
        while self.now < max_cycles and not self.system.halted:
            if trace_from is not None and trace_from <= self.now < trace_from + trace_len:
                self.log.append(self.diagram())
            for pkt in self.stage.values():
                if pkt is not None:
                    pkt.stalled = False
            self.cycle()
            if all(p is None for p in self.stage.values()) and self.system.halted:
                break
        self.counters.cycles = self.now
        return self.counters

    def diagram(self) -> str:
        cells = []
        for name in STAGES:
            pkt = self.stage[name]
            cells.append(f"{str(pkt) if pkt else '--':<5}")
        return f"{self.now:>9}  " + " ".join(cells)

    @staticmethod
    def header() -> str:
        return "    ciclo  " + " ".join(f"{name:<5}" for name in STAGES)


def build_system(program: Path) -> func.System:
    system = func.System()
    data = program.read_bytes()
    system.memory[0:len(data)] = data
    system.configure_warps({"warps": [{"id": i, "enabled": True, "pc": 0,
                                       "active_mask": 0xFF} for i in range(8)]})
    return system


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("program", nargs="?",
                        default=str(ROOT / "22.fpga-gpu-bl8" / "examples" / "plasma_nommio.bin"))
    parser.add_argument("--trace-from", type=int, default=None,
                        help="imprime el diagrama de etapas desde este ciclo")
    parser.add_argument("--trace-len", type=int, default=40)
    parser.add_argument("--exec-base", type=int, default=None,
                        help="ciclos de la lane por instruccion (6 hoy; 4 si se le "
                             "quita el fetch redundante)")
    args = parser.parse_args()

    program = Path(args.program)
    if not program.exists():
        raise SystemExit(f"falta {program}")

    cfg = Config()
    if args.exec_base is not None:
        cfg.exec_base = args.exec_base
    pipe = Pipeline(build_system(program), cfg)
    counters = pipe.run(trace_from=args.trace_from, trace_len=args.trace_len)

    if pipe.log:
        print(Pipeline.header())
        for line in pipe.log:
            print(line)
        print("    (wN* = esa etapa no pudo avanzar ese ciclo)")
        print()

    print(counters.report())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
