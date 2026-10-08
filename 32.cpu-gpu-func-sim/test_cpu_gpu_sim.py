import contextlib
import io
import math
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import cpu_gpu_sim as sim
from cpu_gpu_sim import AccessFault, CpuGpuSystem, InstructionLimitExceeded, mm

sys.path.insert(0, str(sim.ROOT / "1.isa"))
from mini_asm import assemble_bytes, first_pass  # noqa: E402

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


LAUNCH = HERE / "examples" / "asm" / "launch.asm"


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


DMA = HERE / "examples" / "asm" / "dma" / "dma.asm"
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
    """El runtime y los kernels de `examples/asm/dma`: el protocolo del §5 entero."""

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


RECT = HERE / "examples" / "asm" / "dma" / "rect.asm"


class RectKernelsTest(unittest.TestCase):
    """`gpu_k_fill_rect` y `gpu_k_blit`: el rectángulo exacto y nada alrededor."""

    RESULTS = 0x10000
    GUARD_WORD = 0xDEADBEEF

    @classmethod
    def setUpClass(cls):
        cls.system = CpuGpuSystem(MEMORY)
        cls.system.load_cpu_program(sim.load_program_file(RECT))
        guard = struct.pack("<I", cls.GUARD_WORD) * 0x4000           # 64 KiB de guarda
        for base in (0x20000, 0x40000, 0x50000, 0x70000):
            cls.system.load_memory(guard, base)
        cls.src1 = [0x1000 + n * 7 for n in range(7 * 15)]            # 7 filas, pitch 60
        cls.system.load_memory(struct.pack("<105I", *cls.src1), 0x30000)
        cls.src2 = [0x9000 + n for n in range(3 * 8)]                 # 3 filas, pitch 32
        cls.system.load_memory(struct.pack("<24I", *cls.src2), 0x60000)
        cls.outcome = cls.system.run()

    def words(self, base, count):
        return [word(self.system, base + 4 * i) for i in range(count)]

    def test_the_four_jobs_finish_cleanly(self):
        self.assertEqual(self.outcome, "halt")
        self.assertFalse(self.system.cpu.error)
        self.assertEqual(self.words(self.RESULTS, 4), [GPU_OK] * 4)

    def test_fill_rect_writes_exactly_its_rectangle(self):
        # 7 filas de 13 palabras en un pitch de 24 (96 bytes): fuera de ellas, guarda
        expected = []
        for row in range(7):
            expected += [0xAAAA5555] * 13 + [self.GUARD_WORD] * 11
        expected += [self.GUARD_WORD] * 24                            # la fila 8, intacta
        self.assertEqual(self.words(0x20000, len(expected)), expected)

    def test_blit_copies_each_row_to_its_place_and_nothing_else(self):
        expected = []
        for row in range(7):
            expected += self.src1[row * 15:row * 15 + 13] + [self.GUARD_WORD] * 15
        expected += [self.GUARD_WORD] * 28                            # la fila 8, intacta
        self.assertEqual(self.words(0x40000, len(expected)), expected)

    def test_a_one_word_fill_rect_writes_one_word(self):
        self.assertEqual(self.words(0x50000, 3), [0x12345678, self.GUARD_WORD, self.GUARD_WORD])

    def test_a_blit_with_fewer_rows_than_warps_still_copies_every_row(self):
        expected = []
        for row in range(3):
            expected += self.src2[row * 8:row * 8 + 8] + [self.GUARD_WORD] * 8
        expected += [self.GUARD_WORD] * 16                            # la fila 4, intacta
        self.assertEqual(self.words(0x70000, len(expected)), expected)

    def test_nothing_is_left_live_or_pending(self):
        gpu = self.system.gpu
        self.assertEqual((gpu.live, gpu.done), (0, 0))


BENCH_DMA = HERE / "examples" / "asm" / "dma" / "bench_dma.asm"


class BenchDmaTest(unittest.TestCase):
    """`bench_dma.asm` con tamaños hasta 4 KiB y una repetición: 4 operaciones x 5
    configuraciones x 6 tamaños, y cada una tiene que dar el resultado correcto."""

    @classmethod
    def setUpClass(cls):
        image, labels = race_image(BENCH_DMA)
        cls.labels = labels
        cls.system = CpuGpuSystem(32 * 1024 * 1024)
        cls.system.load_cpu_program(image)
        cls.system.load_memory(struct.pack("<I", 6), labels["bench_nsizes"])
        cls.system.load_memory(struct.pack("<I", 1), labels["bench_reps"])
        cls.outcome = cls.system.run()

    def test_it_finishes_with_every_configuration_correct(self):
        self.assertEqual(self.outcome, "halt")
        self.assertFalse(self.system.cpu.error)
        self.assertIsNone(self.system.gpu.fault)
        self.assertEqual(word(self.system, self.labels["bench_done"]), 1)
        self.assertEqual(word(self.system, self.labels["bench_errors"]), 0)

    def test_the_last_blit_left_its_rows_in_the_destination(self):
        # el último trabajo: blit de 4 KiB con 8 warps = 16 filas de 64 palabras, pitch 640
        src = [(i * 0x9E3779B1 + 0x1234567) & 0xFFFFFFFF for i in range(1024)]
        for row in range(16):
            got = [word(self.system, 0x600000 + row * 640 + 4 * i) for i in range(64)]
            self.assertEqual(got, src[row * 64:row * 64 + 64], f"fila {row}")

    def test_nothing_is_left_live_or_pending(self):
        gpu = self.system.gpu
        self.assertEqual((gpu.live, gpu.done), (0, 0))


