"""Ejecuta Mandelbrot en MiniGPU, verifica el framebuffer y exporta ITER/PNG."""

import argparse
from pathlib import Path
import runpy
import struct
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "x.cpu-tests"))

from backends.gpu_simulator import GpuBackend
from run_gpu_tests import load_case, compare_result

WIDTH, HEIGHT, MAX_ITER = 320, 240, 256
BASE = 0x00100000


def generate_reference():
    """Referencia escalar Q16.16, independiente del ensamblador y la GPU."""
    reference = runpy.run_path(str(ROOT / "0.mandelbrot/mandelbrot_fixed.py"))
    values = [reference["mandelbrot"](*reference["pixel_to_complex"](x, y), MAX_ITER)
              for y in range(HEIGHT) for x in range(WIDTH)]
    (HERE / "expected.bin").write_bytes(struct.pack(f"<{len(values)}I", *values))
    print("Generado expected.bin desde la referencia escalar", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-only", action="store_true",
                        help="regenera expected.bin sin ejecutar la GPU")
    parser.add_argument("--output-dir", type=Path, default=HERE / "output")
    args = parser.parse_args()
    if args.reference_only:
        generate_reference()
        return 0

    from PIL import Image

    case = load_case(HERE / "test.json")
    backend = GpuBackend(ROOT)
    print("Ejecutando 320x240, 256 iteraciones, 8 warps x 8 lanes...", flush=True)
    start = time.monotonic()
    result = backend.run(
        program=case["program"], initial_memory=case["initial_memory"],
        register_numbers=set(), memory_ranges=list(case["expected"]["memory"]),
        max_instructions=case["max_instructions"], timeout_seconds=case["timeout_seconds"],
        warp_config=case["warp_config"],
    )
    errors = compare_result(case, result, "gpu-simulator")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    framebuffer = result["memory"][(BASE, WIDTH * HEIGHT * 4)]
    values = struct.unpack(f"<{WIDTH * HEIGHT}I", framebuffer)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "framebuffer.bin").write_bytes(framebuffer)
    converter = runpy.run_path(str(ROOT / "2.cpu-sim-func/raw_to_iter.py"))
    (args.output_dir / "mandelbrot.iter").write_bytes(
        converter["convert_raw_to_iter"](framebuffer, WIDTH, HEIGHT, MAX_ITER))
    viewer = runpy.run_path(str(ROOT / "0.mandelbrot/view_iterations.py"))
    image = Image.new("RGB", (WIDTH, HEIGHT))
    image.putdata([viewer["iteration_to_rgb"](value, MAX_ITER) for value in values])
    image.save(args.output_dir / "mandelbrot.png")
    print(f"PASS: {len(values)} píxeles idénticos a la referencia; "
          f"{result['observations']['instructions_executed']:,} instrucciones de warp; "
          f"{time.monotonic() - start:.1f} s")
    print(f"Resultados: {args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
