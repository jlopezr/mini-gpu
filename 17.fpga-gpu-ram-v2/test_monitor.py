import unittest
from monitor import (
    MonitorClient, MonitorError, CpuStatus, format_registers, validate_transfer,
    WARP_CONFIG_BASE, SIMT_DEBUG_BASE, SYSID_BASE,
)


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
            base = WARP_CONFIG_BASE + w * 16
            self.assertEqual(writes[base], 64 if w == 3 else 0)
            self.assertEqual(writes[base + 4], 0x55 if w == 3 else 0)
            self.assertEqual(writes[base + 8], 7 if w == 3 else 0)
        self.assertEqual(sum(call[0] == 'reset' for call in client.calls), 1)

    def test_launch_at_final_sdram_word(self):
        client = RecordingClient()
        client.configure_warps({'warps': [dict(id=0, pc=0x01fffffc)]})
        self.assertIn(('write', WARP_CONFIG_BASE, bytes.fromhex('fcffff01')), client.calls)

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
        # Por símbolo y no por número: si la base se mueve otra vez, este test
        # se mueve con ella en vez de fallar con un número que hay que buscar.
        self.assertEqual(client.calls, [('byte',SIMT_DEBUG_BASE,29)])
        with self.assertRaises(MonitorError): client.select_context(8,0)
        with self.assertRaises(MonitorError): client.select_context(0,-1)

    def test_transfer_boundaries(self):
        validate_transfer(0,33554432)
        validate_transfer(WARP_CONFIG_BASE,128)      # los ocho descriptores
        validate_transfer(SIMT_DEBUG_BASE,20)        # los cinco de §14.3
        validate_transfer(SYSID_BASE,28)             # las siete de SYSTEM
        for address,size in [
                (33554431,2),                 # cruza el final de la RAM
                (0x02000000,4),               # justo detrás de la RAM
                (WARP_CONFIG_BASE+0x7f,2),    # se sale del último descriptor
                (SIMT_DEBUG_BASE+20,4),       # pasado el último de §14.3
                (SYSID_BASE+28,4),            # pasada la séptima palabra
                (0x82000000,4),               # GPU CORE: bloque no implementado
                (0,0)]:
            with self.assertRaises(MonitorError): validate_transfer(address,size)

    def test_read_complete_lane_register_file(self):
        client = RecordingClient()
        registers = client.read_registers(3, 5)
        self.assertEqual(registers, [0x10000000 + register for register in range(32)])
        self.assertEqual(client.calls[0], ('byte', SIMT_DEBUG_BASE, 29))
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
