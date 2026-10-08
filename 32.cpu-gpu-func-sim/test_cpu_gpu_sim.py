import contextlib
import io
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import cpu_gpu_sim as sim
from cpu_gpu_sim import AccessFault, CpuGpuSystem, InstructionLimitExceeded, mm

sys.path.insert(0, str(sim.ROOT / "1.isa"))
from mini_asm import assemble_bytes  # noqa: E402

HERE = Path(__file__).resolve().parent
INC = sim.ROOT / "x.tests" / "inc"
MEMORY = 1 << 20            # 1 MiB
KERNEL = 0x10000
OUT = 0x20000
ERROR_MEMORY_ACCESS = 0x02
ERROR_EXPLICIT_TRAP = 0x03


def asm(source: str) -> bytes:
    return assemble_bytes('.include "mmio.inc"\n' + source, None, "test.asm", (INC,))


# out[tid] = tid*tid + 1, con out en OUT.
SQUARE = asm(f"""
    GETTID R1
    MUL    R2, R1, R1
    ADDI   R2, R2, 1
    MOVI   R3, 2
    SHL    R4, R1, R3
    LI     R5, {OUT}
    ADD    R4, R4, R5
    STORE  R2, R4, 0
    HALT
""")
THREE_ADDS = asm("ADDI R1, R1, 1\nADDI R1, R1, 1\nADDI R1, R1, 1\nHALT")
TRAP = asm("TRAP")


def make(cpu_source: str = "HALT", kernel: bytes | None = None, **kwargs):
    system = CpuGpuSystem(MEMORY, **kwargs)
    system.load_cpu_program(asm(cpu_source))
    if kernel is not None:
        system.load_memory(kernel, KERNEL)
    return system


def port(system, address, master):
    found = system.bus.device_for(master, address)
    if found is None:
        raise AssertionError(f"nada mapeado en {address:#010x}")
    return found


def read(system, address, master="cpu"):
    p = port(system, address, master)
    return p.read(address - p.BASE)


def write(system, address, value, master="cpu"):
    p = port(system, address, master)
    p.write(address - p.BASE, value)


def gpu(offset):
    return mm.MMIO_GPU_BASE + offset


def set_warp(system, n, pc=KERNEL, active=0xFF, group=0):
    base = mm.MMIO_GPU_WARPS_BASE + n * mm.MMIO_GPU_WARPS_STRIDE
    write(system, base + mm.MMIO_GPU_WARPS_PC_OFF, pc)
    write(system, base + mm.MMIO_GPU_WARPS_ACTIVE_OFF, active)
    write(system, base + mm.MMIO_GPU_WARPS_GROUP_OFF, group)


def word(system, address):
    return struct.unpack_from("<I", system.memory, address)[0]


LAUNCH = HERE / "examples" / "launch.asm"


def demo(**kwargs):
    """`launch.asm` entero, cargado en 0. Devuelve (sistema, dirección de `out`).

    `out` son las 16 últimas palabras de la imagen: el fichero acaba con ellas.
    """
    image = sim.load_program_file(LAUNCH)
    system = CpuGpuSystem(MEMORY, **kwargs)
    system.load_cpu_program(image)
    return system, len(image) - 64


def run_gpu(system, limit=10_000):
    for _ in range(limit):
        if system.gpu.system.halted:
            return
        system.gpu.step()
    raise AssertionError("la GPU no paró")


class SharedMemoryTest(unittest.TestCase):
    def test_cpu_and_every_lane_share_one_bytearray(self):
        s = make()
        self.assertIs(s.cpu.memory, s.memory)
        self.assertIs(s.gpu.system.memory, s.memory)
        for warp in s.gpu.warps:
            self.assertIs(warp.memory, s.memory)
            for lane in warp.processors:
                self.assertIs(lane.memory, s.memory)

    def test_gpu_write_is_visible_to_the_cpu_and_vice_versa(self):
        s = make(f"""
            LI    R20, {OUT}
            LI    R21, 0x1234
            STORE R21, R20, 0x100       ; la CPU escribe
            HALT
        """)
        s.run()
        self.assertEqual(word(s, OUT + 0x100), 0x1234)
        self.assertEqual(s.cpu.read_u32(OUT + 0x100), 0x1234)