POLL_EXP = HERE / "examples" / "asm" / "dma" / "poll_exp.asm"


class PollExperimentTest(unittest.TestCase):
    """`poll_exp.asm`: los 24 trabajos (memset y memcpy, 1 a 8 warps, 3 maneras de
    esperar) salen bien. Los ciclos no existen en el simulador: solo se comprueba
    que el programa funciona."""

    @classmethod
    def setUpClass(cls):
        image, labels = race_image(POLL_EXP)
        cls.labels = labels
        cls.system = CpuGpuSystem(32 * 1024 * 1024)
        cls.system.load_cpu_program(image)
        cls.system.load_memory(struct.pack("<I", 50), labels["exp_initial_cfg"])
        cls.outcome = cls.system.run()

    def test_it_finishes_with_every_job_correct(self):
        self.assertEqual(self.outcome, "halt")
        self.assertFalse(self.system.cpu.error)
        self.assertIsNone(self.system.gpu.fault)
        self.assertEqual(word(self.system, self.labels["exp_done"]), 1)
        self.assertEqual(word(self.system, self.labels["exp_errors"]), 0)

    def test_the_last_job_is_a_memcpy_of_256_kib_with_eight_warps(self):
        src = [(i * 0x9E3779B1 + 0x1234567) & 0xFFFFFFFF for i in (0, 1, 65535)]
        dst = [word(self.system, 0x600000 + 4 * i) for i in (0, 1, 65535)]
        self.assertEqual(dst, src)

    def test_nothing_is_left_live_or_pending(self):
        gpu = self.system.gpu
        self.assertEqual((gpu.live, gpu.done), (0, 0))


LAT_EXP = HERE / "examples" / "asm" / "dma" / "lat_exp.asm"


class LatencyExperimentTest(unittest.TestCase):
    """`lat_exp.asm`: los 24 trabajos de una lane terminan y escriben donde deben."""

    @classmethod
    def setUpClass(cls):
        image, labels = race_image(LAT_EXP)
        cls.labels = labels
        cls.system = CpuGpuSystem(32 * 1024 * 1024)
        cls.system.load_cpu_program(image)
        cls.outcome = cls.system.run()

    def test_it_finishes_cleanly(self):
        self.assertEqual(self.outcome, "halt")
        self.assertFalse(self.system.cpu.error)
        self.assertIsNone(self.system.gpu.fault)
        self.assertEqual(word(self.system, self.labels["lat_done"]), 1)

    def test_the_last_store_kernel_wrote_every_address_it_visited(self):
        # el último trabajo: store, stride 65536, 128 vueltas desde 0x600000
        for i in (0, 1, 64, 127):
            self.assertEqual(word(self.system, 0x600000 + i * 65536), 0x1234ABCD, i)
        # y entre dos direcciones visitadas no se tocó nada
        self.assertNotEqual(word(self.system, 0x600000 + 4), 0x1234ABCD)

    def test_nothing_is_left_live_or_pending(self):
        gpu = self.system.gpu
        self.assertEqual((gpu.live, gpu.done), (0, 0))


RENDER = HERE / "examples" / "asm" / "render" / "render.asm"


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


RENDER_V2 = HERE / "examples" / "asm" / "render" / "render_v2.asm"


class RenderExampleTest(unittest.TestCase):
    """`examples/asm/render`: la CPU lleva el bucle y la GPU pinta cada fotograma."""

    PROGRAM = RENDER

    @classmethod
    def setUpClass(cls):
        video = sim.VideoDevice(frame_instructions=1000)
        video.stop_after_swaps = 2
        cls.system = CpuGpuSystem(32 * 1024 * 1024, video=video)
        cls.system.load_cpu_program(sim.load_program_file(cls.PROGRAM))
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


class RenderV2ExampleTest(RenderExampleTest):
    """`render_v2.asm`: las escrituras coalescidas. La imagen tiene que ser la misma."""

    PROGRAM = RENDER_V2

    def test_it_never_diverges(self):
        # Las 8 lanes de un warp tienen siempre la misma fila: el bucle de filas
        # es uniforme y no abre ninguna región SIMT (v1 sí, en los 4 hilos que
        # sobraban).
        for warp in self.system.gpu.warps:
            self.assertEqual((len(warp.region_stack), len(warp.path_stack)),
                             (0, 0))

    def test_a_frame_is_about_46_thousand_warp_instructions(self):
        per_frame = self.system.gpu.retired / 2
        self.assertAlmostEqual(per_frame, 46_500, delta=1_500)


RENDER_CPU = HERE / "examples" / "asm" / "render" / "render_cpu.asm"


