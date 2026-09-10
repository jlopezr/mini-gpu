"""Behavioral coverage for reusable regions and independent finite path storage."""

import copy
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '1.isa'))
from miniisa_asm import assemble
from minigpu_sim import System, ERROR_SIMT, ERROR_MEMORY_ACCESS


class RegionTest(unittest.TestCase):
    def make(self, source, **limits):
        gpu = System(2048, 1, 8, **limits)
        words = assemble(source)
        gpu.load_program(struct.pack('<' + 'I' * len(words), *words))
        return gpu

    def snapshot(self, gpu):
        w = gpu.streaming_multiprocessor.warps[0]
        return copy.deepcopy((w.pc, w.active_mask, w.live_mask, w.state,
                              w.region_stack, w.path_stack,
                              [p.regs for p in w.processors], bytes(gpu.memory),
                              gpu.instructions_executed))

    def run_checked(self, gpu, limit=20000):
        """Check architectural invariants after every retired instruction."""
        w = gpu.streaming_multiprocessor.warps[0]
        history = []
        while not gpu.halted:
            self.assertLess(gpu.instructions_executed, limit)
            before = self.snapshot(gpu)
            gpu.step()
            if gpu.error:
                self.assertEqual(self.snapshot(gpu), before, 'fault must be atomic')
                break
            self.assertEqual(w.active_mask & ~w.live_mask, 0)
            occupied = w.active_mask
            for path in w.path_stack:
                mask = path.pending_mask & w.live_mask
                self.assertNotEqual(mask, 0)
                self.assertEqual(mask & occupied, 0)
                occupied |= mask
            bases = [r.path_base for r in w.region_stack]
            self.assertEqual(bases, sorted(bases))
            self.assertTrue(all(base <= len(w.path_stack) for base in bases))
            if w.region_stack:
                self.assertEqual(w.active_mask & ~w.region_stack[-1].entry_mask, 0)
            else:
                self.assertEqual(w.path_stack, [])
            history.append((w.pc, w.active_mask, tuple(w.region_stack), tuple(w.path_stack)))
        return w, history

    def test_long_escape_loop_reuses_original_mask_even_when_region_stack_full(self):
        for position in ('inside', 'outside'):
            with self.subTest(position=position):
                opening = 'loop: SSY done' if position == 'inside' else 'SSY done\nloop:'
                gpu = self.make(f'''
                    GETTID R1
                    ADDI R1, R1, 100
                    MOVI R4, 128
                    {opening}
                    BGE R2, R4, done
                    BGE R2, R1, done
                    ADDI R2, R2, 1
                    BRA loop
                done:
                    ADDI R3, R2, 0
                    BAR
                    EXIT
                ''', simt_region_depth=1, simt_path_depth=1)
                w, history = self.run_checked(gpu)
                self.assertFalse(gpu.error)
                self.assertEqual([p.regs[3] for p in w.processors], list(range(100, 108)))
                self.assertEqual(max(len(r) for _, _, r, _ in history), 1)
                self.assertTrue(all(not paths for _, _, _, paths in history))
                self.assertTrue(any(mask == 0x80 and r[0].entry_mask == 0xff
                                    for _, mask, r, _ in history if r))
                self.assertEqual(w.region_stack, [])

    def pending_loop(self, **limits):
        return self.make('''
            GETTID R1
        loop:
            SSY done
            BEQ R1, R0, handler
            ADDI R1, R1, -1
            BRA loop
        handler:
            ADDI R3, R3, 10
            BRA done
        done:
            ADDI R3, R3, 1
            EXIT
        ''', **limits)

    def test_repeated_ssy_keeps_seven_paths_and_original_region(self):
        gpu = self.pending_loop(simt_region_depth=1, simt_path_depth=7)
        w, history = self.run_checked(gpu)
        self.assertFalse(gpu.error)
        self.assertEqual([p.regs[3] for p in w.processors], [11] * 8)
        self.assertEqual(max(len(p) for _, _, _, p in history), 7)
        regions = [r[0] for _, _, r, _ in history if r]
        self.assertTrue(all(r == regions[0] for r in regions))
        self.assertEqual((w.region_stack, w.path_stack), ([], []))

    def test_path_overflow_is_atomic_and_independent_of_region_capacity(self):
        gpu = self.pending_loop(simt_region_depth=8, simt_path_depth=2)
        w, _ = self.run_checked(gpu)
        self.assertEqual(gpu.error_code, ERROR_SIMT)
        self.assertEqual((len(w.region_stack), len(w.path_stack)), (1, 2))
        self.assertEqual(w.pc, 8)  # BEQ, not SSY
        self.assertIsNone(gpu.fault.core_id)

    def test_nested_region_cannot_run_outer_pending_path_early(self):
        gpu = self.make('''
            GETTID R1
            MOVI R2, 4
            SSY outer
            BLT R1, R2, low
            MOVI R2, 6
            SSY inner
            BLT R1, R2, middle
            MOVI R3, 30
            BRA inner
        middle:
            MOVI R3, 20
        inner:
            ADDI R3, R3, 1
            BRA outer
        low:
            MOVI R3, 10
        outer:
            ADDI R3, R3, 1
            BAR
            EXIT
        ''')
        w, history = self.run_checked(gpu)
        self.assertFalse(gpu.error)
        self.assertEqual([p.regs[3] for p in w.processors], [11]*4 + [22]*2 + [32]*2)
        self.assertTrue(any(len(r) == 2 and r[-1].path_base == 1 and len(p) == 2
                            for _, _, r, p in history))

    def test_multiple_different_pending_destinations_in_one_region(self):
        gpu = self.make('''
            GETTID R1
            MOVI R2, 2
            SSY done
            BLT R1, R2, low
            MOVI R2, 5
            BLT R1, R2, middle
            MOVI R3, 30
            BRA done
        low:
            MOVI R3, 10
            BRA done
        middle:
            MOVI R3, 20
        done:
            ADDI R3, R3, 1
            EXIT
        ''', simt_region_depth=1)
        w, history = self.run_checked(gpu)
        self.assertFalse(gpu.error)
        self.assertEqual([p.regs[3] for p in w.processors], [11]*2+[21]*3+[31]*3)
        self.assertTrue(any(len(p) == 2 and p[0].pending_pc != p[1].pending_pc
                            for _, _, _, p in history))

    def test_fallthrough_join_parks_without_path(self):
        gpu = self.make('''
            GETTID R1
            MOVI R2, 4
            SSY join
            BGE R1, R2, work
        join:
            ADDI R3, R3, 1
            BAR
            EXIT
        work:
            MOVI R3, 9
            BRA join
        ''')
        w, history = self.run_checked(gpu)
        self.assertFalse(gpu.error)
        self.assertEqual([p.regs[3] for p in w.processors], [1]*4+[10]*4)
        self.assertTrue(all(not p for _, _, _, p in history))

    def test_direct_join_branch_succeeds_with_path_stack_full(self):
        gpu = self.make('''
            GETTID R1
            MOVI R2, 2
            SSY join
            BLT R1, R2, low
            MOVI R2, 5
            BLT R1, R2, join
            MOVI R3, 20
            BRA join
        low:
            MOVI R3, 10
        join:
            ADDI R3, R3, 1
            EXIT
        ''', simt_path_depth=1)
        w, _ = self.run_checked(gpu)
        self.assertFalse(gpu.error)
        self.assertEqual([p.regs[3] for p in w.processors], [11]*2+[1]*3+[21]*3)

    def test_identical_next_pcs_do_not_diverge_without_ssy(self):
        gpu = self.make('GETTID R1\nBEQ R1, R0, next\nnext: ADDI R3, R3, 1\nEXIT')
        w, _ = self.run_checked(gpu)
        self.assertFalse(gpu.error)
        self.assertEqual([p.regs[3] for p in w.processors], [1]*8)

    def test_sequential_regions_release_capacity_before_next_if(self):
        gpu = self.make('''
            GETTID R1
            MOVI R2, 4
            SSY first
            BLT R1, R2, first
            ADDI R3, R3, 10
        first:
            SSY second
            BGE R1, R2, second
            ADDI R3, R3, 20
        second:
            ADDI R3, R3, 1
            EXIT
        ''', simt_region_depth=1)
        w, _ = self.run_checked(gpu)
        self.assertFalse(gpu.error)
        self.assertEqual([p.regs[3] for p in w.processors], [21]*4+[11]*4)

    def test_reentry_does_not_search_past_innermost_region(self):
        gpu = self.make('''
        outer_site:
            SSY outer_join
            SSY inner_join
            BRA outer_site
        inner_join:
            NOP
        outer_join:
            EXIT
        ''', simt_region_depth=2)
        w, _ = self.run_checked(gpu)
        self.assertEqual((gpu.error_code, gpu.fault.pc), (ERROR_SIMT, 0))
        self.assertEqual([r.ssy_pc for r in w.region_stack], [0, 4])

    def test_exit_unwinds_inner_before_outer_pending_path(self):
        gpu = self.make('''
            GETTID R1
            MOVI R2, 4
            SSY outer
            BLT R1, R2, low
            SSY inner
            EXIT
        inner:
            MOVI R3, 99
            BRA outer
        low:
            MOVI R3, 10
        outer:
            ADDI R3, R3, 1
            EXIT
        ''')
        w, _ = self.run_checked(gpu)
        self.assertFalse(gpu.error)
        self.assertEqual([p.regs[3] for p in w.processors], [11]*4+[0]*4)

    def test_same_join_distinct_ssy_sites_open_distinct_regions(self):
        gpu = self.make('SSY done\nSSY done\nSSY done\ndone: ADDI R3, R3, 1\nEXIT')
        w, history = self.run_checked(gpu)
        self.assertFalse(gpu.error)
        self.assertEqual(max(len(r) for _, _, r, _ in history), 2)
        # The third opens then immediately closes all three before executing done.
        self.assertEqual([p.regs[3] for p in w.processors], [1]*8)
        gpu = self.make('SSY done\nSSY done\nSSY done\ndone: EXIT', simt_region_depth=2)
        self.run_checked(gpu)
        self.assertEqual((gpu.error_code, gpu.fault.pc), (ERROR_SIMT, 8))

    def test_exit_inside_region_preserves_parked_lanes(self):
        gpu = self.make('''
            GETTID R1
            MOVI R2, 4
            SSY join
            BLT R1, R2, join
            EXIT
        join:
            ADDI R3, R3, 1
            EXIT
        ''')
        w, _ = self.run_checked(gpu)
        self.assertFalse(gpu.error)
        self.assertEqual([p.regs[3] for p in w.processors], [1]*4+[0]*4)
        self.assertEqual((w.region_stack, w.path_stack), ([], []))

    def test_last_exit_clears_both_stacks_and_keeps_next_pc(self):
        gpu = self.make('SSY done\nEXIT\ndone: MOVI R3, 99')
        w, _ = self.run_checked(gpu)
        self.assertFalse(gpu.error)
        self.assertEqual(w.pc, 8)
        self.assertEqual((w.region_stack, w.path_stack), ([], []))
        self.assertEqual([p.regs[3] for p in w.processors], [0]*8)

    def test_changed_join_on_reused_ssy_faults_without_replacing_region(self):
        gpu = self.make('loop: SSY done\nBRA loop\ndone: EXIT\nother: EXIT')
        gpu.step()
        gpu.step()
        struct.pack_into('<I', gpu.memory, 0, (0x31 << 26) | 2)  # join now PC12
        before = self.snapshot(gpu)
        gpu.step()
        self.assertEqual(gpu.error_code, ERROR_SIMT)
        self.assertEqual(self.snapshot(gpu), before)

    def test_invalid_join_precedes_capacity_error(self):
        gpu = self.make('SSY done\nSSY 2048\ndone: EXIT', simt_region_depth=1)
        self.run_checked(gpu)
        self.assertEqual(gpu.error_code, ERROR_MEMORY_ACCESS)

    def test_reset_discards_both_stacks(self):
        gpu = self.pending_loop()
        w = gpu.streaming_multiprocessor.warps[0]
        while not w.path_stack:
            gpu.step()
        gpu.reset()
        self.assertEqual((w.region_stack, w.path_stack), ([], []))

    def test_depth_validation(self):
        for key in ('simt_region_depth', 'simt_path_depth'):
            for bad in (0, -1, True, 1.5):
                with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                    System(**{key: bad})

    def test_cli_stack_capacities(self):
        regions = '\n'.join(['SSY done'] * 9) + '\ndone: EXIT'
        paths = '''
            GETTID R1
            MOVI R2, 2
            SSY done
            BLT R1, R2, low
            MOVI R2, 4
            BLT R1, R2, middle
            BRA done
        low:
            NOP
            BRA done
        middle:
            NOP
        done:
            EXIT
        '''
        cases = [
            (regions, [], 1),  # default region depth is eight
            (regions, ['--simt-region-depth', '9'], 0),
            (paths, [], 0),
            (paths, ['--simt-path-depth', '1'], 1),
            (paths, ['--simt-path-depth', '2', '--simt-region-depth', '1'], 0),
            ('EXIT', ['--simt-region-depth', '0'], 2),
            ('EXIT', ['--simt-path-depth', '-1'], 2),
        ]
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / 'program.bin'
            for source, options, expected in cases:
                with self.subTest(options=options, expected=expected):
                    words = assemble(source)
                    binary.write_bytes(struct.pack('<'+'I'*len(words), *words))
                    result = subprocess.run(
                        [sys.executable, str(Path(__file__).with_name('minigpu_sim.py')),
                         str(binary), '--num-warps', '1', '--memory-size', '2048',
                         '--max', '100', *options],
                        capture_output=True, text=True, timeout=10, check=False)
                    self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                    if expected == 2:
                        self.assertIn('profundidades SIMT', result.stderr)