class LaunchTest(unittest.TestCase):
    def test_demo_cpu_launches_two_warps_and_reads_the_results(self):
        s, out = demo()
        self.assertEqual(s.run(), "halt")
        self.assertFalse(s.cpu.error)
        self.assertEqual([word(s, out + 4 * t) for t in range(16)],
                         [t * t + 1 for t in range(16)])
        self.assertEqual((s.cpu.regs[1], s.cpu.regs[2]), (2, 226))
        self.assertEqual(s.gpu.done, 0, "la CPU limpió WARP_DONE con W1C")

    def test_warp_done_is_sticky_until_the_cpu_clears_it(self):
        s = make(kernel=SQUARE)
        set_warp(s, 0)
        write(s, gpu(mm.MMIO_GPU_WARP_START_OFF), 1)
        self.assertEqual(read(s, gpu(mm.MMIO_GPU_WARP_LIVE_OFF)), 1)
        self.assertEqual(read(s, gpu(mm.MMIO_GPU_WARP_DONE_OFF)), 0)
        run_gpu(s)
        self.assertEqual(read(s, gpu(mm.MMIO_GPU_WARP_LIVE_OFF)), 0)
        self.assertEqual(read(s, gpu(mm.MMIO_GPU_WARP_DONE_OFF)), 1)
        self.assertEqual(read(s, gpu(mm.MMIO_GPU_WARP_DONE_OFF)), 1, "leer no limpia")
        write(s, gpu(mm.MMIO_GPU_WARP_DONE_OFF), 1)
        self.assertEqual(read(s, gpu(mm.MMIO_GPU_WARP_DONE_OFF)), 0)

    def test_starting_a_warp_clears_its_done_bit(self):
        s = make(kernel=SQUARE)
        set_warp(s, 3)
        write(s, gpu(mm.MMIO_GPU_WARP_START_OFF), 1 << 3)
        run_gpu(s)
        self.assertEqual(s.gpu.done, 1 << 3)
        write(s, gpu(mm.MMIO_GPU_WARP_START_OFF), 1 << 3)
        self.assertEqual(s.gpu.done, 0)

    def test_run_launches_only_enabled_descriptors_and_outlives_the_cpu(self):
        s = make(f"""
            LI    R10, MMIO_GPU_BASE
            MOVI  R14, 1
            STORE R14, R10, MMIO_GPU_CONTROL_OFF     ; RUN
            HALT                                     ; la CPU acaba antes que la GPU
        """, kernel=SQUARE)
        set_warp(s, 0)
        set_warp(s, 2)
        set_warp(s, 5, active=0)                     # deshabilitado
        self.assertEqual(s.run(), "halt")
        self.assertEqual(s.gpu.done, 0b101)
        for tid in range(24):
            expected = tid * tid + 1 if tid < 8 or 16 <= tid < 24 else 0
            self.assertEqual(word(s, OUT + 4 * tid), expected, tid)

    def test_new_work_can_be_added_while_other_warps_run(self):
        s = make(kernel=THREE_ADDS)
        set_warp(s, 0, active=1)
        set_warp(s, 1, active=1)
        write(s, gpu(mm.MMIO_GPU_WARP_START_OFF), 1)
        s.gpu.step()
        write(s, gpu(mm.MMIO_GPU_WARP_START_OFF), 2)
        self.assertEqual(s.gpu.live, 0b11)
        run_gpu(s)
        self.assertEqual(s.gpu.done, 0b11)

    def test_descriptor_registers_round_trip_and_simt_state_is_read_only(self):
        s = make()
        set_warp(s, 4, pc=0x40, active=0x0F, group=9)
        base = mm.MMIO_GPU_WARPS_BASE + 4 * mm.MMIO_GPU_WARPS_STRIDE
        self.assertEqual(read(s, base + mm.MMIO_GPU_WARPS_PC_OFF), 0x40)
        self.assertEqual(read(s, base + mm.MMIO_GPU_WARPS_ACTIVE_OFF), 0x0F)
        self.assertEqual(read(s, base + mm.MMIO_GPU_WARPS_GROUP_OFF), 9)
        self.assertEqual(read(s, base + mm.MMIO_GPU_WARPS_SIMT_OFF), 0)
        with self.assertRaises(AccessFault):
            write(s, base + mm.MMIO_GPU_WARPS_SIMT_OFF, 0)


DMA = HERE / "examples" / "dma" / "dma.asm"
GPU_OK, GPU_ERR_FAULT, GPU_ERR_TIMEOUT = 0, 1, 2
GUARD = 0xDEADBEEF
DMA_WORDS = 100


def dma_system(**kwargs):
    """`dma.asm` entero. Devuelve (sistema, dirección de `results`, de `buf_b`).

    Los datos son lo último de la imagen: results (44 bytes), buf_a y buf_b (400
    cada uno) y la palabra de guarda.
    """
    image = sim.load_program_file(DMA)
    system = CpuGpuSystem(MEMORY, **kwargs)
    system.load_cpu_program(image)
    end = len(image)
    return system, end - 848, end - 404


class DmaHarnessTest(unittest.TestCase):
    """El runtime y los kernels de `examples/dma`: el protocolo del §5 entero."""

    def setUp(self):
        self.system, self.results, self.buf_b = dma_system()
        self.assertEqual(self.system.run(), "halt")
        self.assertFalse(self.system.cpu.error)
        self.r = [word(self.system, self.results + 4 * i) for i in range(11)]

    def test_memset_then_memcpy_are_correct_down_to_the_last_word(self):
        # job 1 (memset, 2 warps) y job 2 (memcpy, 4 warps), 100 palabras: la
        # ultima pasada es parcial en los dos y las lanes divergen.
        self.assertEqual(self.r[0:2], [GPU_OK, 0])
        self.assertEqual(self.r[2:4], [GPU_OK, 0])
        self.assertEqual(self.r[4], GUARD, "la guarda detras de buf_b no se toco")

    def test_a_faulting_job_is_reported_with_its_first_error(self):
        status, first_error, first_error_pc = self.r[5:8]
        self.assertEqual(status, GPU_ERR_FAULT)
        # error_code 0x02 (acceso a memoria), lane_valid, lane 0, warp 0
        self.assertEqual(first_error, 0x02 << 8 | 1 << 6)
        self.assertGreater(first_error_pc, 0)
        self.assertEqual(self.system.gpu.system.fault, None, "RESET la recupero")

    def test_a_job_that_never_ends_times_out_and_the_gpu_recovers(self):
        self.assertEqual(self.r[8], GPU_ERR_TIMEOUT)
        # tras el fallo y el timeout, el job 5 sale bien
        self.assertEqual(self.r[9:11], [GPU_OK, 0])
        self.assertEqual([word(self.system, self.buf_b + 4 * i) for i in range(DMA_WORDS)],
                         [0] * DMA_WORDS)

    def test_nothing_is_left_live_or_pending_at_the_end(self):
        # cada job se recogio con W1C de lo leido; el fallo y el timeout, con
        # WARP_DONE leido antes de RESET
        gpu = self.system.gpu
        self.assertEqual((gpu.live, gpu.done), (0, 0))


RENDER = HERE / "examples" / "render" / "render.asm"


def plasma_reference(frame: int) -> bytes:
    """El framebuffer RGB565 de `render.asm` en `frame`, calculado en Python.

    Es la misma aritmética entera que el kernel: tres ondas triangulares de seis
    bits, una por canal, en un mosaico de 80 x 60 celdas de 4 x 4 píxeles.
    """
    def tri(p):
        a = abs((p & 63) - 32)
        return a - (a >> 5)

    out = bytearray(320 * 240 * 2)
    for cy in range(60):
        for cx in range(80):
            pixel = (tri(cx + cy + frame) << 11
                     | tri(2 * cx - cy + 2 * frame) << 6
                     | tri(2 * cy - cx + 3 * frame))
            cell = struct.pack("<I", pixel | pixel << 16) * 2
            for line in range(4):
                start = ((cy * 4 + line) * 320 + cx * 4) * 2
                out[start:start + 8] = cell
    return bytes(out)