class RenderCpuExampleTest(unittest.TestCase):
    """`render_cpu.asm`: el mismo plasma, pintado solo por la CPU.

    Es la referencia de la comparación con la GPU, y solo vale si la imagen es
    la misma byte a byte.
    """

    @classmethod
    def setUpClass(cls):
        video = sim.VideoDevice(frame_instructions=1000)
        video.stop_after_swaps = 2
        cls.cpu = sim.cpu_sim.CPU(32 * 1024 * 1024, video=video)
        cls.cpu.load_program(sim.load_program_file(RENDER_CPU))
        cls.cpu.run(2_000_000)
        cls.video = video

    def test_it_paints_exactly_the_image_the_gpu_paints(self):
        front, back = self.video.fb_front, self.video.fb_back
        size = 320 * 240 * 2
        self.assertEqual(bytes(self.cpu.memory[front:front + size]),
                         plasma_reference(1))
        self.assertEqual(bytes(self.cpu.memory[back:back + size]),
                         plasma_reference(0))

    def test_a_frame_is_about_42_instructions_per_cell(self):
        # Medido: es el dato que usan las estimaciones de fotogramas por segundo.
        per_frame = self.cpu.instructions_executed / 2
        self.assertAlmostEqual(per_frame / (80 * 60), 42, delta=0.5)


RACE = HERE / "examples" / "asm" / "race"
RACE_COLORS = (0x07E0, 0xFD20, 0x07FF)      # CPU, GPU ingenua, GPU bien puesta


def race_image(path: Path):
    """(imagen, etiquetas) de un demo de `examples/asm/race`."""
    source = path.read_text(encoding="utf-8")
    labels = first_pass(source, path.parent, path.name, (INC,))[1]
    return assemble_bytes(source, path.parent, path.name, (INC,)), labels


def life_soup(seed: int = 12345):
    """La sopa inicial de `life.inc`: el mismo generador y los mismos dos bits."""
    state, grid = seed, []
    for _ in range(104):
        row = []
        for _ in range(160):
            state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
            row.append((state >> 30) & (state >> 29) & 1)
        grid.append(row)
    return grid


def life_step(grid):
    """B3/S23 en una rejilla con el borde muerto."""
    rows, cols = len(grid), len(grid[0])
    out = []
    for y in range(rows):
        row = []
        for x in range(cols):
            n = sum(grid[j][i]
                    for j in range(max(0, y - 1), min(rows, y + 2))
                    for i in range(max(0, x - 1), min(cols, x + 2))) - grid[y][x]
            row.append(1 if n == 3 or (n == 2 and grid[y][x]) else 0)
        out.append(row)
    return out


def life_pixels(grid, color: int) -> bytes:
    """Las 208 líneas de `life.inc`: cada celda, un cuadrado de 2 x 2 píxeles."""
    out = bytearray()
    for grid_row in grid:
        line = b"".join(struct.pack("<H", color if cell else 0) * 2 for cell in grid_row)
        out += line * 2
    return bytes(out)


class LifeRaceTest(unittest.TestCase):
    """`examples/asm/race/life.asm`: los tres métodos tienen que dar la misma vida.

    Con `race_period` a 1 el método cambia en cada fotograma (CPU, GPU ingenua,
    GPU bien puesta, CPU...) y la rejilla pasa de uno a otro sin ningún arreglo: si
    un solo método calculara algo distinto, la generación 7 ya no coincidiría.
    """

    FRAMES = 7
    PROGRAM = RACE / "life.asm"

    @classmethod
    def setUpClass(cls):
        image, labels = race_image(cls.PROGRAM)
        video = sim.VideoDevice(frame_instructions=1000)
        video.stop_after_swaps = cls.FRAMES
        cls.system = CpuGpuSystem(32 * 1024 * 1024, video=video)
        cls.system.load_cpu_program(image)
        cls.system.load_memory(struct.pack("<I", 1), labels["race_period"])
        cls.outcome = cls.system.run()
        cls.video = video
        cls.labels = labels
        cls.generations = [life_soup()]
        for _ in range(cls.FRAMES):
            cls.generations.append(life_step(cls.generations[-1]))

    def screen(self, base: int) -> bytes:
        start = base + 32 * 640
        return bytes(self.system.memory[start:start + 208 * 640])

    def test_it_stops_after_the_swaps_with_both_cores_healthy(self):
        self.assertEqual(self.outcome, "halt")
        self.assertEqual(self.video.swap_count, self.FRAMES)
        self.assertFalse(self.system.cpu.error)
        self.assertIsNone(self.system.gpu.fault)

    def test_the_displayed_frame_is_the_last_generation_drawn_by_its_method(self):
        method = (self.FRAMES - 1) % 3
        self.assertEqual(self.screen(self.video.fb_front),
                         life_pixels(self.generations[self.FRAMES], RACE_COLORS[method]))

    def test_the_previous_frame_is_the_generation_before_in_the_color_of_its_own_method(self):
        method = (self.FRAMES - 2) % 3
        self.assertEqual(self.screen(self.video.fb_back),
                         life_pixels(self.generations[self.FRAMES - 1], RACE_COLORS[method]))

    def test_the_soup_is_alive_and_changes(self):
        # sin esto, "las tres iguales" valdría también para una rejilla vacía
        first, last = self.generations[0], self.generations[self.FRAMES]
        self.assertGreater(sum(map(sum, first)), 3000)
        self.assertNotEqual(first, last)
        self.assertGreater(sum(map(sum, last)), 1500)

    def test_both_gpu_kernels_ran_and_nothing_is_left_pending(self):
        gpu = self.system.gpu
        self.assertEqual((gpu.live, gpu.done), (0, 0))
        self.assertTrue(all(warp.instructions_executed > 0 for warp in gpu.warps))

    def test_neither_gpu_kernel_diverges(self):
        for warp in self.system.gpu.warps:
            self.assertEqual((len(warp.region_stack), len(warp.path_stack)), (0, 0))


