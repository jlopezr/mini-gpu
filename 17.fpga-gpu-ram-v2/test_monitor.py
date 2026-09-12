import unittest
from monitor import MonitorClient, MonitorError, CpuStatus, format_registers, validate_transfer


class RecordingClient(MonitorClient):
    def __init__(self, halted=True):
        self.calls = []
        self.stopped = halted

    def get_status(self):
        self.calls.append(('status',))
        return CpuStatus(self.stopped, False, 0, 0)

    def reset_cpu(self):
        self.calls.append(('reset',))

    def write_memory(self, address, data):
        self.calls.append(('write', address, bytes(data)))

    def write_byte(self, address, value):
        self.calls.append(('byte', address, value))

    def read_register(self, register):
        self.calls.append(('register', register))
        return 0x10000000 + register


class LaunchTest(unittest.TestCase):
    def test_configure_disables_omitted_warps_and_preserves_ram(self):
        client = RecordingClient()
        client.configure_warps({'warps': [dict(id=3, pc='0x40', active_mask='0x55', workgroup_id=7)]})
        writes = {entry[1]: int.from_bytes(entry[2], 'little') for entry in client.calls if entry[0] == 'write'}
        self.assertEqual(len(writes), 24)
        for w in range(8):
            base = 0x80000000 + w * 16
            self.assertEqual(writes[base], 64 if w == 3 else 0)
            self.assertEqual(writes[base + 4], 0x55 if w == 3 else 0)
            self.assertEqual(writes[base + 8], 7 if w == 3 else 0)
        self.assertEqual(sum(call[0] == 'reset' for call in client.calls), 1)

    def test_launch_at_final_sdram_word(self):
        client = RecordingClient()
        client.configure_warps({'warps': [dict(id=0, pc=0x01fffffc)]})
        self.assertIn(('write', 0x80000000, bytes.fromhex('fcffff01')), client.calls)

    def test_invalid_launch_never_touches_hardware(self):
        for config in [
            {'warps':[dict(id=8)]}, {'warps':[dict(id=0,pc=1)]},
            {'warps':[dict(id=0,pc=33554432)]}, {'warp_size':4,'warps':[]},
            {'warps':[dict(id=0,active_mask=256)]},
            {'warps':[dict(id=0,workgroup_id=1<<32)]},
            {'warps':[dict(id=0),dict(id=0)]},
        ]:
            with self.subTest(config=config):
                client = RecordingClient()
                with self.assertRaises(MonitorError): client.configure_warps(config)
                self.assertEqual(client.calls, [])

    def test_running_gpu_is_not_reset_by_configuration(self):
        client = RecordingClient(halted=False)
        with self.assertRaises(MonitorError): client.configure_warps({'warps':[]})
        self.assertEqual(client.calls, [('status',)])

    def test_select_context_encoding_and_bounds(self):
        client = RecordingClient()
        client.select_context(3,5)
        self.assertEqual(client.calls, [('byte',0x80000100,29)])
        with self.assertRaises(MonitorError): client.select_context(8,0)
        with self.assertRaises(MonitorError): client.select_context(0,-1)

    def test_transfer_boundaries(self):
        validate_transfer(0,33554432)
        validate_transfer(0x80000000,128)
        validate_transfer(0x80000100,20)
        for address,size in [(33554431,2),(0x02000000,4),(0x8000007f,2),(0,0)]:
            with self.assertRaises(MonitorError): validate_transfer(address,size)

    def test_read_complete_lane_register_file(self):
        client = RecordingClient()
        registers = client.read_registers(3, 5)
        self.assertEqual(registers, [0x10000000 + register for register in range(32)])
        self.assertEqual(client.calls[0], ('byte', 0x80000100, 29))
        self.assertEqual(client.calls[1:], [('register', register) for register in range(32)])

    def test_register_display_is_compact_and_complete(self):
        rendered = format_registers(3, 5, list(range(32)))
        self.assertEqual(len(rendered.splitlines()), 5)
        self.assertTrue(rendered.startswith('warp=3 lane=5\n'))
        self.assertIn('R00=0x00000000', rendered)
        self.assertIn('R31=0x0000001f', rendered)
        with self.assertRaises(ValueError):
            format_registers(0, 0, [0] * 31)


if __name__ == '__main__':
    unittest.main()