class RenderExampleTest(unittest.TestCase):
    """`examples/render`: la CPU lleva el bucle y la GPU pinta cada fotograma."""

    @classmethod
    def setUpClass(cls):
        video = sim.VideoDevice(frame_instructions=1000)
        video.stop_after_swaps = 2
        cls.system = CpuGpuSystem(32 * 1024 * 1024, video=video)
        cls.system.load_cpu_program(sim.load_program_file(RENDER))
        cls.outcome = cls.system.run()
        cls.video = video

    def test_it_stops_after_the_second_swap_with_both_cores_healthy(self):
        self.assertEqual(self.outcome, "halt")
        self.assertEqual(self.video.swap_count, 2)
        self.assertFalse(self.system.cpu.error)
        self.assertIsNone(self.system.gpu.fault)

    def test_the_displayed_frame_is_the_second_one_drawn_by_the_gpu(self):
        base = self.video.fb_front
        frame = bytes(self.system.memory[base:base + 320 * 240 * 2])
        self.assertEqual(frame, plasma_reference(1))

    def test_the_other_buffer_still_holds_the_first_frame(self):
        base = self.video.fb_back
        frame = bytes(self.system.memory[base:base + 320 * 240 * 2])
        self.assertEqual(frame, plasma_reference(0))

    def test_every_warp_was_used_and_nothing_is_left_pending(self):
        gpu = self.system.gpu
        self.assertEqual((gpu.live, gpu.done), (0, 0))
        # 8 warps por frame; la CPU relanza los mismos ocho
        self.assertTrue(all(warp.instructions_executed > 0 for warp in gpu.warps))


class WarpConfigArraysTest(unittest.TestCase):
    """`LOGICAL_WARP_ID[n]` y `WARP_ARG[n]` (§14.2) y las instrucciones que los leen."""

    LOGICAL = mm.MMIO_GPU_WARPS_BASE + mm.MMIO_GPU_WARPS_LOGICAL_ID_OFF
    ARG = mm.MMIO_GPU_WARPS_BASE + mm.MMIO_GPU_WARPS_ARG_OFF

    def test_arrays_round_trip_per_warp(self):
        s = make()
        for n in range(8):
            write(s, self.LOGICAL + 4 * n, 100 + n)
            write(s, self.ARG + 4 * n, 0x8000_0000 + n)
        for n in range(8):
            self.assertEqual(read(s, self.LOGICAL + 4 * n), 100 + n)
            self.assertEqual(read(s, self.ARG + 4 * n), 0x8000_0000 + n)

    def test_the_arrays_do_not_alias_the_descriptors_or_each_other(self):
        s = make()
        set_warp(s, 0, pc=0x40, active=0x0F, group=9)
        write(s, self.LOGICAL, 1)
        write(s, self.ARG, 2)
        base = mm.MMIO_GPU_WARPS_BASE
        self.assertEqual(read(s, base + mm.MMIO_GPU_WARPS_PC_OFF), 0x40)
        self.assertEqual(read(s, base + mm.MMIO_GPU_WARPS_GROUP_OFF), 9)
        self.assertEqual((read(s, self.LOGICAL), read(s, self.ARG)), (1, 2))

    def test_offsets_outside_the_implemented_warps_are_errors(self):
        s = make(num_warps=4, warp_size=4)
        for name, address in (("LOGICAL_WARP_ID del warp 4", self.LOGICAL + 16),
                              ("WARP_ARG del warp 4", self.ARG + 16),
                              ("hueco entre descriptores y arrays", self.LOGICAL - 4),
                              ("tras WARP_ARG", self.ARG + 4 * 32)):
            with self.subTest(name):
                with self.assertRaises(AccessFault):
                    read(s, address)
                with self.assertRaises(AccessFault):
                    write(s, address, 1)

    def test_writing_them_with_the_warp_live_is_an_error(self):
        s = make(kernel=THREE_ADDS)
        set_warp(s, 0, active=1)
        write(s, gpu(mm.MMIO_GPU_CONTROL_OFF), sim.CTRL_HALT)
        write(s, gpu(mm.MMIO_GPU_WARP_START_OFF), 1)
        for address in (self.LOGICAL, self.ARG):
            with self.assertRaises(AccessFault):
                write(s, address, 5)
        write(s, self.LOGICAL + 4, 5)           # el warp 1 no está vivo

    def test_reset_keeps_them_like_the_descriptors(self):
        s = make(kernel=TRAP)
        set_warp(s, 0, active=1)
        write(s, self.LOGICAL, 7)
        write(s, self.ARG, 0x1234)
        write(s, gpu(mm.MMIO_GPU_WARP_START_OFF), 1)
        s.gpu.step()                            # TRAP: la GPU queda con error
        write(s, gpu(mm.MMIO_GPU_CONTROL_OFF), sim.CTRL_RESET)
        self.assertEqual((read(s, self.LOGICAL), read(s, self.ARG)), (7, 0x1234))

    def test_a_warp_cannot_read_or_write_them(self):
        for name, body in (("leer LOGICAL_WARP_ID", f"LI R1, {self.LOGICAL}\nLOAD R2, R1, 0"),
                           ("escribir WARP_ARG", f"LI R1, {self.ARG}\nSTORE R0, R1, 0")):
            with self.subTest(name):
                s = make(kernel=asm(body + "\nHALT"))
                set_warp(s, 0, active=1)
                write(s, gpu(mm.MMIO_GPU_WARP_START_OFF), 1)
                s.run()
                self.assertEqual(s.gpu.fault.code, ERROR_MEMORY_ACCESS)

    def test_the_cpu_launches_warps_with_ids_and_an_argument_pointer(self):
        """De extremo a extremo: la CPU rellena los registros y cada warp lo lee.

        Dos warps comparten el mismo bloque de argumentos (`WARP_ARG`) y se
        distinguen solo por su id lógico, que aquí NO es su slot físico (5 y 6).
        """
        s = make("""
            LI    R10, MMIO_GPU_BASE
            LI    R11, MMIO_GPU_WARPS_BASE
            LI    R12, kernel
            LI    R13, args
            MOVI  R14, 1
            ; warp físico 0 -> id lógico 5
            STORE R12, R11, MMIO_GPU_WARPS_PC_OFF
            STORE R14, R11, MMIO_GPU_WARPS_ACTIVE_OFF
            MOVI  R15, 5
            STORE R15, R11, MMIO_GPU_WARPS_LOGICAL_ID_OFF
            STORE R13, R11, MMIO_GPU_WARPS_ARG_OFF
            ; warp físico 1 -> id lógico 6
            STORE R12, R11, 16 + MMIO_GPU_WARPS_PC_OFF
            STORE R14, R11, 16 + MMIO_GPU_WARPS_ACTIVE_OFF
            MOVI  R15, 6
            STORE R15, R11, MMIO_GPU_WARPS_LOGICAL_ID_OFF + 4
            STORE R13, R11, MMIO_GPU_WARPS_ARG_OFF + 4
            MOVI  R14, 3
            STORE R14, R10, MMIO_GPU_WARP_START_OFF
        wait:
            LOAD  R15, R10, MMIO_GPU_WARP_DONE_OFF
            BNE   R15, R14, wait
            HALT

        kernel:                              ; out[lwarp] = args[0] + lwarp
            GETARG   R1                      ; puntero al bloque de argumentos
            LOAD     R2, R1, 0
            GETLWARP R3
            ADD      R2, R2, R3
            MOVI     R4, 2
            SHL      R4, R3, R4
            LI       R5, out
            ADD      R4, R4, R5
            STORE    R2, R4, 0
            HALT

        args:
            .word 1000
        out:
            .word 0, 0, 0, 0, 0, 0, 0, 0
        """)
        self.assertEqual(s.run(), "halt")
        self.assertFalse(s.cpu.error)
        self.assertIsNone(s.gpu.fault)
        # R13 conserva la dirección de `args`, que ocupa una palabra: `out` va detrás.
        out_address = s.cpu.regs[13] + 4
        words = [word(s, out_address + 4 * n) for n in range(8)]
        self.assertEqual(words, [0, 0, 0, 0, 0, 1005, 1006, 0])

    def test_getlane_and_getwarp_inside_a_launched_warp(self):
        s = make(kernel=asm(f"""
            GETLANE R1
            GETWARP R2
            LI      R5, {OUT}
            STORE   R1, R5, 0
            STORE   R2, R5, 4
            HALT"""))
        set_warp(s, 3, active=1)                # sólo la lane 0 del warp físico 3
        write(s, gpu(mm.MMIO_GPU_WARP_START_OFF), 1 << 3)
        s.run()
        self.assertIsNone(s.gpu.fault)
        self.assertEqual((word(s, OUT), word(s, OUT + 4)), (0, 3))