BLUR_SPOTS = ((3, 2), (2, 5), (5, 3))


def blur_step(grid, frame: int):
    """Un fotograma de `blur.inc`: enciende los puntos y desenfoca (borde a cero)."""
    grid = [row[:] for row in grid]
    for sx, sy in BLUR_SPOTS:
        x = abs(((frame * sx) & 255) - 128) + 16
        y = abs(((frame * sy + 64) & 127) - 64) + 16
        for j in (y - 1, y, y + 1):
            for i in (x - 1, x, x + 1):
                grid[j][i] = 255
    rows, cols = len(grid), len(grid[0])

    def at(j, i):
        return grid[j][i] if 0 <= j < rows and 0 <= i < cols else 0

    return [[((4 * at(j, i)
               + 2 * (at(j - 1, i) + at(j + 1, i) + at(j, i - 1) + at(j, i + 1))
               + at(j - 1, i - 1) + at(j - 1, i + 1) + at(j + 1, i - 1) + at(j + 1, i + 1))
              * 15) >> 8
             for i in range(cols)] for j in range(rows)]


def blur_pixels(grid) -> bytes:
    """Las 208 líneas de `blur.inc`: la paleta del calor, 2 x 2 píxeles por celda."""
    out = bytearray()
    for row in grid:
        line = b"".join(struct.pack("<H", ((v << 8) & 0xF800) | ((v << 3) & 0x07E0)) * 2
                        for v in row)
        out += line * 2
    return bytes(out)


class BlurRaceTest(unittest.TestCase):
    """`examples/asm/race/blur.asm`: los tres métodos tienen que dar el mismo calor."""

    FRAMES = 7
    PROGRAM = RACE / "blur.asm"

    @classmethod
    def setUpClass(cls):
        image, labels = race_image(cls.PROGRAM)
        video = sim.VideoDevice(frame_instructions=1000)
        video.stop_after_swaps = cls.FRAMES
        cls.system = CpuGpuSystem(32 * 1024 * 1024, video=video)
        cls.system.load_cpu_program(image)
        cls.system.load_memory(struct.pack("<I", 1), labels["race_period"])
        cls.outcome = cls.system.run()
        cls.video = video
        cls.generations = [[[0] * 160 for _ in range(104)]]
        for frame in range(cls.FRAMES):
            cls.generations.append(blur_step(cls.generations[-1], frame))

    def screen(self, base: int) -> bytes:
        start = base + 32 * 640
        return bytes(self.system.memory[start:start + 208 * 640])

    def test_it_stops_after_the_swaps_with_both_cores_healthy(self):
        self.assertEqual(self.outcome, "halt")
        self.assertEqual(self.video.swap_count, self.FRAMES)
        self.assertFalse(self.system.cpu.error)
        self.assertIsNone(self.system.gpu.fault)

    def test_the_displayed_frame_is_the_blur_after_the_last_frame(self):
        self.assertEqual(self.screen(self.video.fb_front),
                         blur_pixels(self.generations[self.FRAMES]))

    def test_the_previous_frame_is_the_one_before(self):
        self.assertEqual(self.screen(self.video.fb_back),
                         blur_pixels(self.generations[self.FRAMES - 1]))

    def test_there_is_heat_and_it_spreads(self):
        last = self.generations[self.FRAMES]
        self.assertGreater(max(map(max, last)), 150)
        self.assertGreater(sum(1 for row in last for v in row if v), 100)

    def test_the_gpu_ran_and_nothing_is_left_pending(self):
        gpu = self.system.gpu
        self.assertEqual((gpu.live, gpu.done), (0, 0))
        self.assertTrue(all(warp.instructions_executed > 0 for warp in gpu.warps))
        for warp in gpu.warps:
            self.assertEqual((len(warp.region_stack), len(warp.path_stack)), (0, 0))


def rotate_texture():
    """La textura de `rotate.inc`: 128 x 128 palabras con el mismo píxel dos veces."""
    out = []
    for ty in range(128):
        for tx in range(128):
            if ((tx >> 4) ^ (ty >> 4)) & 1:
                red = tx >> 2
                color = red << 11 | (ty >> 1) << 5 | (31 - red)
            else:
                color = 0x18C3
            out.append(color | color << 16)
    return out


