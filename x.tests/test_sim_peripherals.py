"""Los mismos programas MMIO deben funcionar en los tres motores.

Se prueban instrucciones reales, no solo objetos de dispositivo: ese hueco
permitía que la 25 tuviera SysIdDevice y rechazase LOAD a SYS_ID.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "1.isa"))
from miniisa_asm import assemble_bytes
from backends.simulator import SimulatorBackend
from backends.gpu_simulator import GpuBackend, capabilities
from backends.video_layout import FB_BACK
from tools.sim_devices import VideoDevice, SerialDevice


class PeripheralParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backends = [SimulatorBackend(ROOT), GpuBackend(ROOT), GpuBackend(ROOT, "cycle")]

    def run_program(self, backend, source, **kwargs):
        args = dict(program=assemble_bytes(source), initial_memory=[], register_numbers=set(),
                    memory_ranges=[(0x100, 16)], max_instructions=10000, timeout_seconds=10)
        if isinstance(backend, GpuBackend):
            args["warp_config"] = {"warp_size": 1, "warps": [{"id": 0, "pc": 0, "active_mask": 1}]}
        args.update(kwargs)
        return backend.run(**args)

    def test_sysid_desde_load_en_los_tres(self):
        source = "MOVHI R1, 0x8000\nLOAD R2, R1, 0xF00\nMOVI R3, 256\nSTORE R2, R3, 0\nHALT"
        for backend, folder in zip(self.backends, (2, 11, 25)):
            with self.subTest(folder=folder):
                result = self.run_program(backend, source)
                self.assertFalse(result["error"])
                self.assertEqual(int.from_bytes(result["memory"][(256, 16)][:4], "little"), 0x4D470000 | folder)

    def test_serie_peek_data_y_salida_mayor_que_fifo(self):
        source = """MOVHI R1, 0x8000
ADDI R1, R1, 512
LOAD R2, R1, 8
LOAD R3, R1, 0
MOVI R4, 256
STORE R2, R4, 0
STORE R3, R4, 4
LOAD R5, R1, 0
STORE R5, R4, 8
MOVI R6, 100
loop: STORE R2, R1, 0
ADDI R6, R6, -1
BNE R6, R0, loop
HALT"""
        for backend in self.backends:
            with self.subTest(backend=backend.version, architecture=backend.ARCHITECTURE):
                result = self.run_program(backend, source, stdin=b"AB")
                self.assertFalse(result["error"])
                self.assertEqual(result["stdout"], b"A" * 100)
                self.assertEqual(result["memory"][(256, 16)][:12], b"A\0\0\0A\0\0\0B\0\0\0")

    def test_swap_capture_y_halt_at(self):
        for backend in self.backends:
            with self.subTest(backend=backend.version, architecture=backend.ARCHITECTURE):
                result = self.run_program(backend, "MOVHI R1, 0x8000\nSTORE R0, R1, 8\nloop: BEQ R0, R0, loop",
                                          video={"run_until_swap": 1, "capture_frame": True},
                                          initial_memory=[(FB_BACK, b"\x34\x12\x78\x56")])
                self.assertTrue(result["halted"])
                self.assertFalse(result["error"])
                self.assertEqual(result["video"]["swaps"], 1)
                self.assertEqual(len(result["video"]["frame"]), 320 * 240 * 2)
                self.assertEqual(result["video"]["frame"][:4], b"\x34\x12\x78\x56")

    def test_status_serie_observa_los_bytes_pendientes(self):
        source = """MOVHI R1, 0x8000
MOVI R2, 65
STORE R2, R1, 512
STORE R2, R1, 512
STORE R2, R1, 512
LOAD R3, R1, 516
MOVI R4, 256
STORE R3, R4, 0
HALT"""
        for backend in self.backends:
            with self.subTest(backend=backend.version, architecture=backend.ARCHITECTURE):
                result = self.run_program(backend, source)
                self.assertFalse(result["error"])
                self.assertEqual(result["memory"][(256, 16)][:4], b"\0\x3d\0\0")
                self.assertEqual(result["stdout"], b"AAA")

    def test_clases_y_capacidades_compartidas(self):
        for backend in self.backends[1:]:
            self.assertIs(backend.module.VideoDevice, VideoDevice)
            self.assertIs(backend.module.SerialDevice, SerialDevice)
            self.assertTrue({"video", "frame_capture", "serial"} <= capabilities(backend.version))

    def test_un_lane_invalido_no_consume_uart_de_otro_lane(self):
        for backend in self.backends[1:]:
            with self.subTest(backend=backend.version):
                serial = SerialDevice(stdin=b"AB")
                gpu = backend.module.System(1024, 1, 2, serial=serial)
                gpu.load_program(assemble_bytes("LOAD R2, R1, 0\nHALT"))
                lanes = gpu.streaming_multiprocessor.warps[0].processors
                lanes[0].regs[1] = serial.BASE
                lanes[1].regs[1] = 0xFFFFFFFF
                gpu.run(10)
                self.assertTrue(gpu.error)
                self.assertEqual(serial.rx, b"AB")
                self.assertEqual(lanes[0].regs[2], 0)

    def test_lanes_activos_consumen_uart_una_vez_y_en_orden(self):
        for backend in self.backends[1:]:
            with self.subTest(backend=backend.version):
                serial = SerialDevice(stdin=b"ABC")
                gpu = backend.module.System(1024, 1, 2, serial=serial)
                gpu.load_program(assemble_bytes("LOAD R2, R1, 0\nHALT"))
                lanes = gpu.streaming_multiprocessor.warps[0].processors
                for lane in lanes:
                    lane.regs[1] = serial.BASE
                gpu.run(10)
                self.assertFalse(gpu.error)
                self.assertEqual([lane.regs[2] for lane in lanes], [65, 66])
                self.assertEqual(serial.rx, b"C")

    def test_cli_comun(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            program = folder / "echo.asm"
            program.write_text("MOVHI R1, 0x8000\nLOAD R2, R1, 512\nSTORE R2, R1, 512\nHALT")
            incoming, outgoing = folder / "input.bin", folder / "output.bin"
            incoming.write_bytes(b"Q")
            for script in ("2.cpu-sim-func/minicpu_sim.py", "11.gpu-sim-func/minigpu_sim.py",
                           "25.gpu-sim-cycle-uarch/minigpu_cycle.py"):
                with self.subTest(script=script):
                    args = [sys.executable, str(ROOT / script), str(program), "--serial-input", str(incoming),
                            "--serial-output", str(outgoing), "--video", "--frame-instructions", "10"]
                    if not script.startswith("2."):
                        args += ["--num-warps", "1", "--warp-size", "1"]
                    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(outgoing.read_bytes(), b"Q")


if __name__ == "__main__":
    unittest.main()