class ControlTest(unittest.TestCase):
    def status(self, s):
        return read(s, gpu(mm.MMIO_GPU_STATUS_OFF))

    def test_status_bits(self):
        s = make(kernel=THREE_ADDS)
        self.assertEqual(self.status(s), sim.STATUS_IDLE)
        set_warp(s, 0, active=1)
        set_warp(s, 1, active=1)
        write(s, gpu(mm.MMIO_GPU_WARP_START_OFF), 3)
        self.assertEqual(self.status(s), sim.STATUS_RUNNING | 2 << sim.STATUS_LIVE_SHIFT)
        write(s, gpu(mm.MMIO_GPU_CONTROL_OFF), sim.CTRL_HALT)
        self.assertEqual(self.status(s), sim.STATUS_HALTED | 2 << sim.STATUS_LIVE_SHIFT)
        write(s, gpu(mm.MMIO_GPU_CONTROL_OFF), sim.CTRL_RESUME)
        run_gpu(s)
        self.assertEqual(self.status(s), sim.STATUS_IDLE)

    def test_caps_declare_the_real_geometry(self):
        s = make(num_warps=4, warp_size=2)
        self.assertEqual(read(s, gpu(mm.MMIO_GPU_CAPS_OFF)), 4 | 2 << 8)

    def test_halt_keeps_state_and_resume_continues(self):
        s = make(kernel=THREE_ADDS)
        set_warp(s, 0, active=1)
        write(s, gpu(mm.MMIO_GPU_WARP_START_OFF), 1)
        s.gpu.step()
        s.gpu.step()
        pc = s.gpu.warps[0].pc
        write(s, gpu(mm.MMIO_GPU_CONTROL_OFF), sim.CTRL_HALT)
        self.assertFalse(s.gpu.step())
        self.assertEqual(s.gpu.warps[0].pc, pc)
        self.assertEqual(s.gpu.warps[0].processors[0].regs[1], 2)
        write(s, gpu(mm.MMIO_GPU_CONTROL_OFF), sim.CTRL_RESUME)
        run_gpu(s)
        self.assertEqual(s.gpu.warps[0].processors[0].regs[1], 3)

    def test_step_runs_one_warp_instruction_and_stays_halted(self):
        s = make(kernel=THREE_ADDS)
        set_warp(s, 0, active=1)
        write(s, gpu(mm.MMIO_GPU_WARP_START_OFF), 1)
        with self.assertRaises(AccessFault):
            write(s, gpu(mm.MMIO_GPU_CONTROL_OFF), sim.CTRL_STEP)   # sin HALT
        write(s, gpu(mm.MMIO_GPU_CONTROL_OFF), sim.CTRL_HALT)
        write(s, gpu(mm.MMIO_GPU_CONTROL_OFF), sim.CTRL_STEP)
        self.assertEqual(s.gpu.retired, 1)
        self.assertEqual(s.gpu.warps[0].pc, KERNEL + 4)
        self.assertTrue(self.status(s) & sim.STATUS_HALTED)

    def test_resume_requires_halted(self):
        s = make()
        with self.assertRaises(AccessFault):
            write(s, gpu(mm.MMIO_GPU_CONTROL_OFF), sim.CTRL_RESUME)

    def test_run_requires_no_live_warps(self):
        s = make(kernel=THREE_ADDS)
        set_warp(s, 0, active=1)
        write(s, gpu(mm.MMIO_GPU_CONTROL_OFF), sim.CTRL_HALT)
        write(s, gpu(mm.MMIO_GPU_WARP_START_OFF), 1)
        with self.assertRaises(AccessFault):
            write(s, gpu(mm.MMIO_GPU_CONTROL_OFF), sim.CTRL_RUN)

    def test_invalid_control_and_start_writes(self):
        s = make(kernel=THREE_ADDS)
        set_warp(s, 0, active=1)
        set_warp(s, 1, active=0)
        write(s, gpu(mm.MMIO_GPU_CONTROL_OFF), sim.CTRL_HALT)
        write(s, gpu(mm.MMIO_GPU_WARP_START_OFF), 1)
        cases = {
            "bits reservados": (mm.MMIO_GPU_CONTROL_OFF, 1 << 5),
            "comandos incompatibles": (mm.MMIO_GPU_CONTROL_OFF, sim.CTRL_RUN | sim.CTRL_HALT),
            "warp no implementado": (mm.MMIO_GPU_WARP_START_OFF, 1 << 8),
            "warp ya vivo": (mm.MMIO_GPU_WARP_START_OFF, 1),
            "ACTIVE a cero": (mm.MMIO_GPU_WARP_START_OFF, 2),
            "WARP_DONE no implementado": (mm.MMIO_GPU_WARP_DONE_OFF, 1 << 8),
            "escribir GPU_ID": (mm.MMIO_GPU_ID_OFF, 0),
            "escribir WARP_LIVE": (mm.MMIO_GPU_WARP_LIVE_OFF, 0),
            "registro reservado": (0x28, 0),
        }
        for name, (offset, value) in cases.items():
            with self.subTest(name), self.assertRaises(AccessFault):
                write(s, gpu(offset), value)
        for name, offset in {"WARP_START": mm.MMIO_GPU_WARP_START_OFF,
                             "reservado": 0x28}.items():
            with self.subTest("leer " + name), self.assertRaises(AccessFault):
                read(s, gpu(offset))

    def test_descriptor_writes_are_validated(self):
        s = make(num_warps=4, warp_size=4, kernel=THREE_ADDS)
        base = mm.MMIO_GPU_WARPS_BASE
        for name, offset, value in (
                ("PC desalineado", mm.MMIO_GPU_WARPS_PC_OFF, 0x42),
                ("lanes no implementadas", mm.MMIO_GPU_WARPS_ACTIVE_OFF, 0x10),
                ("warp no implementado", 4 * 16, 0),
                ("SIMT_STATE de solo lectura", mm.MMIO_GPU_WARPS_SIMT_OFF, 0)):
            with self.subTest(name), self.assertRaises(AccessFault):
                write(s, base + offset, value)
        set_warp(s, 0, active=1)
        write(s, gpu(mm.MMIO_GPU_WARP_START_OFF), 1)
        with self.assertRaises(AccessFault):          # warp 0 vivo
            write(s, base + mm.MMIO_GPU_WARPS_PC_OFF, KERNEL)
        write(s, base + 16 + mm.MMIO_GPU_WARPS_PC_OFF, KERNEL)   # warp 1 libre

    def test_reset_discards_runtime_but_keeps_descriptors(self):
        s = make(kernel=TRAP)
        set_warp(s, 1, active=1, group=7)
        write(s, gpu(mm.MMIO_GPU_WARP_START_OFF), 2)
        s.gpu.step()
        self.assertTrue(self.status(s) & sim.STATUS_ERROR)
        with self.assertRaises(AccessFault):
            write(s, gpu(mm.MMIO_GPU_CONTROL_OFF), sim.CTRL_RUN)   # error pendiente
        write(s, gpu(mm.MMIO_GPU_CONTROL_OFF), sim.CTRL_RESET)
        self.assertEqual(self.status(s), sim.STATUS_IDLE)
        self.assertEqual((s.gpu.live, s.gpu.done), (0, 0))
        base = mm.MMIO_GPU_WARPS_BASE + 16
        self.assertEqual(read(s, base + mm.MMIO_GPU_WARPS_ACTIVE_OFF), 1)
        self.assertEqual(read(s, base + mm.MMIO_GPU_WARPS_GROUP_OFF), 7)
        s.load_memory(THREE_ADDS, KERNEL)
        write(s, gpu(mm.MMIO_GPU_CONTROL_OFF), sim.CTRL_RUN)       # RESET seguido de RUN
        run_gpu(s)
        self.assertEqual(s.gpu.done, 2)

    def test_first_error_registers(self):
        s = make(kernel=TRAP)
        set_warp(s, 1, active=1)
        write(s, gpu(mm.MMIO_GPU_WARP_START_OFF), 2)
        s.gpu.step()
        debug = mm.MMIO_GPU_SIMT_BASE
        self.assertEqual(read(s, debug + mm.MMIO_GPU_SIMT_FIRST_ERROR_OFF),
                         ERROR_EXPLICIT_TRAP << 8 | 1 << 3)
        self.assertEqual(read(s, debug + mm.MMIO_GPU_SIMT_FIRST_ERROR_PC_OFF), KERNEL)
        write(s, debug + mm.MMIO_GPU_SIMT_CONTEXT_OFF, 1 << 3 | 2)
        self.assertEqual(read(s, debug + mm.MMIO_GPU_SIMT_CONTEXT_OFF), 1 << 3 | 2)
        with self.assertRaises(AccessFault):
            write(s, debug + mm.MMIO_GPU_SIMT_CONTEXT_OFF, 1 << 6)
        with self.assertRaises(AccessFault):
            write(s, debug + mm.MMIO_GPU_SIMT_FIRST_ERROR_OFF, 0)


