"""Regresión diferencial opcional: RUN_CODON=1 tools/test --prototype 32."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import cpu_gpu_sim as sim
from tools import sim_peripherals
from tools.codon_backend import prepare, snapshot
from test_cpu_gpu_sim import asm, CASES, build_c_example


@unittest.skipUnless(os.environ.get('RUN_CODON') == '1', 'opcional: RUN_CODON=1 y compilador Codon')
class CodonBackendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.binary, cls.env = prepare()

    def compare(self, program, *options):
        args=sim.parse_arguments([str(program),*options])
        s=sim.CpuGpuSystem(args.memory_size,args.num_warps,args.warp_size,
                          cpu_steps=args.cpu_steps,gpu_steps=args.gpu_steps,
                          **sim_peripherals.from_arguments(args))
        s.load_cpu_program(sim.load_program_file(program))
        code=0
        try:
            if s.run(args.run_limit,max_cpu_instructions=args.cpu_run_limit,
                     max_gpu_instructions=args.gpu_run_limit)=='stalled':code=2
        except (sim.InstructionLimitExceeded,sim.gpu_sim.SimulationError):code=2
        if code==0 and (s.cpu.error or s.gpu.fault):code=1
        expected=snapshot(s)
        with tempfile.TemporaryDirectory() as folder:
            state=Path(folder)/'state.json'
            env=dict(self.env,MINIGPU_CODON_STATE=str(state))
            proc=subprocess.run([str(self.binary),str(program),'--backend','codon',*options],
                                env=env,text=True,capture_output=True)
            self.assertEqual(proc.returncode,code,proc.stdout+'\n'+proc.stderr)
            self.assertTrue(state.exists(),proc.stdout+'\n'+proc.stderr)
            actual=json.loads(state.read_text())
            self.assertEqual(actual,expected)

    def source(self, source, *options):
        with tempfile.TemporaryDirectory() as folder:
            program=Path(folder)/'program.bin';program.write_bytes(asm(source))
            self.compare(program,'--memory-size','0x100000','--run-limit','10000',*options)

    def test_cpu_fp32(self):
        self.compare(CASES.parents[0] / 'cases-cpu/alu/fp32/program.asm')
        self.compare(CASES.parents[0] / 'cases-cpu/alu/fp32-cmp-cvt/program.asm')
        self.compare(CASES.parents[0] / 'cases-cpu/alu/ext-minmax-clz/program.asm')

    def test_launch_and_ratios(self):
        for cpu,gpu in ((1,1),(5,1),(1,5),(3,7)):
            with self.subTest(cpu=cpu,gpu=gpu):
                self.compare(CASES/'launch/launch.asm','--cpu-steps',str(cpu),'--gpu-steps',str(gpu))

    def test_runtime_recovery_and_gpu_renderer(self):
        self.compare(CASES/'dma/harness/dma.asm')
        self.compare(CASES/'render/render-v2/render_v2.asm',
                     '--halt-after-swaps','2','--frame-instructions','1000')

    def test_compiled_c_divergence(self):
        image, _ = build_c_example('simt/diverge')
        with tempfile.TemporaryDirectory() as folder:
            program=Path(folder)/'diverge.bin'
            program.write_bytes(image)
            self.compare(program)

    def test_cpu_errors_and_limits(self):
        for source in ('HALT','MOVI R1, 7\nDIV R2, R1, R0','TRAP','LOAD R1, R0, 1',
                       'loop: BRA loop'):
            with self.subTest(source=source):
                self.source(source,'--run-limit','50')

    def mixed(self,kernel):
        return f'''
            LI R10, MMIO_GPU_WARPS_BASE
            LI R1, kernel
            STORE R1, R10, MMIO_GPU_WARPS_PC_OFF
            MOVI R1, 255
            STORE R1, R10, MMIO_GPU_WARPS_ACTIVE_OFF
            LI R10, MMIO_GPU_BASE
            MOVI R1, 1
            STORE R1, R10, MMIO_GPU_WARP_START_OFF
        wait: LOAD R2, R10, MMIO_GPU_WARP_LIVE_OFF
            BNE R2, R0, wait
            HALT
        kernel: {kernel}
        '''

    def test_gpu_fault_and_limits(self):
        for kernel in ('TRAP','LOAD R1, R0, 1','MOVI R1, 7\nDIV R2, R1, R0',
                       'spin: BRA spin'):
            with self.subTest(kernel=kernel):
                self.source(self.mixed(kernel),'--run-limit','100','--gpu-run-limit','20')

    def test_gpu_geometry_and_subwords(self):
        source=self.mixed('''GETLANE R1
            LI R2, 0x20000
            ADD R2, R2, R1
            STOREB R1, R2, 0
            LOADUB R3, R2, 0
            HALT''').replace('MOVI R1, 255','MOVI R1, 15')
        self.source(source,'--num-warps','2','--warp-size','4')

    def test_invalid_configuration(self):
        for options in (('--cpu-steps','0'),('--run-limit','-1'),('--warp-size','0')):
            with self.subTest(options=options):
                proc=subprocess.run([str(self.binary),str(CASES/'launch/launch.asm'),*options],
                                    env=self.env,text=True,capture_output=True)
                self.assertEqual(proc.returncode,2,proc.stdout+'\n'+proc.stderr)
                self.assertIn('Simulador:',proc.stderr)

    def test_simt_paths_and_barrier(self):
        self.source(self.mixed('''
            GETLANE R1
            MOVI R2, 4
            SSY join
            BLT R1, R2, taken
            MOVI R3, 77
            BRA join
        taken: MOVI R3, 33
        join: BAR
            LI R4, 0x20000
            MOVI R6, 2
            SHL R5, R1, R6
            ADD R4, R4, R5
            STORE R3, R4, 0
            HALT
        '''))

    def test_video_and_serial(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'serial.bin'
            self.source('''
                LI R10, MMIO_SERIAL_BASE
                MOVI R1, 65
                STORE R1, R10, MMIO_SERIAL_DATA_OFF
                MOVI R1, 80
            loop: ADDI R1, R1, -1
                BNE R1, R0, loop
                HALT
            ''','--video','--frame-instructions','7','--serial-output',str(output))

    def test_input_script_and_video_clocks(self):
        with tempfile.TemporaryDirectory() as folder:
            script=Path(folder)/'input.txt'
            script.write_text('@0 keyboard connect\n@5 key down R\n@30 key up R\n')
            self.source('''MOVI R1, 100
                loop: ADDI R1, R1, -1
                BNE R1, R0, loop
                HALT''','--input-script',str(script),'--video','--frame-instructions','13')


@unittest.skipUnless(os.environ.get('RUN_CODON') == '1', 'opcional: RUN_CODON=1 y compilador Codon')
class CodonLimitationsTest(unittest.TestCase):
    """Avisa si un Codon nuevo resuelve alguna limitación de tools/codon/LIMITACIONES.md:
    su rodeo en los núcleos ya se podría deshacer."""

    def test_limitations_still_hold(self):
        script = Path(__file__).resolve().parents[1] / 'tools/codon/limitations/check.py'
        proc = subprocess.run([sys.executable, str(script)], text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
