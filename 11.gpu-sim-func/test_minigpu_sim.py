import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from minigpu_sim import (
    ERROR_DIVISION_BY_ZERO,
    ERROR_EXPLICIT_TRAP,
    ERROR_INVALID_ENCODING,
    ERROR_INVALID_OPCODE,
    ERROR_MEMORY_ACCESS,
    Fault,
    InstructionLimitExceeded,
    System,
    UnsupportedDivergence,
)

HALT = 0x3F << 26
TRAP = 0x3E << 26


def imm(op, rd=0, ra=0, value=0):
    return op << 26 | rd << 21 | ra << 16 | (value & 0xFFFF)


def reg(op, rd, ra, rb):
    return op << 26 | rd << 21 | ra << 16 | rb << 11


def program(*words):
    return struct.pack('<' + 'I' * len(words), *words)


class MiniGpuTest(unittest.TestCase):
    def test_config_launches_selected_warps_at_independent_pcs(self):
        gpu = System(128, 8, 4)
        gpu.load_program(program(imm(0x10, 1, value=7), HALT,
                                 imm(0x10, 1, value=9), HALT), launch=False)
        self.assertTrue(gpu.halted)
        gpu.configure_warps({'warp_size': 4, 'warps': [
            {'id': 0, 'pc': '0x0', 'active_mask': '0x5'},
            {'id': 7, 'pc': 8, 'active_mask': 2},
            {'id': 1, 'enabled': False},
        ]})
        gpu.run(4)
        warps = gpu.streaming_multiprocessor.warps
        self.assertEqual([c.regs[1] for c in warps[0].processors], [7, 0, 7, 0])
        self.assertEqual([c.regs[1] for c in warps[7].processors], [0, 9, 0, 0])
        self.assertEqual([w.instructions_executed for w in warps], [2, 0, 0, 0, 0, 0, 0, 2])

    def test_config_rejects_invalid_input_without_changing_state(self):
        gpu = self.make(HALT, lanes=8)
        invalid = [{'warps': [], 'typo': 1},
                   {'warp_size': 4, 'warps': []}, {'warp_size': True, 'warps': []}]
        for entry in ({}, {'id': True}, {'id': -1}, {'id': 8}, {'id': 0.0},
                      {'id': 0, 'enabled': 'false'}, {'id': 0, 'pc': 2},
                      {'id': 0, 'pc': 128}, {'id': 0, 'pc': -4},
                      {'id': 0, 'active_mask': 256}, {'id': 0, 'active_mask': 0},
                      {'id': 0, 'active_mask': -1}, {'id': 0, 'pc': 'oops'},
                      {'id': 0, 'active_mask': True}, {'id': 0, 'mask': 1}):
            invalid.append({'warps': [entry]})
        invalid.append({'warps': [{'id': 0}, {'id': 0}]})
        before = bytes(gpu.memory)
        warp = gpu.streaming_multiprocessor.warps[0]
        for config in invalid:
            with self.subTest(config=config), self.assertRaises(ValueError):
                gpu.configure_warps(config)
            self.assertEqual((warp.pc, warp.active_mask), (0, 255))
            self.assertEqual(bytes(gpu.memory), before)

    def test_config_rejects_wrong_container_types_without_changing_state(self):
        gpu = self.make(HALT, lanes=8)
        warp = gpu.streaming_multiprocessor.warps[0]
        before = bytes(gpu.memory)
        for config in (None, [], {}, {'warps': {}}, {'warps': None},
                       {'warps': [None]}, {'warps': [[]]}):
            with self.subTest(config=config), self.assertRaises(TypeError):
                gpu.configure_warps(config)
            self.assertEqual((warp.pc, warp.active_mask), (0, 255))
            self.assertEqual(bytes(gpu.memory), before)

    def test_config_defaults_empty_and_relaunch(self):
        gpu = self.make(TRAP, lanes=8)
        gpu.run()
        self.assertTrue(gpu.error)
        gpu.configure_warps({'warps': []})
        self.assertTrue(gpu.halted)
        self.assertFalse(gpu.error)
        gpu.run(0)
        gpu.configure_warps({'warps': [{'id': 0}]})
        self.assertFalse(gpu.halted)
        self.assertEqual(gpu.streaming_multiprocessor.warps[0].active_mask, 255)
        self.assertEqual(gpu.instructions_executed, 0)
        self.assertEqual(gpu.memory[:4], program(TRAP))

    def test_config_cli(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / 'memory.bin'
            config = Path(folder) / 'launch.json'
            binary.write_bytes(program(TRAP, HALT))
            command = [sys.executable, str(Path(__file__).with_name('minigpu_sim.py')),
                       str(binary), '--config', str(config), '--memory-size', '64', '--max', '1']
            config.write_text(json.dumps({'warp_size': 4, 'warps': [
                {'id': 7, 'pc': '0x4', 'active_mask': '0x3'}]}), encoding='utf-8')
            result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('HALT tras 1', result.stdout)
            result = subprocess.run(command + ['--warp-size', '8'], capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 2)
            for content in ('{', 'null', '{"warps": [{"id": 8}]}',
                            '{"warps": {}}', '{"warps": [null]}'):
                config.write_text(content, encoding='utf-8')
                result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertNotIn('Traceback', result.stderr)

    def make(self, *words, warps=1, lanes=2, address=0):
        gpu = System(128, warps, lanes)
        gpu.load_program(program(*words), address)
        return gpu

    def test_halt_counted_once_per_warp_and_terminal(self):
        gpu = self.make(imm(0x10, 1, value=7), HALT, warps=3, lanes=4)
        gpu.run(6)
        self.assertTrue(gpu.halted)
        self.assertFalse(gpu.error)
        self.assertEqual(gpu.instructions_executed, 6)
        for warp in gpu.streaming_multiprocessor.warps:
            self.assertEqual((warp.pc, warp.instructions_executed, warp.active_mask), (8, 2, 0))
            self.assertTrue(all(c.regs[1] == 7 for c in warp.processors))
            self.assertFalse(warp.step())
        self.assertFalse(gpu.step())

    def test_exact_limit_across_warps_and_resume(self):
        gpu = self.make(0, HALT, warps=3)
        with self.assertRaises(InstructionLimitExceeded):
            gpu.run(4)
        self.assertEqual(gpu.instructions_executed, 4)
        self.assertFalse(gpu.error)
        gpu.run(6)
        self.assertTrue(gpu.halted)

    def test_loop_and_zero_budget(self):
        gpu = self.make((0x2F << 26) | 0x3FFFFFF)
        for limit in (0, 5):
            with self.assertRaises(InstructionLimitExceeded):
                gpu.run(limit)
            self.assertEqual(gpu.instructions_executed, limit)
        self.assertEqual(gpu.streaming_multiprocessor.warps[0].pc, 0)

    def test_errors_stop_before_other_warps_and_preserve_first_fault(self):
        for word, code in ((TRAP, ERROR_EXPLICIT_TRAP),
                           (0x3D << 26, ERROR_INVALID_OPCODE),
                           (HALT | 1, ERROR_INVALID_ENCODING),
                           (reg(0x0C, 3, 1, 2), ERROR_DIVISION_BY_ZERO)):
            with self.subTest(code=code):
                gpu = self.make(word, HALT, warps=2, address=16)
                gpu.run(10)
                self.assertTrue(gpu.halted)
                self.assertEqual((gpu.error_code, gpu.error_pc), (code, 16))
                self.assertEqual(gpu.fault.warp_id, 0)
                self.assertEqual(gpu.instructions_executed, 0)
                first = gpu.fault
                gpu.stop_with_error(Fault(99, 99, 1, 1))
                self.assertIs(gpu.fault, first)
                self.assertFalse(gpu.streaming_multiprocessor.warps[1].step())
                self.assertEqual(gpu.streaming_multiprocessor.warps[1].pc, 16)

    def test_late_lane_division_fault_is_atomic(self):
        gpu = self.make(reg(0x0C, 3, 1, 2), HALT)
        lanes = gpu.streaming_multiprocessor.warps[0].processors
        for lane in lanes:
            lane.regs[1], lane.regs[3] = 12, 99
        lanes[0].regs[2] = 3
        gpu.run()
        self.assertEqual(gpu.fault.core_id, 1)
        self.assertEqual([c.regs[3] for c in lanes], [99, 99])

    def test_memory_faults_are_atomic_and_record_address(self):
        for op in (0x15, 0x16):
            for bad_address in (65, 128, 0xFFFFFFFC):
                with self.subTest(op=op, address=bad_address):
                    gpu = self.make(imm(op, 2, 1), HALT)
                    lanes = gpu.streaming_multiprocessor.warps[0].processors
                    lanes[0].regs[1], lanes[1].regs[1] = 64, bad_address
                    for lane in lanes:
                        lane.regs[2] = 42
                    before = bytes(gpu.memory)
                    gpu.run()
                    self.assertEqual(gpu.error_code, ERROR_MEMORY_ACCESS)
                    self.assertEqual(gpu.fault.address, bad_address)
                    self.assertEqual(gpu.fault.core_id, 1)
                    self.assertEqual(bytes(gpu.memory), before)
                    self.assertEqual([c.regs[2] for c in lanes], [42, 42])

    def test_fetch_fault_has_no_lane(self):
        for pc in (2, 128):
            gpu = self.make(HALT)
            gpu.streaming_multiprocessor.warps[0].pc = pc
            gpu.run()
            self.assertEqual(gpu.fault, Fault(ERROR_MEMORY_ACCESS, pc, 0, None, pc))

    def test_reset_preserves_memory_identity_and_reload(self):
        gpu = self.make(TRAP)
        memory = gpu.memory
        lane = gpu.streaming_multiprocessor.warps[0].processors[0]
        lane.regs[1] = 123
        gpu.run()
        gpu.reset()
        self.assertIs(gpu.memory, memory)
        self.assertIs(lane.memory, memory)
        self.assertEqual(bytes(memory), bytes(128))
        self.assertEqual(lane.regs, [0] * 32)
        self.assertFalse(gpu.error)
        self.assertTrue(gpu.halted)
        gpu.load_program(program(HALT), 32)
        gpu.run(1)
        self.assertEqual(gpu.streaming_multiprocessor.warps[0].pc, 36)

    def test_gettid_unique_and_store_load(self):
        gpu = self.make(imm(0x30, 1), reg(0x07, 2, 1, 3),
                        imm(0x11, 2, 2, 64), imm(0x16, 1, 2),
                        imm(0x15, 4, 2), HALT, warps=2, lanes=3)
        for warp in gpu.streaming_multiprocessor.warps:
            for lane in warp.processors:
                lane.regs[3] = 2
        gpu.run(12)
        self.assertEqual(struct.unpack_from('<6I', gpu.memory, 64), tuple(range(6)))
        self.assertEqual([c.regs[4] for w in gpu.streaming_multiprocessor.warps
                          for c in w.processors], list(range(6)))

    def test_uniform_branch_and_divergence(self):
        gpu = self.make(imm(0x20, 1, 2, 1), TRAP, HALT)
        gpu.run(2)
        self.assertFalse(gpu.error)
        gpu = self.make(imm(0x20, 1, 2, 1), TRAP, HALT)
        warp = gpu.streaming_multiprocessor.warps[0]
        warp.processors[1].regs[1] = 1
        with self.assertRaises(UnsupportedDivergence):
            gpu.step()
        self.assertEqual((warp.pc, gpu.instructions_executed), (0, 0))
        self.assertFalse(gpu.error)

    def test_inactive_lane_does_not_fault(self):
        gpu = self.make(reg(0x0C, 3, 1, 2), HALT)
        warp = gpu.streaming_multiprocessor.warps[0]
        warp.active_mask = 1
        warp.processors[0].regs[2] = 1
        gpu.run(2)
        self.assertFalse(gpu.error)
        self.assertTrue(gpu.halted)

    def test_alu_regression(self):
        cases = [(0x01, 0x80000022), (0x02, 0x7FFFFFE0),
                 (0x04, 1), (0x05, 0x80000021), (0x06, 0x80000020),
                 (0x07, 2), (0x08, 0x40000000), (0x09, 0xC0000000),
                 (0x0A, 0x80000021), (0x0C, 0xFC1F07C2)]
        for op, expected in cases:
            with self.subTest(op=op):
                gpu = self.make(reg(op, 3, 1, 2), HALT)
                lanes = gpu.streaming_multiprocessor.warps[0].processors
                for lane in lanes:
                    lane.regs[1], lane.regs[2] = 0x80000001, 33
                gpu.run(2)
                self.assertEqual([c.regs[3] for c in lanes], [expected] * 2)

    def test_invalid_configuration_and_load(self):
        for args in ((0, 1, 1), (64, 0, 1), (64, 1, 0)):
            with self.assertRaises(ValueError):
                System(*args)
        gpu = System(64, 1, 1)
        for data, address in ((b'', 0), (b'x', 0), (program(HALT), 2),
                              (program(HALT), -4), (program(HALT), 64)):
            with self.assertRaises(ValueError):
                gpu.load_program(data, address)

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / 'program.bin'
            for word, limit, code, message in ((HALT, 1, 0, 'HALT'),
                                               (TRAP, 1, 1, 'ERROR'),
                                               (0, 0, 2, 'Simulador:')):
                binary.write_bytes(program(word))
                result = subprocess.run(
                    [sys.executable, str(Path(__file__).with_name('minigpu_sim.py')),
                     str(binary), '--num-warps', '1', '--warp-size', '2',
                     '--memory-size', '64', '--max', str(limit)],
                    capture_output=True, text=True, timeout=10, check=False,
                )
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertIn(message, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