class PermissionTest(unittest.TestCase):
    def run_kernel(self, body: str):
        s = make(kernel=asm(body + "\nHALT"))
        set_warp(s, 0, active=1)              # una sola lane: §4.2
        write(s, gpu(mm.MMIO_GPU_WARP_START_OFF), 1)
        self.assertEqual(s.run(), "halt")
        return s

    def test_a_warp_can_read_gpu_info_and_system(self):
        s = self.run_kernel(f"""
            LI    R1, MMIO_GPU_BASE
            LOAD  R2, R1, MMIO_GPU_CAPS_OFF
            LI    R3, MMIO_SYSTEM_BASE
            LOAD  R4, R3, MMIO_SYSTEM_MAGIC_OFF
            LI    R5, {OUT}
            STORE R2, R5, 0
            STORE R4, R5, 4
        """)
        self.assertIsNone(s.gpu.fault)
        self.assertEqual(word(s, OUT), 8 | 8 << 8)
        self.assertEqual(word(s, OUT + 4), mm.MMIO_MAGIC_VALUE)

    def test_a_warp_can_write_bytes_and_halves_into_the_shared_ram(self):
        s = self.run_kernel(f"""
            LI     R5, {OUT}
            MOVI   R1, 0x1234
            STOREH R1, R5, 0
            MOVI   R2, 0x77
            STOREB R2, R5, 2
        """)
        self.assertIsNone(s.gpu.fault)
        self.assertEqual(bytes(s.memory[OUT:OUT + 4]), bytes([0x34, 0x12, 0x77, 0x00]))
        # La CPU lee lo que escribió la GPU con sus propios accesos pequeños.
        self.assertEqual(s.cpu.read_sub(OUT, 2), 0x1234)
        self.assertEqual(s.cpu.read_sub(OUT + 2, 1), 0x77)

    def test_a_warp_cannot_control_the_gpu_or_touch_cpu_blocks(self):
        cases = {
            "LOADB de un registro MMIO que sí puede leer":
                "LI R1, MMIO_GPU_BASE\nLOADB R2, R1, MMIO_GPU_CAPS_OFF",
            "escribir GPU_CONTROL": "LI R1, MMIO_GPU_BASE\nMOVI R2, 1\nSTORE R2, R1, MMIO_GPU_CONTROL_OFF",
            "leer WARP_LIVE": "LI R1, MMIO_GPU_BASE\nLOAD R2, R1, MMIO_GPU_WARP_LIVE_OFF",
            "escribir un descriptor": "LI R1, MMIO_GPU_WARPS_BASE\nSTORE R0, R1, 0",
            "leer SIMT DEBUG": "LI R1, MMIO_GPU_SIMT_BASE\nLOAD R2, R1, 0",
            "leer CPU CORE": "LI R1, MMIO_CPU_BASE\nLOAD R2, R1, MMIO_CPU_ID_OFF",
            "escribir SYSTEM": "LI R1, MMIO_SYSTEM_BASE\nSTORE R0, R1, MMIO_SYSTEM_MAGIC_OFF",
        }
        for name, body in cases.items():
            with self.subTest(name):
                s = make(kernel=asm(body + "\nHALT"))
                set_warp(s, 0, active=1)
                write(s, gpu(mm.MMIO_GPU_WARP_START_OFF), 1)
                s.run()
                self.assertIsNotNone(s.gpu.fault)
                self.assertEqual(s.gpu.fault.code, ERROR_MEMORY_ACCESS)
                self.assertEqual(s.gpu.live, 1, "el warp que falla no termina")
                self.assertEqual(s.gpu.done, 0)

    def test_the_cpu_sees_its_own_blocks_and_system(self):
        s = make()
        self.assertEqual(read(s, mm.MMIO_CPU_BASE + mm.MMIO_CPU_ID_OFF), sim.CPU_ID)
        self.assertEqual(read(s, gpu(mm.MMIO_GPU_ID_OFF)), sim.GPU_ID)
        self.assertEqual(read(s, mm.MMIO_SYSTEM_BASE + mm.MMIO_SYSTEM_SYSTEM_ID_OFF), 32)
        self.assertEqual(read(s, mm.MMIO_SYSTEM_BASE + mm.MMIO_SYSTEM_MEM_SIZE_OFF), MEMORY)
        devices = read(s, mm.MMIO_SYSTEM_BASE + mm.MMIO_SYSTEM_DEVICES_OFF)
        for bit in (mm.MMIO_DEV_SYSTEM_BIT, mm.MMIO_DEV_CPU_BIT, mm.MMIO_DEV_GPU_BIT):
            self.assertTrue(devices >> bit & 1, bit)
        self.assertFalse(devices >> mm.MMIO_DEV_VIDEO_BIT & 1)

    def test_unmodelled_blocks_are_errors_not_zeros(self):
        s = make()
        for name, address in {"CPU PERF": mm.MMIO_CPU_PERF_BASE,
                              "GPU PERF": mm.MMIO_GPU_PERF_BASE,
                              "TIMER": mm.MMIO_TIMER_BASE,
                              "VIDEO sin habilitar": mm.MMIO_VIDEO_BASE}.items():
            with self.subTest(name):
                self.assertIsNone(s.bus.device_for("cpu", address))
                s2 = make(f"LI R1, {address}\nLOAD R2, R1, 0\nHALT")
                s2.run()
                self.assertTrue(s2.cpu.error)
                self.assertEqual(s2.cpu.error_code, ERROR_MEMORY_ACCESS)

    def test_cpu_access_fault_stops_the_cpu_with_error_2(self):
        s = make("LI R10, MMIO_GPU_BASE\nSTORE R0, R10, MMIO_GPU_ID_OFF\nHALT")
        s.run()
        self.assertTrue(s.cpu.error)
        self.assertEqual(s.cpu.error_code, ERROR_MEMORY_ACCESS)

    def test_sub_word_access_to_mmio_is_an_error(self):
        s = make("LI R10, MMIO_GPU_BASE\nLOADB R1, R10, MMIO_GPU_CAPS_OFF\nHALT")
        s.run()
        self.assertEqual(s.cpu.error_code, ERROR_MEMORY_ACCESS)