def rotate_image(frame: int, texture) -> bytes:
    """Las 208 líneas de `rotate.inc` en `frame`, con la misma aritmética entera."""
    sin = [int(round(128 * math.sin(2 * math.pi * k / 64))) for k in range(64)]
    a = abs((frame & 31) - 16) - 8
    s = 48 + abs(((frame * 3) & 63) - 32)
    dux = (sin[(a + 16) & 63] * s) >> 7
    dvx = (sin[a & 63] * s) >> 7
    u00 = 8192 + 40 * frame - 80 * dux + 52 * dvx
    v00 = 8192 + 24 * frame - 80 * dvx - 52 * dux
    out = bytearray()
    for y in range(104):
        u, v = u00 - y * dvx, v00 + y * dux
        row = []
        for _ in range(160):
            row.append(texture[(v & 0x3F80) + ((u >> 7) & 127)])
            u += dux
            v += dvx
        line = struct.pack("<160I", *row)
        out += line * 2
    return bytes(out)


class RotateRaceTest(unittest.TestCase):
    """`examples/asm/race/rotate.asm`: los tres métodos tienen que dar la misma imagen."""

    FRAMES = 7
    PROGRAM = RACE / "rotate.asm"

    @classmethod
    def setUpClass(cls):
        image, labels = race_image(cls.PROGRAM)
        video = sim.VideoDevice(frame_instructions=1000)
        video.stop_after_swaps = cls.FRAMES
        cls.system = CpuGpuSystem(32 * 1024 * 1024, video=video)
        cls.system.load_cpu_program(image)
        cls.system.load_memory(struct.pack("<I", 1), labels["race_period"])
        cls.outcome = cls.system.run()
        cls.video = video
        cls.texture = rotate_texture()

    def screen(self, base: int) -> bytes:
        start = base + 32 * 640
        return bytes(self.system.memory[start:start + 208 * 640])

    def test_it_stops_after_the_swaps_with_both_cores_healthy(self):
        self.assertEqual(self.outcome, "halt")
        self.assertEqual(self.video.swap_count, self.FRAMES)
        self.assertFalse(self.system.cpu.error)
        self.assertIsNone(self.system.gpu.fault)

    def test_the_displayed_frame_is_the_last_one_drawn(self):
        self.assertEqual(self.screen(self.video.fb_front),
                         rotate_image(self.FRAMES - 1, self.texture))

    def test_the_previous_frame_is_the_one_before(self):
        self.assertEqual(self.screen(self.video.fb_back),
                         rotate_image(self.FRAMES - 2, self.texture))

    def test_consecutive_frames_differ(self):
        self.assertNotEqual(rotate_image(0, self.texture), rotate_image(1, self.texture))

    def test_the_gpu_ran_and_nothing_is_left_pending(self):
        gpu = self.system.gpu
        self.assertEqual((gpu.live, gpu.done), (0, 0))
        self.assertTrue(all(warp.instructions_executed > 0 for warp in gpu.warps))
        for warp in gpu.warps:
            self.assertEqual((len(warp.region_stack), len(warp.path_stack)), (0, 0))


CUBE_SIN = [int(round(128 * math.sin(2 * math.pi * k / 64))) for k in range(64)]
CUBE_EPS = 256
CUBE_LIM = 8192 + 2 * CUBE_EPS
CUBE_BG = 0x10A2
CUBE_PALETTE = [(0xF800, 0xFFFF), (0x7800, 0x8410), (0x07E0, 0xFFE0),
                (0x03E0, 0x8400), (0x001F, 0x07FF), (0x000F, 0x0410)]


