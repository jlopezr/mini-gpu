import io
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from minigpu_sim import System, ERROR_SIMT
from gpu_trace import TextTrace


class TraceTest(unittest.TestCase):
    def gpu(self, words, *, detail=False, limit=None):
        gpu = System(128, 2, 2)
        gpu.load_program(struct.pack('<' + 'I' * len(words), *words))
        stream = io.StringIO()
        gpu.trace = TextTrace(stream, detail=detail, limit=limit)
        return gpu, stream

    def test_round_robin_and_limit_preserve_execution(self):
        for limit in (None, 0, 2):
            gpu, stream = self.gpu([0, 0xFC000000], limit=limit)
            gpu.run(4)
            self.assertEqual(gpu.instructions_executed, 4)
            rows = [line for line in stream.getvalue().splitlines() if line[:1].isdigit()]
            self.assertEqual(len(rows), 4 if limit is None else limit)
            if limit is None:
                self.assertEqual([row.split()[1] for row in rows], ['W0', 'W1', 'W0', 'W1'])
                self.assertIn('FINISHED', rows[-1])
            else:
                self.assertIn('ejecucion continua', stream.getvalue())

    def test_register_and_memory_details(self):
        words = [(0x10 << 26) | (1 << 21) | 64,
                 (0x10 << 26) | (2 << 21) | 7,
                 (0x16 << 26) | (2 << 21) | (1 << 16),
                 (0x15 << 26) | (3 << 21) | (1 << 16), 0xFC000000]
        gpu, stream = self.gpu(words, detail=True)
        gpu.run(10)
        log = stream.getvalue()
        self.assertIn('T0 R2: 0x00000000 -> 0x00000007', log)
        self.assertIn('T1 WRITE [0x00000040] = 0x00000007', log)
        self.assertIn('T0 READ [0x00000040] = 0x00000007', log)

    def test_fault_does_not_log_uncommitted_changes(self):
        gpu, stream = self.gpu([(0x0C << 26) | (3 << 21) | (1 << 16) | (2 << 11)], detail=True)
        lanes = gpu.streaming_multiprocessor.warps[0].processors
        lanes[0].regs[1], lanes[0].regs[2] = 12, 3
        gpu.run()
        self.assertIn('ERROR 0x04 hilo=1', stream.getvalue())
        self.assertNotIn('T0 R3:', stream.getvalue())
        self.assertEqual(lanes[0].regs[3], 0)

    def test_fetch_and_divergence(self):
        gpu, stream = self.gpu([0])
        gpu.streaming_multiprocessor.warps[0].pc = 128
        gpu.run()
        self.assertIn('<FETCH>', stream.getvalue())
        self.assertIn('direccion=0x00000080', stream.getvalue())
        gpu, stream = self.gpu([(0x20 << 26) | (1 << 21) | 1])
        gpu.streaming_multiprocessor.warps[0].processors[1].regs[1] = 1
        gpu.step()
        self.assertIn('ERROR 0x06', stream.getvalue())

    def test_cli_file_and_final_summary_after_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            binary, log = Path(folder) / 'program.bin', Path(folder) / 'trace.log'
            binary.write_bytes(struct.pack('<2I', 0, 0xFC000000))
            command = [sys.executable, str(Path(__file__).with_name('minigpu_sim.py')),
                       str(binary), '--num-warps', '1', '--trace-file', str(log), '--trace-limit', '1']
            result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('FIN: HALT; 2 instrucciones', log.read_text(encoding='utf-8'))
            result = subprocess.run(command + ['--trace-file', str(binary)],
                                    capture_output=True, text=True, check=False, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(binary.read_bytes(), struct.pack('<2I', 0, 0xFC000000))


if __name__ == '__main__':
    unittest.main()
