"""Hardware backend contract and suite selection, without a connected board."""
import io
import struct
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import run_gpu_tests as runner
from backends import gpu_fpga
from backends.gpu_simulator import GpuBackend


class SnapshotClient:
    def __init__(self, fault=0):
        self.fault = fault
        self.selected = (0, 0)
        self.reads = []

    def select_context(self, warp, lane):
        self.selected = warp, lane

    def read_register(self, register):
        self.reads.append((*self.selected, register))
        return self.selected[0] * 10000 + self.selected[1] * 100 + register

    def read_memory(self, address, size):
        if 0x80000000 <= address < 0x80000080:
            warp = (address - 0x80000000) // 16
            return struct.pack('<4I', warp * 4, 0xff00 | warp, 0, 0)
        value = {0x80000108: 123, 0x8000010c: self.fault,
                 0x80000110: 44, 0x80000114: self.selected[0] + 10}[address]
        return value.to_bytes(4, 'little')


class GpuFpgaTest(unittest.TestCase):
    def test_read_actual_warp_state_and_only_requested_registers(self):
        client = SnapshotClient()
        fields = {'warp[3].lane[5].R7', 'warp[0].lane[2].R1', 'warp[3].lane[5].R9'}
        got = gpu_fpga.read_observations(client, SimpleNamespace(error=False), fields)
        self.assertEqual(got['instructions_executed'], 123)
        self.assertFalse(got['fault.present'])
        self.assertEqual(got['warp[3].pc'], 12)
        self.assertEqual(got['warp[3].active_mask'], 3)
        self.assertEqual(got['warp[3].instructions_executed'], 13)
        self.assertEqual(got['warp[3].lane[5].R7'], 30507)
        self.assertEqual(client.reads, [(0, 2, 1), (3, 5, 7), (3, 5, 9)])

    def test_fault_lane_valid_and_unavailable_memory_address(self):
        for code, valid in [(4, True), (6, False), (2, True)]:
            with self.subTest(code=code):
                client = SnapshotClient((0x40 if valid else 0) | (3 << 3) | 5)
                got = gpu_fpga.read_observations(client, SimpleNamespace(error=True, error_code=code), set())
                self.assertEqual(got['fault.pc'], 44)
                self.assertEqual(got['fault.warp_id'], 3)
                self.assertEqual(got['fault.core_id'], 5 if valid else None)
                if code == 2:
                    self.assertNotIn('fault.address', got)
                else:
                    self.assertIsNone(got['fault.address'])

    def test_default_suite_filters_capabilities_and_bram(self):
        skipped = {}
        accepted = []
        for path in (runner.ROOT / 'cases-gpu').rglob('test.json'):
            case = runner.load_case(path)
            reason = gpu_fpga.incompatibility(case)
            if reason:
                skipped[case['name']] = reason
            else:
                accepted.append(case['name'])
        self.assertEqual(len(accepted), 26)
        self.assertEqual(len(skipped), 8)
        self.assertIn('fuera del mapa de memoria', skipped['gpu-mandelbrot'])
        self.assertIn('fuera del mapa de memoria', skipped['gpu-load-out-of-bounds'])
        self.assertIn('atómicos', skipped['gpu-division-by-zero'])
        self.assertIn('gpu-mandelbrot-packed', accepted)
        self.assertIn('ssy-all-paths', accepted)

    def test_explicit_incompatible_case_rejected_before_hardware(self):
        path = runner.ROOT / 'cases-gpu/programs/mandelbrot/test.json'
        with patch('sys.argv', ['runner', '--backend', 'gpu-fpga', str(path)]), patch.object(runner, 'GpuFpgaBackend') as factory, patch('sys.stderr'):
            self.assertEqual(runner.main(), 2)
            factory.assert_not_called()

    def test_gpu_both_compares_gpu_keys_and_detects_mismatch(self):
        path = runner.ROOT / 'cases-gpu/scheduling/independent-pcs/test.json'
        model = GpuBackend(runner.REPOSITORY)
        def execute(**kwargs):
            fields = kwargs.pop('observation_fields')
            self.assertIn('warp[3].lane[7].R1', fields)
            return model.run(**kwargs)
        for broken in (False, True):
            def execute_variant(**kwargs):
                result = execute(**kwargs)
                if broken:
                    result['observations']['warp[3].lane[7].R1'] = 0
                return result
            with self.subTest(broken=broken), patch('sys.argv', ['runner', '--backend', 'gpu-both', str(path)]), patch.object(runner, 'GpuFpgaBackend') as factory, redirect_stdout(io.StringIO()) as output:
                factory.return_value.run.side_effect = execute_variant
                self.assertEqual(runner.main(), 1 if broken else 0)
                self.assertNotIn('ERROR', output.getvalue())
                self.assertEqual('diferencial GPU' in output.getvalue(), broken)

    def test_monitor_revision_requires_update_from_20(self):
        from backends import board
        from test_board import fake_monitor
        monitor = fake_monitor([(2, 0), (2, 1)])
        with patch.object(board, 'upload') as upload:
            board.ensure_bitstream(monitor, 'COM3', 1, gpu_fpga.VERSIONS['bram']['monitor_version'], runner.REPOSITORY / '12.fpga-gpu', 'gpu-fpga', 'bram', board.UploadPolicy(assume_yes=True))
        upload.assert_called_once()


if __name__ == '__main__':
    unittest.main()