def trunc_div(a: int, b: int) -> int:
    """La división de la CPU: truncada hacia cero."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def cube_texture(ident: int):
    """Una de las seis texturas de `cube.inc`: 64 x 64 palabras, borde negro de 2."""
    pattern = ident >> 1
    c0, c1 = CUBE_PALETTE[ident]
    out = []
    for ty in range(64):
        for tx in range(64):
            if pattern == 0:
                bit = ((tx >> 3) ^ (ty >> 3)) & 1
            elif pattern == 1:
                bit = ((tx + ty) >> 3) & 1
            else:
                bit = ((tx >> 2) & (ty >> 2)) & 1
            color = c1 if bit else c0
            if (tx - 2) & 0xFFFFFFFF >= 60 or (ty - 2) & 0xFFFFFFFF >= 60:
                color = 0
            out.append(color | color << 16)
    return out


def cube_matrix(frame: int):
    """R = Rx(a) Ry(b) en Q7: b es el fotograma y a sus tres cuartos."""
    b, a = frame & 63, (frame * 3 >> 2) & 63
    sb, cb = CUBE_SIN[b], CUBE_SIN[(b + 16) & 63]
    sa, ca = CUBE_SIN[a], CUBE_SIN[(a + 16) & 63]
    return [[cb, 0, sb],
            [(sa * sb) >> 7, ca, (-(sa * cb)) >> 7],
            [(-(ca * sb)) >> 7, sa, (ca * cb) >> 7]]


def cube_faces(frame: int):
    """Por eje, (textura, u00, v00, ux, vx, uy, vy), o una entrada inerte si está de canto."""
    m = cube_matrix(frame)
    out = []
    for i in range(3):
        if m[2][i] == 0:
            out.append((0, 0x40000000, 0x40000000, 0, 0, 0, 0))
            continue
        s = 1 if m[2][i] > 0 else -1
        coefficients = []
        for axis in ((i + 1) % 3, (i + 2) % 3):
            q = trunc_div(m[2][axis] << 14, m[2][i])
            cx = (m[0][axis] << 7) - ((q * m[0][i]) >> 7)
            cy = (m[1][axis] << 7) - ((q * m[1][i]) >> 7)
            ux, uy = cx >> 7, cy >> 7
            start = 4096 + ((s * q) >> 2) - 80 * ux - 52 * uy + CUBE_EPS
            coefficients.append((start, ux, uy))
        (u00, ux, uy), (v00, vx, vy) = coefficients
        out.append((2 * i + (s < 0), u00, v00, ux, vx, uy, vy))
    return out


def cube_image(frame: int, textures) -> bytes:
    """Las 208 líneas de `cube.inc` en `frame`, celda a celda como los tres métodos."""
    faces = cube_faces(frame)
    out = bytearray()
    for y in range(104):
        state = [[u00 + y * uy, v00 + y * vy, ux, vx, tex]
                 for (tex, u00, v00, ux, vx, uy, vy) in faces]
        row = []
        for _ in range(160):
            pixel = CUBE_BG | CUBE_BG << 16
            for u, v, _ux, _vx, tex in state:
                if (u & 0xFFFFFFFF) < CUBE_LIM and (v & 0xFFFFFFFF) < CUBE_LIM:
                    index = (((v - CUBE_EPS) * 2) & 0x3F00) \
                        + ((((u - CUBE_EPS) & 0xFFFFFFFF) >> 5) & 0xFC)
                    pixel = textures[tex][index >> 2]
                    break
            row.append(pixel)
            for s in state:
                s[0] += s[2]
                s[1] += s[3]
        out += struct.pack("<160I", *row) * 2
    return bytes(out)


class CubeRaceTest(unittest.TestCase):
    """`examples/asm/race/cube.asm`: los tres métodos tienen que dibujar el mismo cubo."""

    FRAMES = 7
    PROGRAM = RACE / "cube.asm"

    @classmethod
    def setUpClass(cls):
        image, labels = race_image(cls.PROGRAM)
        video = sim.VideoDevice(frame_instructions=1000)
        video.stop_after_swaps = cls.FRAMES
        cls.system = CpuGpuSystem(32 * 1024 * 1024, video=video)
        cls.system.load_cpu_program(image)
        cls.system.load_memory(struct.pack("<I", 1), labels["race_period"])
        cls.outcome = cls.system.run()
        cls.video = video
        cls.textures = [cube_texture(i) for i in range(6)]

    def screen(self, base: int) -> bytes:
        start = base + 32 * 640
        return bytes(self.system.memory[start:start + 208 * 640])

    def test_it_stops_after_the_swaps_with_both_cores_healthy(self):
        self.assertEqual(self.outcome, "halt")
        self.assertEqual(self.video.swap_count, self.FRAMES)
        self.assertFalse(self.system.cpu.error)
        self.assertIsNone(self.system.gpu.fault)

    def test_the_displayed_frame_is_the_last_one_drawn(self):
        self.assertEqual(self.screen(self.video.fb_front),
                         cube_image(self.FRAMES - 1, self.textures))

    def test_the_previous_frame_is_the_one_before(self):
        self.assertEqual(self.screen(self.video.fb_back),
                         cube_image(self.FRAMES - 2, self.textures))

    def test_there_is_a_cube_and_a_background(self):
        image = cube_image(self.FRAMES - 1, self.textures)
        words = struct.unpack("<%dI" % (len(image) // 4), image)
        background = CUBE_BG | CUBE_BG << 16
        painted = sum(1 for w in words if w != background)
        self.assertGreater(painted, 2000)
        self.assertLess(painted, len(words) * 0.8)
        self.assertGreater(len(set(words)), 6)

    def test_the_gpu_ran_and_nothing_is_left_pending(self):
        gpu = self.system.gpu
        self.assertEqual((gpu.live, gpu.done), (0, 0))
        self.assertTrue(all(warp.instructions_executed > 0 for warp in gpu.warps))

    def test_a_face_seen_edge_on_is_inert_and_the_rest_have_their_own_texture(self):
        for frame in range(64):
            matrix, faces = cube_matrix(frame), cube_faces(frame)
            live = [f for f, row in zip(faces, range(3)) if matrix[2][row] != 0]
            self.assertTrue(live, frame)
            self.assertEqual(len({f[0] for f in live}), len(live), frame)
            for face, axis in zip(faces, range(3)):
                if matrix[2][axis] == 0:
                    self.assertEqual(face[1], 0x40000000, frame)


class LifeRaceStripTest(unittest.TestCase):
    """La gráfica de tiempos: una columna por fotograma, color por método."""

    FRAMES = 4

    @classmethod
    def setUpClass(cls):
        # un reloj falso que avanza 7 líneas de gráfica en cada lectura
        real, real_labels = race_image(RACE / "life.asm")
        shift = struct.unpack_from("<I", real, real_labels["race_shift"])[0]
        source = f"""
.include "mmio.inc"
.include "race_host.inc"
.include "life.inc"
.include "../dma/gpu_runtime.inc"
bench_init:
    RET
bench_now:
    LI    R2, fake_clock
    LOAD  R1, R2, 0
    LI    R3, {7 << shift}
    ADD   R1, R1, R3
    STORE R1, R2, 0
    RET
