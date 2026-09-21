"""Incremental timing contracts and architectural differential tests."""
import sys
import unittest
from pathlib import Path

from cycle_sim import Pipeline, Config, functional, CycleLimitExceeded
from resources import transaction_count
from isa import Result

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '1.isa'))
from mini_asm import assemble_bytes


def make(source, warps=1, lanes=4, **kwargs):
    system = functional.System(8192, warps, lanes)
    system.load_program(assemble_bytes(source))
    return Pipeline(system, Config(imem_lines=0, **kwargs))


def architecture(system):
    return (bytes(system.memory), system.fault,
            [(w.pc, w.active_mask, w.live_mask, w.state, w.barrier_generation,
              w.region_stack, w.path_stack, w.instructions_executed,
              [p.regs for p in w.processors]) for w in system.streaming_multiprocessor.warps])


class PipelineTests(unittest.TestCase):
    def differential(self, source, warps=1, lanes=4, **cfg):
        pipeline = make(source, warps, lanes, **cfg)
        oracle = functional.System(8192, warps, lanes)
        oracle.load_program(assemble_bytes(source))
        oracle.run(100000)
        pipeline.run(1000000)
        self.assertEqual(architecture(pipeline.system), architecture(oracle))
        return pipeline

    def test_alu_commit_and_no_same_cycle_reschedule(self):
        p = make('MOVI R1, 7\nADDI R2, R1, 3\nHALT')
        events = []
        p.trace = events.append
        w = p.warps[0]
        while not p.system.halted:
            before = p.stages.copy()
            p.cycle()
            if not any(e['event'] == 'retire' for e in events):
                self.assertEqual(w.processors[0].regs[1], 0)
            if before['W'] and before['W'].pc == 0:
                self.assertIsNone(p.stages['S'])
                self.assertEqual(w.processors[0].regs[1], 7)
        retires = [e for e in events if e['event'] == 'retire']
        self.assertEqual([e['cycle'] for e in retires], [6, 13, 19])
        self.assertEqual(w.processors[0].regs[2], 10)

    def test_alu_multiple_warps(self):
        p = self.differential('GETTID R1\nADDI R2,R1,5\nADD R0,R1,R2\nHALT', 8)
        self.assertEqual(p.counters.retired, 32)
        self.assertEqual(p.counters.occupancy['X'], 24)
        self.assertEqual(p.counters.lane_ops, 128)

    def test_multicycle_blocks_x_and_retains_front(self):
        p = make('MOVI R1,9\nMOVI R2,2\nDIV R3,R1,R2\nADD R4,R1,R2\nHALT', warps=8)
        events = []
        p.trace = events.append
        p.run()
        self.assertGreater(p.counters.stall_x, 0)
        self.assertEqual(p.counters.multicycle['DIV'], 8 * 32)
        retires = [e['serial'] for e in events if e['event'] == 'retire']
        self.assertEqual(retires, sorted(retires))
        self.assertTrue(all(w.processors[0].regs[3:5] == [4, 11] for w in p.warps))

    def test_shift_timing_uses_active_lanes(self):
        p = make('SHL R3,R1,R2\nHALT', lanes=4)
        for lane, n in zip(p.warps[0].processors, (0, 2, 7, 31)):
            lane.regs[1:3] = [1, n]
        p.warps[0].active_mask = p.warps[0].live_mask = 7
        p.run()
        self.assertEqual(p.counters.occupancy['X'], 7)
        self.assertEqual(p.warps[0].processors[2].regs[3], 128)
        self.assertEqual(p.warps[0].processors[3].regs[3], 0)

    def test_x_occupancy_breakdown_and_partial_execution(self):
        p = make('MOVI R1,8\nMOVI R2,2\nMUL R3,R1,R2\n'
                 'SHL R4,R1,R2\nDIV R5,R1,R2\nBRA done\ndone: HALT')
        while not (p.stages['X'] and p.stages['X'].decoded.op == 0xc):
            p.cycle()
        p.cycle()
        partial = p.counters.report()
        self.assertEqual(partial['x_cycles_by_opcode']['DIV'], 1)
        self.assertEqual(sum(partial['x_cycles_by_unit'].values()), partial['occupancy']['X'])
        p.run()
        report = p.counters.report()
        self.assertEqual(report['x_cycles_by_unit'],
                         dict(ALU=2, MUL=4, SHIFT=2, DIV=32, CONTROL=1, FAULT=0))
        self.assertEqual(sum(report['x_cycles_by_opcode'].values()), report['occupancy']['X'])
        import io
        from minigpu_cycle import print_report
        output = io.StringIO()
        print_report(report, p.system, output)
        self.assertIn('OCUPACIÓN X POR TIPO', output.getvalue())
        self.assertIn('78.0 %', output.getvalue())

    def test_divergence_reuse_and_partial_exit(self):
        self.differential('''
            GETTID R1
            MOVI R4, 7
        loop: SSY done
            BGE R2,R4,done
            BGE R2,R1,done
            ADDI R2,R2,1
            BRA loop
        done: ADDI R3,R2,0
            BAR
            EXIT
        ''', warps=2)
        self.differential('''
            GETTID R1
            SSY done
            BEQ R1,R0,early
            MOVI R2,17
            BRA done
        early: EXIT
        done: ADDI R3,R2,1
            BAR
            EXIT
        ''')

    def test_simt_and_barrier_errors(self):
        for source in ('GETTID R1\nBEQ R1,R0,end\nNOP\nend: HALT',
                       'GETTID R1\nSSY end\nBEQ R1,R0,end\nBAR\nend: HALT'):
            self.differential(source)

    def test_memory_visibility_and_atomic_fault(self):
        p = make('STORE R1,R2,0\nHALT', memory_cycles=4)
        for lane in p.warps[0].processors:
            lane.regs[1:3] = [123, 4096 + lane.core_id * 4]
        while not p.lsu: p.cycle()
        self.assertEqual(p.system.memory[4096:4112], bytes(16))
        self.assertIn(0, p.in_flight)
        p.run()
        self.assertEqual(p.system.memory[4096:4112], (123).to_bytes(4,'little') * 4)
        p = make('STORE R1,R2,0\nHALT', memory_cycles=2)
        for lane in p.warps[0].processors: lane.regs[1:3] = [123, 4096]
        p.warps[0].processors[3].regs[2] = 8192
        before = bytes(p.system.memory)
        p.run()
        self.assertEqual(bytes(p.system.memory), before)
        self.assertEqual(p.system.fault.code, 2)
        self.assertEqual(p.system.fault.core_id, 3)
        self.assertEqual(p.counters.retired, 0)

    def test_memory_and_barriers(self):
        self.differential('''
            GETTID R1
            MOVI R2,4
            MUL R2,R1,R2
            ADDI R2,R2,4096
            STORE R1,R2,0
            BAR
            LOAD R3,R2,0
            BAR
            EXIT
        ''', warps=8, memory_cycles=3, lsu_slots=2)

    def test_subword_and_extensions(self):
        p = make('''
            MOVI R1,-7
            MOVI R2,2
            REM R3,R1,R2
            STOREB R3,R0,4097
            LOADB R4,R0,4097
            LOADUB R5,R0,4097
            STOREH R1,R0,4098
            LOADH R6,R0,4098
            LOADUH R7,R0,4098
            SHLI R8,R2,31
            SLT R9,R1,R2
            HALT
        ''', lanes=1)
        p.run()
        self.assertEqual(p.warps[0].processors[0].regs[3:10],
                         [0xffffffff,0xffffffff,255,0xfffffff9,65529,0,1])

    def test_fetch_miss_holds_packet_once(self):
        p = make('MOVI R1,7\nADDI R1,R1,1\nHALT')
        p.config = Config(imem_lines=1, imem_miss_cycles=5)
        p.run()
        self.assertEqual(p.counters.imem_misses, 1)
        self.assertEqual(p.counters.imem_hits, 2)
        self.assertEqual(p.counters.stall_fetch, 5)
        self.assertEqual(p.warps[0].processors[0].regs[1], 8)

    def test_limits_and_bad_fetch(self):
        p = make('BRA 0')
        with self.assertRaises(CycleLimitExceeded): p.run(20)
        p = make('HALT')
        p.warps[0].pc = 8192
        p.run()
        self.assertEqual(p.system.error_code, 2)
        self.assertEqual(p.system.error_pc, 8192)
        self.assertEqual(p.counters.retired, 0)

    def test_coalescing_duplicate_stores(self):
        requests = [(i, Result(4, access=(4096, 4, i, False))) for i in range(4)]
        self.assertEqual(transaction_count(requests), 4)
        requests = [(i, Result(4, access=(4096, 4, None, False))) for i in range(4)]
        self.assertEqual(transaction_count(requests), 1)

    def test_load_response_waits_for_rf_and_retains_data(self):
        p = make('LOAD R1,R0,4096\nHALT\nMOVI R2,9\nHALT',
                 warps=2, lanes=1, memory_cycles=3)
        p.warps[1].pc = 8
        p.system.memory[4096:4100] = (123).to_bytes(4, 'little')
        events = []
        p.trace = events.append
        for _ in range(30):
            if p.counters.writeback_collisions: break
            p.cycle()
        self.assertEqual(p.counters.writeback_collisions, 1)
        self.assertEqual(p.warps[0].processors[0].regs[1], 0)
        self.assertEqual(p.warps[0].pc, 0)
        self.assertIn(0, p.in_flight)
        self.assertEqual(p.warps[1].processors[0].regs[2], 9)
        self.assertTrue(p.lsu[0].response_ready)
        # A response must not be resampled while the write port is unavailable.
        p.system.memory[4096:4100] = (456).to_bytes(4, 'little')
        p.cycle()
        self.assertEqual(p.warps[0].processors[0].regs[1], 123)
        self.assertNotIn(0, p.in_flight)
        self.assertTrue(p.stages['S'] is None or p.stages['S'].warp != 0)
        p.run()
        self.assertEqual(p.counters.writeback_collisions, 1)
        self.assertEqual(p.counters.stall_writeback, 1)
        self.assertEqual(p.counters.response_arrival_collisions, 1)
        response = next(e for e in events if e['event'] == 'lsu_response')
        retirement = next(e for e in events if e['event'] == 'retire' and e['pc'] == 0)
        self.assertEqual(retirement['cycle'], response['cycle'] + 1)

    def test_rf_free_completions_can_share_edge(self):
        for instruction in ('NOP', 'ADD R0,R0,R0'):
            p = make(f'LOAD R1,R0,4096\nHALT\n{instruction}\nHALT',
                     warps=2, lanes=1, memory_cycles=3)
            p.warps[1].pc = 8
            p.run()
            self.assertEqual(p.counters.writeback_collisions, 0)
            self.assertGreaterEqual(p.counters.simultaneous_completions, 1)

    def test_uart_response_no_consume_hasta_commit(self):
        p = make('LOAD R1,R3,0\nHALT\nMOVI R2,9\nHALT',
                 warps=2, lanes=1, memory_cycles=3)
        p.system.serial = functional.SerialDevice(stdin=b'AB')
        p.warps[0].processors[0].regs[3] = p.system.serial.BASE
        p.warps[1].pc = 8
        for _ in range(30):
            if p.counters.writeback_collisions:
                break
            p.cycle()
        self.assertEqual(p.counters.writeback_collisions, 1)
        self.assertTrue(p.lsu[0].response_ready)
        self.assertEqual(p.system.serial.rx, b'AB')
        p.cycle()
        self.assertEqual(p.warps[0].processors[0].regs[1], ord('A'))
        self.assertEqual(p.system.serial.rx, b'B')
        p.run()
        self.assertEqual(p.system.serial.rx, b'B')

    def test_memory_progresses_while_x_is_busy(self):
        p = make('LOAD R1,R0,4096\nHALT\nDIV R3,R1,R2\nHALT',
                 warps=2, lanes=1, memory_cycles=6)
        p.warps[1].pc = 8
        p.warps[1].processors[0].regs[1:3] = [10, 2]
        while not p.warps[0].instructions_executed: p.cycle()
        self.assertIsNotNone(p.stages['X'])
        self.assertEqual(p.stages['X'].warp, 1)
        self.assertGreater(p.stages['X'].remaining, 1)
        p.run()

    def test_barrier_release_is_independent_of_busy_x(self):
        p = make('BAR\nHALT\nDIV R3,R1,R2\nHALT', warps=2, lanes=1)
        p.warps[1].pc = 8
        p.warps[1].workgroup_id = 1
        p.warps[1].processors[0].regs[1:3] = [8, 2]
        for _ in range(20):
            p.cycle()
            if p.counters.barrier_releases: break
        self.assertEqual(p.counters.barrier_releases, 1)
        self.assertEqual(p.warps[0].state, 'READY')
        self.assertIsNotNone(p.stages['X'])
        self.assertGreater(p.stages['X'].remaining, 1)
        p.run()

    def test_full_lsu_and_fifo_memory_order(self):
        p = make('STORE R1,R0,4096\nHALT\nLOAD R2,R0,4096\nHALT',
                 warps=2, lanes=1, lsu_slots=1, memory_cycles=20)
        p.warps[0].processors[0].regs[1] = 987
        p.warps[1].pc = 8
        p.run()
        self.assertGreater(p.counters.stall_lsu_full, 0)
        self.assertEqual(p.warps[1].processors[0].regs[2], 987)
        self.assertEqual(p.counters.lsu_transactions, 2)

    def test_direct_mapped_conflict_misses(self):
        p = make('MOVI R1,1\nHALT\nNOP\nNOP\nMOVI R1,2\nHALT', warps=2, lanes=1)
        p.config = Config(imem_lines=1, imem_miss_cycles=3)
        p.warps[1].pc = 16
        p.run()
        self.assertEqual(p.counters.imem_misses, 4)
        self.assertEqual(p.counters.imem_hits, 0)
        self.assertEqual(p.counters.stall_fetch, 12)


if __name__ == '__main__': unittest.main()