class VideoSharedTest(unittest.TestCase):
    def make_video(self):
        video = sim.VideoDevice(frame_instructions=5)
        s = CpuGpuSystem(MEMORY, video=video)
        s.load_cpu_program(asm("loop: BRA loop"))
        return s

    def arm(self, s, target):
        v = mm.MMIO_VIDEO_BASE
        write(s, v + mm.MMIO_VIDEO_HALT_TARGET_OFF, target)
        write(s, v + mm.MMIO_VIDEO_HALT_AT_OFF, 1)
        write(s, v + mm.MMIO_VIDEO_SWAP_OFF, 1)
        for _ in range(100):
            s.step_round()

    def test_video_is_visible_to_both_masters(self):
        s = self.make_video()
        self.assertEqual(read(s, mm.MMIO_VIDEO_BASE + mm.MMIO_VIDEO_CTRL_OFF),
                         read(s, mm.MMIO_VIDEO_BASE + mm.MMIO_VIDEO_CTRL_OFF, "gpu"))
        self.assertTrue(read(s, mm.MMIO_SYSTEM_BASE + mm.MMIO_SYSTEM_DEVICES_OFF)
                        >> mm.MMIO_DEV_VIDEO_BIT & 1)

    def test_halt_target_gpu_stops_only_the_gpu(self):
        s = self.make_video()
        self.arm(s, sim.VideoDevice.HALT_TARGET_GPU)
        self.assertTrue(s.gpu.halted_by_control)
        self.assertFalse(s.cpu.halted)

    def test_halt_target_cpu_stops_only_the_cpu(self):
        s = self.make_video()
        self.arm(s, sim.VideoDevice.HALT_TARGET_CPU)
        self.assertTrue(s.cpu.halted)
        self.assertFalse(s.gpu.halted_by_control)