class MandelbrotRegionTest(unittest.TestCase):
    def check_image(self, name, base, group=None):
        folder = ROOT / 'x.cpu-tests/cases-gpu' / name
        source = (folder / 'mandelbrot.asm').read_text(encoding='utf-8')
        if group is not None:
            if name == 'mandelbrot':
                source = source.replace('ORI   R3, R3, 0x2C00', f'MOVI R3, {group+8}')
            else:
                source = source.replace('MOVI  R3, 19200', f'MOVI R3, {group+8}')
            source = source.replace('GETTID R11', f'GETTID R11\nADDI R11, R11, {group}')
        words = assemble(source)
        gpu = System(2*1024*1024, 8 if group is None else 1, 8, simt_region_depth=1)
        gpu.load_program(struct.pack('<'+'I'*len(words), *words))
        gpu.run(50_000_000)
        self.assertFalse(gpu.error, gpu.fault)
        expected = (folder / 'expected.bin').read_bytes()
        start, size = (0, len(expected)) if group is None else (group*4, 32)
        self.assertEqual(gpu.memory[base+start:base+start+size], expected[start:start+size])

    def test_original_and_packed_samples_with_one_region(self):
        for name, base, groups in (
                ('mandelbrot', 0x100000, (504, 16000, 32000)),
                ('mandelbrot-packed', 0x4000, (120, 4700, 9600, 19192))):
            for group in groups:
                with self.subTest(name=name, group=group):
                    self.check_image(name, base, group)

    @unittest.skipUnless(os.environ.get('RUN_SLOW_SIMT') == '1', 'full framebuffers: RUN_SLOW_SIMT=1')
    def test_full_original_and_packed_framebuffers(self):
        for name, base in (('mandelbrot', 0x100000), ('mandelbrot-packed', 0x4000)):
            with self.subTest(name=name):
                self.check_image(name, base)


if __name__ == '__main__':
    unittest.main()
