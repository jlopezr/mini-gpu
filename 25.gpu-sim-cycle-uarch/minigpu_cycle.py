#!/usr/bin/env python3
"""CLI and x.tests backend API for the cycle-accurate MiniGPU model.

The command-line interface keeps the architectural tracing options of the
functional simulator and adds separate cycle/microarchitectural tracing.

Architectural trace:
    --trace
    --trace-detail
    --trace-limit
    --trace-file

Cycle trace:
    --cycle-trace
    --cycle-trace-from
    --cycle-trace-cycles

Human-readable pipeline trace:
    --pipeline-trace
    --pipeline-trace-file
    --pipeline-from
    --pipeline-cycles
"""

import argparse
from contextlib import ExitStack, nullcontext
from dataclasses import asdict
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from cycle_sim import Pipeline, Config, functional, CycleLimitExceeded

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.sysid_device import SysIdDevice  # noqa: E402


VideoDevice = functional.VideoDevice
SerialDevice = functional.SerialDevice
config_warp_size = functional.config_warp_size
TextTrace = functional.TextTrace
InstructionLimitExceeded = functional.InstructionLimitExceeded

def print_report(report, gpu, stream=sys.stdout):
    cycles = report["cycles"]
    retired = report["retired"]
    cpi = report["cpi"]

    print("", file=stream)
    print("RESUMEN", file=stream)
    print(f"  Ciclos                 {cycles:>10}", file=stream)
    print(f"  Instrucciones          {retired:>10}", file=stream)
    print(
        f"  CPI                    {cpi:>10.2f}"
        if cpi is not None
        else "  CPI                             -",
        file=stream,
    )
    print(f"  Operaciones de lane    {report['lane_ops']:>10}", file=stream)

    print("", file=stream)
    print("PIPELINE", file=stream)
    print(f"  Utilización X          {100 * report['x_utilization']:>9.1f} %", file=stream)
    print(f"  Stalls X               {report['stall_x']:>10}", file=stream)
    print(f"  Sin warp elegible      {report['stall_no_warp']:>10}", file=stream)
    print(f"  Stalls fetch           {report['stall_fetch']:>10}", file=stream)

    if report["stall_lsu_full"]:
        print(f"  Stalls LSU llena       {report['stall_lsu_full']:>10}", file=stream)

    # Memory/LSU information is interesting when memory was actually used
    # or when some exceptional condition occurred.
    memory_used = (
        report["lsu_transactions"]
        or report["stall_writeback"]
        or report["writeback_collisions"]
    )

    if memory_used:
        print("", file=stream)
        print("MEMORIA", file=stream)
        print(f"  Transacciones LSU      {report['lsu_transactions']:>10}", file=stream)

        if report["writeback_collisions"]:
            print(
                f"  Colisiones writeback   "
                f"{report['writeback_collisions']:>10}",
                file=stream,
            )

        if report["stall_writeback"]:
            print(
                f"  Stalls writeback       "
                f"{report['stall_writeback']:>10}",
                file=stream,
            )

    hits = report["imem_hits"]
    misses = report["imem_misses"]

    if hits or misses:
        total = hits + misses
        hit_rate = 100.0 * hits / total

        print("", file=stream)
        print("FETCH", file=stream)
        print(f"  Hits                   {hits:>10}", file=stream)
        print(f"  Misses                 {misses:>10}", file=stream)
        print(f"  Hit rate               {hit_rate:>9.1f} %", file=stream)

    if report["reconvergence"] or report["barrier_releases"]:
        print("", file=stream)
        print("SIMT", file=stream)

        if report["reconvergence"]:
            print(
                f"  Reconvergencias        "
                f"{report['reconvergence']:>10}",
                file=stream,
            )

        if report["barrier_releases"]:
            print(
                f"  Barreras liberadas     "
                f"{report['barrier_releases']:>10}",
                file=stream,
            )

    print("", file=stream)

    if gpu.fault:
        f = gpu.fault
        print(
            "Terminación: "
            f"FAULT code={f.code}, "
            f"W{f.warp_id} lane {f.core_id}, "
            f"PC=0x{f.pc:08X}",
            file=stream,
        )
    elif report.get("limit"):
        print(f"Terminación: LIMIT ({report['limit']})", file=stream)
    else:
        print("Terminación: HALT", file=stream)