class SchedulingTest(unittest.TestCase):
    def outcome(self, **kwargs):
        s, out = demo(**kwargs)
        s.run()
        return bytes(s.memory[out:out + 64]), s.cpu.regs[:]

    def test_result_does_not_depend_on_the_cpu_gpu_ratio(self):
        reference = self.outcome()
        for cpu_steps, gpu_steps in ((5, 1), (1, 5), (3, 7), (50, 1)):
            with self.subTest(cpu_steps=cpu_steps, gpu_steps=gpu_steps):
                self.assertEqual(self.outcome(cpu_steps=cpu_steps, gpu_steps=gpu_steps),
                                 reference)

    def test_same_input_gives_the_same_trace_of_instructions(self):
        a, b = demo()[0], demo()[0]
        for s in (a, b):
            s.run()
        self.assertEqual((a.cpu.instructions_executed, a.gpu.retired),
                         (b.cpu.instructions_executed, b.gpu.retired))

    def test_limit_stops_a_cpu_that_never_halts(self):
        s = make("loop: BRA loop")
        with self.assertRaises(InstructionLimitExceeded):
            s.run(100)
        self.assertEqual(s.instructions_executed, 100)

    def spinning(self):
        """CPU y un warp que no acaban nunca."""
        s = make("loop: BRA loop", kernel=asm("spin: BRA spin"))
        set_warp(s, 0, active=1)
        write(s, gpu(mm.MMIO_GPU_WARP_START_OFF), 1)
        return s

    def test_run_limit_is_n_for_each_core_not_n_between_both(self):
        s = self.spinning()
        # Se comprueban los dos límites antes de cada instrucción y cada ronda
        # empieza por la CPU: el de CPU salta tras su instrucción 100, antes de
        # la 100 de warp. Lo que importa es que son ~100 y ~100, no 50 y 50.
        with self.assertRaises(InstructionLimitExceeded):
            s.run(100)
        self.assertEqual((s.cpu_instructions, s.gpu.retired), (100, 99))

    def test_per_core_limits_override_the_common_one(self):
        s = self.spinning()
        with self.assertRaisesRegex(InstructionLimitExceeded, "CPU"):
            s.run(1000, max_cpu_instructions=10)
        self.assertEqual((s.cpu_instructions, s.gpu.retired), (10, 9))
        s = self.spinning()
        with self.assertRaisesRegex(InstructionLimitExceeded, "warp"):
            s.run(1000, max_gpu_instructions=7)
        self.assertEqual((s.cpu_instructions, s.gpu.retired), (7, 7))

    def test_a_core_that_already_stopped_does_not_trip_its_limit(self):
        self.assertEqual(make("HALT").run(max_cpu_instructions=1), "halt")
        s = make("HALT", kernel=THREE_ADDS)
        set_warp(s, 0, active=1)
        write(s, gpu(mm.MMIO_GPU_WARP_START_OFF), 1)
        self.assertEqual(s.run(max_cpu_instructions=1), "halt")
        self.assertEqual(s.gpu.done, 1, "la GPU acabó aunque la CPU ya estaba en su tope")

    def test_negative_limit_is_rejected(self):
        for kwargs in ({"max_instructions": -1}, {"max_cpu_instructions": -1},
                       {"max_gpu_instructions": -1}):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                make().run(**kwargs)

    def test_limit_counts_warp_instructions_across_relaunches(self):
        s = make("loop: BRA loop", kernel=THREE_ADDS)
        set_warp(s, 0, active=1)
        for _ in range(3):
            write(s, gpu(mm.MMIO_GPU_WARP_START_OFF), 1)
            run_gpu(s)
        self.assertEqual(s.gpu.retired, 12)

    def test_invalid_ratio_is_rejected(self):
        for kwargs in ({"cpu_steps": 0}, {"gpu_steps": -1}, {"num_warps": 9},
                       {"warp_size": 9}):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                make(**kwargs)


