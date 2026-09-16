#!/usr/bin/env python3
"""CLI and existing x.tests backend API for the cycle model."""
import argparse
from contextlib import ExitStack
from dataclasses import asdict
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from cycle_sim import Pipeline, Config, functional, CycleLimitExceeded

config_warp_size = functional.config_warp_size
TextTrace = functional.TextTrace
InstructionLimitExceeded = functional.InstructionLimitExceeded


class System(functional.System):
    """Reuse launch validation and state storage; all stepping uses the new pipeline."""
    def __init__(self, *args, config=None, max_cycles=1_000_000_000, **kwargs):
        super().__init__(*args, **kwargs)
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
        if self.trace is None or record['event'] not in ('retire', 'fault'): return
        w = self.streaming_multiprocessor.warps[record['warp']]
        details = tuple(f'T{lane} R{r} = 0x{v:08x}' for lane, r, v in record.get('writes', []))
        details += tuple(f'STORE 0x{a:08x} = {data}' for a, data in record.get('stores', []))
        self.trace(functional.TraceEvent(w.warp_id, record['pc'], record['mask'],
                   w.live_mask, record['instruction'], w.pc,
                   f"cycle={record['cycle']} {record['event']} {record.get('fault', '')}", details))

    def _pipeline(self):
        if self.pipeline is None:
            self.pipeline = Pipeline(self, self.config, self._trace_event if self.trace else None)
        return self.pipeline

    def step(self):
        before = self.instructions_executed
        self._pipeline().cycle()
        return self.instructions_executed != before

    def run(self, max_instructions=100_000_000):
        return self._pipeline().run(self.max_cycles, max_instructions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('program', type=Path, help='.asm, .bin or .hex')
    parser.add_argument('--warps', type=int, default=8)
    parser.add_argument('--lanes', type=int, default=8)
    parser.add_argument('--warp-config', type=Path)
    parser.add_argument('--memory-size', type=lambda s: int(s, 0), default=32 * 1024 * 1024)
    parser.add_argument('--max-cycles', type=int, default=10_000_000)
    parser.add_argument('--max-instructions', type=int, default=100_000_000)
    parser.add_argument('--trace', type=Path, help='stream JSONL cycle snapshots and events')
    parser.add_argument('--trace-from', type=int, default=0)
    parser.add_argument('--trace-cycles', type=int, default=None)
    parser.add_argument('--report', type=Path, help='JSON counters and configuration')
    parser.add_argument('--state', type=Path, help='JSON architectural warp state')
    parser.add_argument('--dump-memory', nargs=3, metavar=('ADDRESS', 'SIZE', 'FILE'))
    for field, default in asdict(Config()).items():
        parser.add_argument('--' + field.replace('_', '-'), type=int, default=default)
    args = parser.parse_args()
    try:
        cfg = Config(**{field: getattr(args, field) for field in asdict(Config())})
        if args.trace_from < 0 or args.trace_cycles is not None and args.trace_cycles < 0:
            raise ValueError('trace ranges must be nonnegative')
        if args.program.suffix.lower() == '.asm':
            sys.path.insert(0, str(HERE.parent / '1.isa'))
            from miniisa_asm import assemble_bytes
            program = assemble_bytes(args.program.read_text(encoding='utf-8'))
        elif args.program.suffix.lower() == '.hex':
            program = b''.join(int(line, 16).to_bytes(4, 'little')
                               for line in args.program.read_text().splitlines() if line.strip())
        elif args.program.suffix.lower() == '.bin':
            program = args.program.read_bytes()
        else:
            raise ValueError('expected .asm, .bin or .hex')
        gpu = System(args.memory_size, args.warps, args.lanes, config=cfg, max_cycles=args.max_cycles)
        gpu.load_program(program)
        if args.warp_config:
            gpu.configure_warps(json.loads(args.warp_config.read_text(encoding='utf-8')))
        pipeline = gpu._pipeline()
        for output in (args.trace, args.report, args.state):
            if output: output.parent.mkdir(parents=True, exist_ok=True)
        with ExitStack() as stack:
            if args.trace:
                stream = stack.enter_context(args.trace.open('w', encoding='utf-8'))
                def emit(record):
                    cycle = record['cycle']
                    if cycle >= args.trace_from and (args.trace_cycles is None or cycle < args.trace_from + args.trace_cycles):
                        stream.write(json.dumps(record) + '\n')
                pipeline.trace = emit
            limited = None
            try:
                report = gpu.run(args.max_instructions)
            except (CycleLimitExceeded, InstructionLimitExceeded) as exc:
                limited = str(exc)
                report = pipeline.counters.report()
        report.update(config=asdict(cfg), fault=asdict(gpu.fault) if gpu.fault else None,
                      halted=gpu.halted, limit=limited)
        if args.report: args.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        if args.state:
            state = [{**{key: getattr(w, key) for key in ('warp_id', 'pc', 'active_mask', 'live_mask',
                      'state', 'workgroup_id', 'barrier_generation', 'instructions_executed')},
                      'registers': [p.regs for p in w.processors],
                      'regions': [asdict(r) for r in w.region_stack],
                      'paths': [asdict(p) for p in w.path_stack]} for w in pipeline.warps]
            args.state.write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
        if args.dump_memory:
            address, size, filename = args.dump_memory
            gpu.dump_memory(int(address, 0), int(size, 0), Path(filename))
        print(json.dumps(report, indent=2))
        return 2 if limited else 1 if gpu.error else 0
    except (ValueError, OSError, functional.SimulationError) as exc:
        parser.exit(2, f'error: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