class System(functional.System):
    """Reuse architectural state/launch validation; stepping uses the pipeline."""

    def __init__(
        self,
        *args,
        config=None,
        max_cycles=1_000_000_000,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        # El bloque de identificacion se HEREDA del modelo funcional, y por eso
        # hay que corregir la carpeta: sin esto contesta "soy la 11", que es
        # peor que no tenerlo. Son dos modelos distintos de la misma ISA --uno
        # funcional y otro con pipeline-- y lo que los distingue es justo lo que
        # SYS_ID tiene que decir.
        #
        # El perfil de ISA si es el mismo: este modelo ejecuta el mismo juego,
        # lo que cambia es CUANDO, no QUE. Un test lo contrasta.
        self.sysid = SysIdDevice(
            folder=25, isa_profile=functional.SIMULATOR_ISA_PROFILE)
        self.config = config or Config()
        self.max_cycles = max_cycles
        self.pipeline = None

    def reset(self):
        super().reset()
        self.pipeline = None

    def load_program(self, *args, **kwargs):
        super().load_program(*args, **kwargs)
        self.pipeline = None

    def configure_warps(self, config):
        super().configure_warps(config)
        self.pipeline = None

    def _trace_event(self, record):
        """Translate cycle-model retire/fault events to the old TextTrace API."""
        if self.trace is None:
            return

        if record["event"] not in ("retire", "fault"):
            return

        w = self.streaming_multiprocessor.warps[record["warp"]]

        details = tuple(
            f"T{lane} R{reg} = 0x{value:08X}"
            for lane, reg, value in record.get("writes", ())
        )

        details += tuple(
            f"STORE 0x{address:08X} = {data}"
            for address, data in record.get("stores", ())
        )

        if record["event"] == "fault":
            fault = record.get("fault")

            self.trace.fault(
                functional.TraceEvent(
                    w.warp_id,
                    record["pc"],
                    record["mask"],
                    w.live_mask,
                    record["instruction"],
                    w.pc,
                    f"cycle={record['cycle']} fault {fault}",
                    (),
                )
            )
            return

        outcome = f"cycle={record['cycle']}"

        self.trace(
            functional.TraceEvent(
                w.warp_id,
                record["pc"],
                record["mask"],
                w.live_mask,
                record["instruction"],
                w.pc,
                outcome,
                details,
            )
        )

    def _pipeline(self):
        if self.pipeline is None:
            self.pipeline = Pipeline(
                self,
                self.config,
                self._trace_event if self.trace else None,
            )
        return self.pipeline

    def step(self):
        before = self.instructions_executed
        self._pipeline().cycle()
        return self.instructions_executed != before

    def run(self, max_instructions=100_000_000):
        return self._pipeline().run(self.max_cycles, max_instructions)


class PipelineTrace:
    """Compact human-readable view of S/F/I/D/X/W and the LSU."""

    def __init__(self, stream, start=0, cycles=None):
        self.stream = stream
        self.start = start
        self.end = None if cycles is None else start + cycles
        self.header_written = False

    def accepts(self, cycle):
        return cycle >= self.start and (
            self.end is None or cycle < self.end
        )

    @staticmethod
    def packet_text(packet, stage):
        if packet is None:
            return "."

        warp = packet["warp"]
        pc = packet["pc"]
        remaining = packet.get("remaining", 0)

        text = f"W{warp}:{pc:04X}"

        # El contador solo tiene significado visual durante
        # una operación multicycle activa.
        if stage in ("F", "X", "LSU") and remaining > 1:
            text += f"({remaining})"

        return text

    def __call__(self, record):
        if record["event"] != "snapshot":
            return

        cycle = record["cycle"]

        if not self.accepts(cycle):
            return

        if not self.header_written:
            self.stream.write(
                " cycle | S            F            I            D"
                "            X            W            LSU\n"
            )
            self.stream.write(
                "-------+------------------------------------------------"
                "---------------------------------------------\n"
            )
            self.header_written = True

        stages = record["stages"]
        lsu = record.get("lsu", ())

        stage_values = [
            self.packet_text(stages[name], name)
            for name in "SFIDXW"
        ]

        if lsu:
            lsu_text = ",".join(self.packet_text(packet, "LSU") for packet in lsu)
        else:
            lsu_text = "."

        self.stream.write(
            f"{cycle:6d} | "
            + " ".join(f"{value:<12}" for value in stage_values)
            + f" {lsu_text}\n"
        )


def load_program(path):
    # La logica vive en 1.isa/miniisa_asm.py para que los tres simuladores
    # carguen igual. Estaba solo aqui, y por eso `gpusim programa.asm` fallaba
    # mientras `gpusim-cycle programa.asm` funcionaba.
    sys.path.insert(0, str(HERE.parent / "1.isa"))
    from miniisa_asm import load_program_bytes

    return load_program_bytes(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "program",
        type=Path,
        help=".asm, .bin or .hex",
    )

    # ------------------------------------------------------------------
    # Old/functional-compatible machine options.
    # ------------------------------------------------------------------

    parser.add_argument(
        "--num-warps", "--warps",
        dest="num_warps",
        type=int,
        default=8,
        help="number of warps (alias: --warps)",
    )

    parser.add_argument(
        "--warp-size", "--lanes",
        dest="warp_size",
        type=int,
        default=8,
        help="lanes per warp (alias: --lanes)",
    )

    parser.add_argument(
        "--config", "--warp-config",
        dest="warp_config",
        type=Path,
        help="JSON with initial warp configuration",
    )

    parser.add_argument(
        "--memory-size",
        type=lambda s: int(s, 0),
        default=32 * 1024 * 1024,
    )

    parser.add_argument(
        "--max", "--max-instructions",
        dest="max_instructions",
        type=int,
        default=100_000_000,
        help="maximum retired warp instructions",
    )

    parser.add_argument(
        "--dump", "--dump-memory",
        dest="dump_memory",
        nargs=3,
        metavar=("ADDRESS", "SIZE", "FILE"),
        help="dump a memory range after execution",
    )

    # ------------------------------------------------------------------
    # Architectural trace: compatible with the functional simulator.
    # ------------------------------------------------------------------

    parser.add_argument(
        "--trace",
        action="store_true",
        help="show architectural retire/fault trace",
    )

    parser.add_argument(
        "--trace-detail",
        action="store_true",
        help="include register and memory effects in architectural trace",
    )

    parser.add_argument(
        "--trace-limit",
        type=int,
        help="maximum architectural trace entries shown; does not limit execution",
    )

    parser.add_argument(
        "--trace-file",
        type=Path,
        help="write architectural trace as UTF-8 instead of stderr",
    )

    # ------------------------------------------------------------------
    # Cycle-accurate JSONL trace.
    # ------------------------------------------------------------------

    parser.add_argument(
        "--cycle-trace",
        type=Path,
        help="write complete cycle/event trace as JSONL",
    )

    parser.add_argument(
        "--cycle-trace-from",
        type=int,
        default=0,
        help="first cycle written to --cycle-trace",
    )

    parser.add_argument(
        "--cycle-trace-cycles",
        type=int,
        default=None,
        help="number of cycles written to --cycle-trace",
    )

    # ------------------------------------------------------------------
    # Human-readable pipeline trace.
    # ------------------------------------------------------------------

    parser.add_argument(
        "--pipeline-trace",
        action="store_true",
        help="show human-readable S/F/I/D/X/W/LSU trace",
    )

    parser.add_argument(
        "--pipeline-trace-file",
        type=Path,
        help="write human-readable pipeline trace instead of stderr",
    )

    parser.add_argument(
        "--pipeline-from",
        type=int,
        default=0,
        help="first cycle shown by --pipeline-trace",
    )

    parser.add_argument(
        "--pipeline-cycles",
        type=int,
        default=None,
        help="number of cycles shown by --pipeline-trace",
    )

    # ------------------------------------------------------------------
    # Reports/state.
    # ------------------------------------------------------------------

    parser.add_argument(
        "--report",
        type=Path,
        help="write counters and microarchitectural configuration as JSON",
    )

    parser.add_argument(
        "--state",
        type=Path,
        help="write final architectural warp state as JSON",
    )

    parser.add_argument(
        "--max-cycles",
        type=int,
        default=10_000_000,
        help="maximum simulated clock cycles",
    )

    # ------------------------------------------------------------------
    # Microarchitectural timing/resource parameters.
    # ------------------------------------------------------------------

    for field, default in asdict(Config()).items():
        parser.add_argument(
            "--" + field.replace("_", "-"),
            type=int,
            default=default,
        )

    from tools import sim_peripherals
    sim_peripherals.add_arguments(parser)
    args = parser.parse_args()

    try:
        cfg = Config(
            **{
                field: getattr(args, field)
                for field in asdict(Config())
            }
        )

        for name in (
            "trace_limit",
            "cycle_trace_from",
            "cycle_trace_cycles",
            "pipeline_from",
            "pipeline_cycles",
        ):
            value = getattr(args, name)
            if value is not None and value < 0:
                raise ValueError(f"{name.replace('_', '-')} must be nonnegative")

        if args.max_cycles < 0:
            raise ValueError("max-cycles must be nonnegative")

        if args.max_instructions < 0:
            raise ValueError("max-instructions must be nonnegative")

        program = load_program(args.program)

        gpu = System(
            args.memory_size,
            args.num_warps,
            args.warp_size,
            config=cfg,
            max_cycles=args.max_cycles,
            **sim_peripherals.from_arguments(args),
        )

        gpu.load_program(program)

        if args.warp_config:
            gpu.configure_warps(
                json.loads(
                    args.warp_config.read_text(encoding="utf-8")
                )
            )

        # --trace-detail, --trace-file and --trace-limit imply an
        # architectural trace, matching the old simulator's behaviour.
        architectural_tracing = (
            args.trace
            or args.trace_detail
            or args.trace_file is not None
            or args.trace_limit is not None
        )

        pipeline_tracing = (
            args.pipeline_trace
            or args.pipeline_trace_file is not None
        )

        # Create output directories before opening anything.
        for output in (
            args.trace_file,
            args.cycle_trace,
            args.pipeline_trace_file,
            args.report,
            args.state,
        ):
            if output:
                output.parent.mkdir(parents=True, exist_ok=True)

        with ExitStack() as stack:
            # ----------------------------------------------------------
            # Architectural TextTrace.
            # ----------------------------------------------------------

            if architectural_tracing:
                if args.trace_file:
                    arch_stream = stack.enter_context(
                        args.trace_file.open("w", encoding="utf-8")
                    )
                else:
                    arch_stream = sys.stderr

                gpu.trace = TextTrace(
                    arch_stream,
                    detail=args.trace_detail,
                    limit=args.trace_limit,
                )

            # Pipeline must be constructed after gpu.trace has been set so
            # System._pipeline() can install the compatibility callback.
            pipeline = gpu._pipeline()

            # ----------------------------------------------------------
            # Raw JSONL cycle trace.
            # ----------------------------------------------------------

            cycle_stream = None

            if args.cycle_trace:
                cycle_stream = stack.enter_context(
                    args.cycle_trace.open("w", encoding="utf-8")
                )

            # ----------------------------------------------------------
            # Human pipeline trace.
            # ----------------------------------------------------------

            human_pipeline_trace = None

            if pipeline_tracing:
                if args.pipeline_trace_file:
                    pipeline_stream = stack.enter_context(
                        args.pipeline_trace_file.open("w", encoding="utf-8")
                    )
                else:
                    pipeline_stream = sys.stderr

                human_pipeline_trace = PipelineTrace(
                    pipeline_stream,
                    args.pipeline_from,
                    args.pipeline_cycles,
                )

            # ----------------------------------------------------------
            # Fan out Pipeline.event() to all requested observers.
            # ----------------------------------------------------------

            def emit(record):
                # Architectural compatibility trace.
                if gpu.trace is not None:
                    gpu._trace_event(record)

                # Complete machine-readable cycle trace.
                if cycle_stream is not None:
                    cycle = record["cycle"]

                    if (
                        cycle >= args.cycle_trace_from
                        and (
                            args.cycle_trace_cycles is None
                            or cycle
                            < args.cycle_trace_from
                            + args.cycle_trace_cycles
                        )
                    ):
                        cycle_stream.write(json.dumps(record) + "\n")

                # Compact human-readable pipeline snapshots.
                if human_pipeline_trace is not None:
                    human_pipeline_trace(record)

            pipeline.trace = emit if (
                architectural_tracing
                or cycle_stream is not None
                or human_pipeline_trace is not None
            ) else None

            limited = None

            try:
                report = gpu.run(args.max_instructions)

            except (CycleLimitExceeded, InstructionLimitExceeded) as exc:
                limited = str(exc)
                report = pipeline.counters.report()

            # Finish old-style architectural trace.
            if gpu.trace is not None:
                if gpu.fault:
                    final = f"{gpu.fault}; {gpu.instructions_executed} instrucciones de warp"
                elif limited:
                    final = (
                        f"SIMULADOR: {limited}; "
                        f"{gpu.instructions_executed} instrucciones de warp"
                    )
                else:
                    final = (
                        f"HALT; "
                        f"{gpu.instructions_executed} instrucciones de warp"
                    )

                gpu.trace.finish(final)

            report.update(
                config=asdict(cfg),
                fault=asdict(gpu.fault) if gpu.fault else None,
                halted=gpu.halted,
                limit=limited,
            )

            if args.report:
                args.report.write_text(
                    json.dumps(report, indent=2) + "\n",
                    encoding="utf-8",
                )

            if args.state:
                state = [
                    {
                        **{
                            key: getattr(w, key)
                            for key in (
                                "warp_id",
                                "pc",
                                "active_mask",
                                "live_mask",
                                "state",
                                "workgroup_id",
                                "barrier_generation",
                                "instructions_executed",
                            )
                        },
                        "registers": [
                            processor.regs
                            for processor in w.processors
                        ],
                        "regions": [
                            asdict(region)
                            for region in w.region_stack
                        ],
                        "paths": [
                            asdict(path)
                            for path in w.path_stack
                        ],
                    }
                    for w in pipeline.warps
                ]

                args.state.write_text(
                    json.dumps(state, indent=2) + "\n",
                    encoding="utf-8",
                )

            if args.dump_memory:
                address, size, filename = args.dump_memory
                gpu.dump_memory(
                    int(address, 0),
                    int(size, 0),
                    Path(filename),
                )

            sim_peripherals.write_outputs(args, gpu)
            print_report(report, gpu)

            return 2 if limited else 1 if gpu.error else 0

    except (ValueError, OSError, functional.SimulationError) as exc:
        parser.exit(2, f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())