class CommandLineTest(unittest.TestCase):
    def test_demo_from_the_command_line(self):
        out = demo()[1]
        with tempfile.TemporaryDirectory() as folder:
            dump = Path(folder) / "out.bin"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = sim.main([str(LAUNCH), "--memory-size", hex(MEMORY),
                                 "--dump", hex(out), "64", str(dump)])
            self.assertEqual(code, 0, stdout.getvalue())
            self.assertEqual(struct.unpack("<16I", dump.read_bytes()),
                             tuple(t * t + 1 for t in range(16)))
            self.assertIn("GPU: ociosa", stdout.getvalue())

    def test_kernel_in_another_file_through_include(self):
        cpu_source = """
            .include "mmio.inc"
            LI    R10, MMIO_GPU_BASE
            LI    R11, MMIO_GPU_WARPS_BASE
            LI    R12, kernel                   ; la etiqueta está en kernel.asm
            MOVI  R13, 1
            STORE R12, R11, MMIO_GPU_WARPS_PC_OFF
            STORE R13, R11, MMIO_GPU_WARPS_ACTIVE_OFF
            STORE R13, R10, MMIO_GPU_WARP_START_OFF
        wait:
            LOAD  R15, R10, MMIO_GPU_WARP_DONE_OFF
            BEQ   R15, R0, wait
            HALT
            .include "kernel.asm"
        out:
            .word 0
        """
        kernel_source = """
        kernel:
            LI    R5, out                       ; y la de out está en cpu.asm
            MOVI  R1, 77
            STORE R1, R5, 0
            HALT
        """
        with tempfile.TemporaryDirectory() as folder:
            cpu_file = Path(folder) / "cpu.asm"
            cpu_file.write_text(cpu_source, encoding="utf-8")
            (Path(folder) / "kernel.asm").write_text(kernel_source, encoding="utf-8")
            image = sim.load_program_file(cpu_file)
            dump = Path(folder) / "out.bin"
            with contextlib.redirect_stdout(io.StringIO()):
                code = sim.main([str(cpu_file), "--memory-size", hex(MEMORY),
                                 "--dump", hex(len(image) - 4), "4", str(dump)])
            self.assertEqual(code, 0)
            self.assertEqual(struct.unpack("<I", dump.read_bytes()), (77,))

    def run_cli(self, *argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = sim.main([str(LAUNCH), "--memory-size", hex(MEMORY), *argv])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_run_limit_applies_to_each_core(self):
        # La demo ejecuta 37 instrucciones de CPU y 18 de warp.
        code, _, err = self.run_cli("--run-limit", "10")
        self.assertEqual(code, 2)
        self.assertIn("límite de 10 instrucciones de CPU", err)
        code, _, err = self.run_cli("--run-limit", "1000", "--cpu-run-limit", "10")
        self.assertEqual((code, "de CPU" in err), (2, True))
        code, _, err = self.run_cli("--run-limit", "1000", "--gpu-run-limit", "10")
        self.assertEqual((code, "de warp" in err), (2, True))
        code, _, err = self.run_cli("--run-limit", "10", "--cpu-run-limit", "1000",
                                    "--gpu-run-limit", "1000")
        self.assertEqual((code, err), (0, ""))

    def test_trace_limit_counts_cpu_and_warp_lines_together(self):
        code, out, err = self.run_cli("--trace-limit", "20")     # implica --trace
        self.assertEqual(code, 0, "el límite de traza no limita la ejecución")
        self.assertIn("GPU: ociosa", out)
        shown = [line for line in err.splitlines()
                 if line.startswith(("CPU", "GPU")) and "PASO" not in line]
        self.assertEqual(len(shown), 20)
        self.assertEqual({line[:3] for line in shown}, {"CPU", "GPU"})
        self.assertIn("... traza limitada a 20 líneas; la ejecución continúa", err)
        self.assertTrue(err.splitlines()[-1].startswith("FIN: HALT"))

    def test_trace_limit_larger_than_the_trace_prints_no_notice(self):
        code, _, err = self.run_cli("--trace-limit", "1000")
        self.assertEqual(code, 0)
        self.assertNotIn("traza limitada", err)

    def test_negative_trace_limit_is_rejected(self):
        code, _, err = self.run_cli("--trace-limit", "-1")
        self.assertEqual(code, 2)
        self.assertIn("trace-limit", err)

    def test_the_gpu_program_option_no_longer_exists(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            sim.main([str(LAUNCH), "--gpu-program", "kernel.asm"])

    def test_trace_interleaves_cpu_and_warp_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            trace = Path(folder) / "trace.txt"
            with contextlib.redirect_stdout(io.StringIO()):
                sim.main([str(LAUNCH), "--memory-size", hex(MEMORY),
                          "--trace-file", str(trace)])
            lines = trace.read_text(encoding="utf-8").splitlines()
        for line in lines:
            self.assertTrue(line.startswith(("CPU", "GPU", "FIN")), line)
        self.assertTrue(lines[-1].startswith("FIN: HALT"))
        owners = [line[:3] for line in lines
                  if line.startswith(("CPU", "GPU")) and "PASO" not in line]
        self.assertIn("CPU", owners)
        self.assertIn("GPU", owners)
        self.assertLess(owners.index("CPU"), owners.index("GPU"))
        self.assertGreater(owners.count("CPU"), 1)
        self.assertGreater(len(owners) - owners.index("GPU"), owners.count("GPU"),
                           "tras el primer warp aún hay líneas de CPU: se intercalan")


if __name__ == "__main__":
    unittest.main()
