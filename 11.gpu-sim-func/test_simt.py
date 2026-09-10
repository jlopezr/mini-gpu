import io
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '1.isa'))
from miniisa_asm import assemble, AsmError
from minigpu_sim import System, ERROR_SIMT, ERROR_BARRIER, ERROR_INVALID_ENCODING
from gpu_trace import TextTrace, instruction_text


class SimtTest(unittest.TestCase):
    def make(self, source, warps=1):
        words = assemble(source)
        gpu = System(1024, warps, 8)
        gpu.load_program(struct.pack('<' + 'I' * len(words), *words))
        return gpu

    def test_nested_paths_reconverge_once(self):
        gpu = self.make('''
            GETTID R1
            MOVI R2, 4
            SSY join
            BLT R1, R2, low
            MOVI R3, 30
            BRA join
        low:
            MOVI R2, 2
            SSY inner
            BLT R1, R2, lowest
            MOVI R3, 20
            BRA inner
        lowest:
            MOVI R3, 10
        inner:
            ADDI R3, R3, 1
        join:
            ADDI R3, R3, 1
            BAR
            EXIT
        ''')
        gpu.run(100)
        warp = gpu.streaming_multiprocessor.warps[0]
        self.assertFalse(gpu.error)
        self.assertEqual([p.regs[3] for p in warp.processors], [12, 12, 22, 22, 31, 31, 31, 31])
        self.assertEqual(warp.simt_stack, [])
        self.assertEqual(warp.live_mask, 0)

    def test_exit_in_either_path_never_reactivates(self):
        for first, second, expected in [('EXIT', 'MOVI R3, 7', [8]*4+[0]*4),
                                        ('MOVI R3, 7', 'EXIT', [0]*4+[8]*4),
                                        ('EXIT', 'EXIT', [0]*8)]:
            gpu = self.make(f'''
                GETTID R1
                MOVI R2, 4
                SSY join
                BLT R1, R2, low
                {first}
                BRA join
            low:
                {second}
            join:
                ADDI R3, R3, 1
                BAR
                EXIT
            ''')
            gpu.run(100)
            self.assertFalse(gpu.error)
            self.assertEqual([p.regs[3] for p in gpu.streaming_multiprocessor.warps[0].processors], expected)

    def test_uniform_branch_does_not_consume_ssy(self):
        gpu = self.make('''
            GETTID R1
            SSY join
            BEQ R0, R0, branch
        branch:
            BEQ R0, R1, join
            MOVI R3, 9
        join:
            ADDI R3, R3, 1
            EXIT
        ''')
        gpu.run(100)
        self.assertFalse(gpu.error)
        self.assertEqual([p.regs[3] for p in gpu.streaming_multiprocessor.warps[0].processors], [1]+[10]*7)

    def test_simt_stack_accepts_eight_frames_and_rejects_the_ninth_atomically(self):
        gpu = self.make('\n'.join(['SSY done'] * 9) + '\ndone: EXIT')
        gpu.run(20)
        warp = gpu.streaming_multiprocessor.warps[0]

        self.assertTrue(gpu.error)
        self.assertEqual(gpu.error_code, ERROR_SIMT)
        self.assertEqual(gpu.fault.pc, 8 * 4)
        self.assertEqual(gpu.fault.warp_id, 0)
        self.assertIsNone(gpu.fault.core_id)
        self.assertEqual(warp.pc, 8 * 4)
        self.assertEqual(len(warp.simt_stack), 8)
        self.assertEqual(warp.instructions_executed, 8)
        self.assertEqual(gpu.instructions_executed, 8)

    def test_divergent_loop(self):
        gpu = self.make('''
            GETTID R1
        loop:
            SSY done
            BEQ R1, R0, done
            ADDI R1, R1, -1
            ADDI R3, R3, 1
            BRA loop
        done:
            BAR
            EXIT
        ''')
        gpu.run(200)
        self.assertFalse(gpu.error)
        self.assertEqual([p.regs[3] for p in gpu.streaming_multiprocessor.warps[0].processors], list(range(8)))

    def test_invalid_barrier_and_missing_ssy_are_atomic(self):
        for prefix, code in [('', ERROR_SIMT), ('SSY join', ERROR_BARRIER)]:
            gpu = self.make(f'''
                GETTID R1
                {prefix}
                BEQ R1, R0, join
                BAR
            join:
                EXIT
            ''')
            gpu.run(100)
            self.assertEqual(gpu.error_code, code)
            self.assertIsNone(gpu.fault.core_id)

    def test_barrier_wait_release_repeat_and_trace(self):
        gpu = self.make('BAR\nMOVI R1, 1\nBAR\nEXIT', warps=2)
        w0, w1 = gpu.streaming_multiprocessor.warps
        stream = io.StringIO()
        gpu.trace = TextTrace(stream)
        gpu.step()
        self.assertEqual((w0.state, w0.pc, w0.processors[0].regs[1]), ('WAIT_BAR', 0, 0))
        self.assertFalse(w0.step())
        gpu.step()
        self.assertEqual((w0.state, w1.state, w0.pc, w1.pc), ('READY', 'READY', 4, 4))
        gpu.run(8)
        self.assertFalse(gpu.error)
        self.assertEqual((w0.barrier_generation, w1.barrier_generation), (2, 2))
        self.assertIn('WAIT_BAR', stream.getvalue())

    def test_workgroups_and_mismatched_barriers(self):
        for groups, error in [([0, 0], True), ([0, 1], False)]:
            gpu = self.make('BAR\nEXIT\nBAR\nEXIT', warps=2)
            gpu.configure_warps({'warps': [dict(id=i, pc=i*8, workgroup_id=groups[i]) for i in range(2)]})
            gpu.run(10)
            self.assertEqual(gpu.error, error)
            if error:
                self.assertEqual(gpu.error_code, ERROR_BARRIER)

    def test_finished_warp_no_longer_participates(self):
        gpu = self.make('BAR\nEXIT', warps=2)
        gpu.configure_warps({'warps': [dict(id=0), dict(id=1, pc=4)]})
        gpu.run(3)
        self.assertFalse(gpu.error)

    def test_encoding_and_assembler_validation(self):
        self.assertEqual(assemble('SSY end\nBAR\nend: EXIT'), [(0x31<<26)|1, 0x32<<26, 0x33<<26])
        self.assertEqual(assemble('SSY 0'), [(0x31<<26)|0x3ffffff])
        self.assertEqual(instruction_text((0x31<<26)|0x3ffffff), 'SSY -1')
        for text in ('BAR R1', 'EXIT 1', 'SSY', 'SSY 3'):
            with self.assertRaises(AsmError):
                assemble(text)
        for op in (0x32, 0x33):
            gpu = System(64, 1, 8)
            gpu.load_program(struct.pack('<I', (op<<26)|1))
            gpu.run(1)
            self.assertEqual(gpu.error_code, ERROR_INVALID_ENCODING)
            self.assertEqual(gpu.instructions_executed, 0)


if __name__ == '__main__':
    unittest.main()