fake_clock:
    .word 0
"""
        image = assemble_bytes(source, RACE, "strip.asm", (INC,))
        labels = first_pass(source, RACE, "strip.asm", (INC,))[1]
        video = sim.VideoDevice(frame_instructions=1000)
        video.stop_after_swaps = cls.FRAMES
        cls.system = CpuGpuSystem(32 * 1024 * 1024, video=video)
        cls.system.load_cpu_program(image)
        cls.system.load_memory(struct.pack("<I", 1), labels["race_period"])
        cls.system.run()
        cls.video = video

    def column(self, base: int, x: int):
        return [struct.unpack_from("<H", self.system.memory, base + y * 640 + 2 * x)[0]
                for y in range(32)]

    def test_each_frame_has_its_own_column_in_the_color_of_its_method(self):
        for frame in range(self.FRAMES):
            color = RACE_COLORS[frame % 3]
            expected = [0] * 25 + [color] * 7
            for base in (0x01000000, 0x01025800):
                self.assertEqual(self.column(base, frame), expected, f"frame {frame}")

    def test_the_columns_after_the_last_frame_are_still_empty(self):
        self.assertEqual(self.column(0x01000000, self.FRAMES), [0] * 32)
        self.assertEqual(self.column(0x01025800, 319), [0] * 32)


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


C_EXAMPLES = HERE / "examples" / "c"
C_SYSTEM = C_EXAMPLES / "system"


def build_c_example(name: str):
    """Compila `examples/c/<name>.c` (con el tema, p. ej. `dma/memset`) (mini-lcc + mini-opt) y devuelve (imagen, etiquetas).
    Se omite la prueba si no hay compilador (rcc de y.lcc y MSVC); cualquier otro fallo es un error."""
    sys.path.insert(0, str(C_SYSTEM))
    import build as c_build
    try:
        binary = c_build.build(C_EXAMPLES / f"{name}.c")
    except c_build.BuildError as error:
        if "MSVC" in str(error) or "submodulo" in str(error) or "rcc" in str(error):
            raise unittest.SkipTest("sin compilador de C para MiniISA (y.lcc/build/rcc y MSVC)")
        raise
    wrapper = (C_EXAMPLES / "_build" / f"{Path(name).name}.asm")
    labels = first_pass(wrapper.read_text(encoding="utf-8"), wrapper.parent, wrapper.name,
                        c_build.INCLUDE_DIRS)[1]
    return binary.read_bytes(), labels


class CKernelTest(unittest.TestCase):
    """`examples/c/dma/memset.c`: un programa en C con la CPU y un kernel de GPU en el mismo fichero,
    compilado con mini-lcc y mini-opt."""

    @classmethod
    def setUpClass(cls):
        image, cls.labels = build_c_example("dma/memset")
        cls.system = CpuGpuSystem(MEMORY)
        cls.system.load_cpu_program(image)
        cls.outcome = cls.system.run()

    def words(self, label, count):
        return [word(self.system, self.labels[label] + 4 * i) for i in range(count)]

    def test_the_program_halts_with_the_gpu_idle_and_gpu_ok(self):
        self.assertEqual(self.outcome, "halt")
        self.assertFalse(self.system.cpu.error)
        self.assertEqual(self.words("status", 1), [GPU_OK])

    def test_the_kernel_fills_the_whole_buffer_and_nothing_beyond(self):
        buffer = self.words("buffer", 4096 + 16)
        self.assertEqual(buffer[:4096], [0xABCD] * 4096)
        self.assertEqual(buffer[4096:], [0] * 16)

    def test_every_lane_of_four_warps_ran(self):
        # 4 warps x 8 lanes sobre 4096 palabras: 128 vueltas por lane
        self.assertGreater(self.system.gpu.retired, 128 * 4 * 5)


class CSystemKernelsTest(unittest.TestCase):
    """`examples/c/dma/gpu_kernels.c` frente a `asm/dma/gpu_kernels.inc`: los kernels de sistema en C dejan la misma
    memoria que los de ensamblador (y la que dice un modelo en Python) con casi las mismas
    instrucciones de warp. La proporción tiene un tope para que un cambio en mini-lcc o mini-opt que
    empeore el código se note."""

    MAX_RATIO = 1.10        # medido: 1,00 a 1,02

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(C_SYSTEM))
        import compare
        cls.compare = compare
        try:
            cls.rows = compare.compare()
        except compare.c_build.BuildError as error:
            if "MSVC" in str(error) or "submodulo" in str(error) or "rcc" in str(error):
                raise unittest.SkipTest("sin compilador de C para MiniISA (y.lcc/build/rcc y MSVC)")
            raise

    def model(self, work):
        c = self.compare
        words = [0x5A5A5A5A] * 16384
        src = c.pattern(16384, 7)
        if work.kernel == "memset":
            words[:work.params[2]] = [work.params[1]] * work.params[2]
        elif work.kernel == "memcpy":
            words[:work.params[2]] = src[:work.params[2]]
        elif work.kernel == "fill_rect":
            _, pitch, row_words, rows, value = work.params
            for r in range(rows):
                start = r * pitch // 4
                words[start:start + row_words] = [value] * row_words
        else:
            _, dst_pitch, _, src_pitch, row_words, rows = work.params
            for r in range(rows):
                start, s0 = r * dst_pitch // 4, r * src_pitch // 4
                words[start:start + row_words] = src[s0:s0 + row_words]
        return struct.pack("<16384I", *words)

    def test_both_implementations_leave_what_the_model_says(self):
        for work, _, _, same, memory in self.rows:
            with self.subTest(work.name):
                self.assertTrue(same, "C y ensamblador dejan memorias distintas")
                self.assertEqual(memory, self.model(work))

    def test_c_costs_about_the_same_warp_instructions_as_assembler(self):
        for work, asm_count, c_count, _, _ in self.rows:
            with self.subTest(work.name):
                self.assertLessEqual(c_count, asm_count * self.MAX_RATIO)


class CRotateTest(unittest.TestCase):
    """`examples/c/race/rotate.c`: la rotación de textura en C (CPU, GPU inocente y GPU buena, el mismo
    cuerpo con otro reparto de trabajo) frente a `rotate.inc`. Las seis versiones dejan la imagen del
    modelo; el coste de C frente al ensamblador tiene un tope que bajará cuando mini-opt saque del bucle lo
    invariante (ver el README de examples/c)."""

    # medido: CPU 1,22, GPU inocente 1,44, GPU buena 1,45
    MAX_RATIO = {"CPU": 1.35, "GPU inocente": 1.6, "GPU buena": 1.6}

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(C_SYSTEM))
        import compare_rotate
        try:
            cls.rows = compare_rotate.compare(5)
        except compare_rotate.c_build.BuildError as error:
            if "MSVC" in str(error) or "submodulo" in str(error) or "rcc" in str(error):
                raise unittest.SkipTest("sin compilador de C para MiniISA (y.lcc/build/rcc y MSVC)")
            raise

    def test_every_version_draws_the_modelled_image(self):
        for name, _, _, _, correct in self.rows:
            with self.subTest(name):
                self.assertTrue(correct)

    def test_c_stays_within_its_cost_cap_against_assembler(self):
        for name, _, asm_count, c_count, _ in self.rows:
            with self.subTest(name):
                self.assertLessEqual(c_count, asm_count * self.MAX_RATIO[name])

    def test_the_two_gpu_mappings_run_the_same_body(self):
        counts = {name: c for name, _, _, c, _ in self.rows}
        # la buena recorre 160 columnas en 20 vueltas de 8 y la inocente en 160: mismo trabajo,
        # distinto numero de instrucciones de warp, pero del mismo orden
        self.assertLess(abs(counts["GPU buena"] - counts["GPU inocente"]), counts["GPU inocente"] * 0.2)


class CDivergenceTest(unittest.TestCase):
    """`examples/c/simt/diverge.c`: cinco kernels en C cuyas lanes divergen; los `SSY` los pone el pase
    `ssy` de mini-opt. Cada resultado se compara con el mismo cálculo en Python."""

    THREADS = 32

    @classmethod
    def setUpClass(cls):
        image, cls.labels = build_c_example("simt/diverge")
        cls.system = CpuGpuSystem(MEMORY)
        cls.system.load_cpu_program(image)
        cls.outcome = cls.system.run()

    def words(self, label, count):
        return [word(self.system, self.labels[label] + 4 * i) for i in range(count)]

    def test_the_five_launches_finish_without_a_simt_error(self):
        self.assertEqual(self.outcome, "halt")
        self.assertFalse(self.system.gpu.fault)
        self.assertEqual(self.words("status", 5), [GPU_OK] * 5)

    def test_tail_loop_exits_in_different_iterations(self):
        # 1000 palabras entre 32 hilos: las lanes 0..7 hacen 32 vueltas y el resto, 31
        data = self.words("tail", 1000 + 16)
        self.assertEqual(data[:1000], [0xABCD] * 1000)
        self.assertEqual(data[1000:], [0] * 16)

    def test_if_else_on_the_thread_id(self):
        expected = [i * 3 if i & 1 else i + 100 for i in range(self.THREADS)]
        self.assertEqual(self.words("parity", self.THREADS), expected)

    def test_loop_with_a_different_trip_count_per_lane(self):
        def steps(x):
            count = 0
            while x > 1:
                x = x + 1 if x & 1 else x >> 1
                count += 1
            return count
        expected = [steps(i + 1) for i in range(self.THREADS)]
        self.assertEqual(self.words("steps", self.THREADS), expected)
        self.assertGreater(len(set(expected)), 4)          # que de verdad varíe

    def test_early_return_leaves_the_rest_untouched(self):
        expected = [i * i + 1 for i in range(21)] + [0x5555] * (self.THREADS + 8 - 21)
        self.assertEqual(self.words("guard", self.THREADS + 8), expected)

    def test_nested_loops_with_break(self):
        def count(i):
            n = 0
            for a in range((i & 7) + 1):
                for b in range(6):
                    if a * b >= 10:
                        break
                    n += 1
            return n
        self.assertEqual(self.words("nested", self.THREADS), [count(i) for i in range(self.THREADS)])


if __name__ == "__main__":
    unittest.main()
