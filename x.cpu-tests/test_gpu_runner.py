"""Regresiones de integración del runner GPU sin hardware."""

import copy
import unittest
from unittest.mock import patch

from backends.gpu_simulator import GpuBackend
from run_gpu_tests import ROOT, REPOSITORY, load_case, compare_result, discover_cases


class GpuRunnerTest(unittest.TestCase):
    def setUp(self):
        self.path = ROOT / 'cases-gpu/memory/vecsum/test.json'
        self.case = load_case(self.path)
        self.backend = GpuBackend(REPOSITORY)

    def run_case(self, case):
        return self.backend.run(
            program=case['program'], initial_memory=case['initial_memory'],
            register_numbers=set(), memory_ranges=list(case['expected']['memory']),
            max_instructions=case['max_instructions'], timeout_seconds=1,
            warp_config=case['warp_config'],
        )

    def test_vecsum_and_mismatch_diagnostics(self):
        result = self.run_case(self.case)
        self.assertEqual(compare_result(self.case, result, 'gpu'), [])
        broken = copy.deepcopy(result)
        broken['observations']['warp[1].lane[7].R8'] = 0
        broken['observations']['warp[0].pc'] = 0
        broken['observations']['instructions_executed'] = 27
        broken['memory'][(0x180, 64)] = bytes(64)
        errors = compare_result(self.case, broken, 'gpu')
        self.assertEqual(len(errors), 4)
        self.assertTrue(any('warp[1].lane[7].R8' in error for error in errors))
        self.assertTrue(any('0x00000180' in error for error in errors))

    def test_partial_mask_preserves_inactive_outputs(self):
        case = copy.deepcopy(self.case)
        case['warp_config']['warps'][1]['active_mask'] = '0x0F'
        result = self.run_case(case)
        self.assertEqual(result['memory'][(0x180, 64)][48:], bytes(16))
        self.assertEqual(result['observations']['warp[1].lane[7].R8'], 0)
        self.assertTrue(compare_result(case, result, 'gpu'))

    def test_budget_failure_and_fresh_memory_per_case(self):
        case = copy.deepcopy(self.case)
        case['max_instructions'] = 27
        with self.assertRaises(self.backend.module.InstructionLimitExceeded):
            self.run_case(case)
        result = self.run_case(self.case)
        self.assertEqual(compare_result(self.case, result, 'gpu'), [])

    def test_backend_selection_and_discovery(self):
        from run_gpu_tests import validate_compatibility, case_architecture
        cpu = load_case(ROOT / 'cases/basics/smoke/test.json')
        self.assertEqual(cpu['architecture'], 'cpu')
        self.assertEqual(self.case['architecture'], 'gpu')
        validate_compatibility('gpu', ('gpu-simulator',))
        validate_compatibility('cpu', ('cpu-simulator', 'cpu-fpga'))
        with self.assertRaises(ValueError):
            validate_compatibility('cpu', ('gpu-simulator',))
        with self.assertRaises(ValueError):
            validate_compatibility('gpu', ('cpu-simulator', 'cpu-fpga'))
        for raw in ({}, {'architecture': 'other'}, {'architecture': 'gpu'},
                    {'architecture': 'cpu', 'warp_config': 'warps.json'}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                case_architecture(raw)
        self.assertIn(self.path, discover_cases([]))
        self.assertIn(ROOT / 'cases/basics/smoke/test.json', discover_cases([]))

    def test_mixed_explicit_selection_rejected_before_backend_construction(self):
        import run_gpu_tests as runner
        for backend, paths, constructor in (
            ('gpu-simulator', [self.path, ROOT / 'cases/basics/smoke/test.json'], 'GpuBackend'),
            ('cpu-fpga', [ROOT / 'cases/basics/smoke/test.json', self.path], 'FpgaBackend'),
        ):
            with self.subTest(backend=backend), patch(
                'sys.argv', ['run_gpu_tests.py', '--backend', backend, *map(str, paths)]
            ), patch.object(runner, constructor) as factory, patch('sys.stderr'):
                self.assertEqual(runner.main(), 2)
                factory.assert_not_called()

    def test_fault_diagnostics_detect_wrong_and_missing_fields(self):
        case = load_case(ROOT / 'cases-gpu/faults/division-by-zero/test.json')
        result = self.run_case(case)
        self.assertEqual(compare_result(case, result, 'gpu-simulator'), [])
        for field, value in (('pc', 0), ('warp_id', 1), ('core_id', 2), ('address', 128)):
            with self.subTest(field=field):
                broken = copy.deepcopy(result)
                broken['observations'][f'fault.{field}'] = value
                errors = compare_result(case, broken, 'gpu-simulator')
                self.assertEqual(len(errors), 1)
                self.assertIn(f'fault.{field}', errors[0])
        del result['observations']['fault.address']
        self.assertTrue(compare_result(case, result, 'gpu-simulator'))

    def test_fault_expected_format(self):
        from run_gpu_tests import gpu_expectations
        for fault in ({}, {'pc': 0, 'warp_id': 8, 'core_id': None, 'address': None},
                      {'pc': 0, 'warp_id': 0, 'core_id': 8, 'address': None},
                      {'pc': 0, 'warp_id': 0, 'core_id': True, 'address': None}):
            with self.subTest(fault=fault), self.assertRaises((ValueError, TypeError)):
                gpu_expectations({'fault': fault}, 8)

    def test_scheduler_skips_finished_warps(self):
        case = load_case(ROOT / 'cases-gpu/scheduling/independent-pcs/test.json')
        gpu = self.backend.module.System(warp_size=8)
        gpu.load_program(case['program'], launch=False)
        gpu.configure_warps(case['warp_config'])
        order = []
        while not gpu.halted:
            before = [w.instructions_executed for w in gpu.streaming_multiprocessor.warps]
            gpu.step()
            order.extend(i for i, warp in enumerate(gpu.streaming_multiprocessor.warps)
                         if warp.instructions_executed != before[i])
        self.assertEqual(order, [0, 3, 0, 3, 3])

    def test_fault_is_terminal_and_does_not_overwrite_diagnostic(self):
        case = load_case(ROOT / 'cases-gpu/faults/store-out-of-bounds/test.json')
        gpu = self.backend.module.System(warp_size=8)
        gpu.load_program(case['program'], launch=False)
        gpu.configure_warps(case['warp_config'])
        gpu.run(case['max_instructions'])
        first = gpu.fault
        pcs = [w.pc for w in gpu.streaming_multiprocessor.warps]
        count = gpu.instructions_executed
        self.assertFalse(gpu.step())
        for warp in gpu.streaming_multiprocessor.warps:
            self.assertFalse(warp.step())
        gpu.stop_with_error(self.backend.module.Fault(3, 0, 1, None))
        self.assertIs(gpu.fault, first)
        self.assertEqual([w.pc for w in gpu.streaming_multiprocessor.warps], pcs)
        self.assertEqual(gpu.instructions_executed, count)


if __name__ == '__main__':
    unittest.main()
