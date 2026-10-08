#!/usr/bin/env python3
"""Mide en el RTL de la 36 (simulado con iverilog) cuantos ciclos de GPU cuesta
una instruccion de warp, segun su tipo y segun el numero de warps.

    python 36.fpga-cpu-gpu/sim/instr_rate.py [--warps 1 8] [--repeat 20]

Para cada tipo se ensambla un kernel con `repeat` copias de la instruccion, se
lanza con N warps usando el testbench `gpu_system_tb.v` (con la RAM del banco,
latencias 5 y 7) y se cuentan los ciclos de GPU con `running` alto. Se resta un
kernel sin ninguna copia, asi que el resultado es ciclos por instruccion de
warp en regimen, sin el arranque ni el HALT.

Hace falta `iverilog` y `vvp` en el PATH (viven en el paquete oss-cad-suite de
apio). Las latencias de memoria son las del testbench, no las de la SDRAM de la
placa: la columna de LOAD/STORE es orientativa; las de ALU, saltos, desplazamientos
y MUL no dependen de la memoria.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RTL = HERE.parent
sys.path.insert(0, str(RTL.parent / "1.isa"))
from mini_asm import assemble_bytes, write_hex  # noqa: E402

SOURCES = ["gpu_system.v", "gpu_sm.v", "gpu_lane.v", "gpu_register_file.v", "gpu_lsu2.v",
           "gpu_imem_buffer.v", "gpu_perf_counters.v", "gpu_mmio_bridge.v", "async_fifo.v",
           "instruction_buffer.v", "line_buffer.v", "gpu_aux_adapter_128.v",
           "fabric_fifo_bridge.v"]

# R1 = tid, R11 = 2, R12 = 5 (cantidades de desplazamiento), R13 = 0x400 + 4*tid
PROLOGUE = ["GETTID R1", "MOVI R11, 2", "MOVI R12, 5", "SHL R13, R1, R11", "ADDI R13, R13, 1024"]
ADD4 = ["ADD R2, R1, R1"] * 4
CASES = {
    "ADD / ADDI / MOVI": ["ADD R2, R1, R1"],
    "NOP": ["NOP"],
    "SHL por 2": ["SHL R2, R1, R11"],
    "SHL por 5": ["SHL R2, R1, R12"],
    "MUL": ["MUL R2, R1, R1"],
    "BNE no tomado": ["BNE R1, R1, 0"],
    "STORE (ocho lanes seguidas)": ["STORE R1, R13, 0"],
    "LOAD (ocho lanes seguidas)": ["LOAD R2, R13, 0"],
    "STORE + 2 ADD": ["STORE R1, R13, 0"] + ["ADD R2, R1, R1"] * 2,
    "STORE + 4 ADD": ["STORE R1, R13, 0"] + ADD4,
}


def testbench(warps: int, hexfile: Path) -> str:
    src = (RTL / "gpu_system_tb.v").read_text(encoding="utf-8")
    descriptors = "".join(
        f"        expect_write_ok(WARPS + 32'h{w * 16:02x}, 32'h0);\n"
        f"        expect_write_ok(WARPS + 32'h{w * 16 + 4:02x}, 32'hff);\n" for w in range(warps))
    start = src.index("        expect_write_ok(WARPS + 32'h00")
    end = src.index("        // ---- RUN ----")
    src = src[:start] + descriptors + src[end:]
    src = re.sub(r"expect_read\(CORE \+ 32'h20, 32'h0000_0003\);[^\n]*\n", "", src)
    src = re.sub(r"expect_read\(WARPS \+ 32'h[0-9a-f]+, 32'h0000_00ff\);\n", "", src)
    src = re.sub(r"expect_read\(WARPS \+ 32'h24, 32'h0000_0000\);[^\n]*\n", "", src)
    src = src.replace('"sim/kernel_square.hex"', '"' + hexfile.as_posix() + '"')
    src = src.replace("reg [31:0] kernel_words [0:8];", "reg [31:0] kernel_words [0:255];")
    src = src.replace("for (i = 0; i < 9; i = i + 1)\n            mem[i / 4]",
                      "for (i = 0; i < 256; i = i + 1)\n            mem[i / 4]")
    i = src.index('$display("GPU termino')
    j = src.index("\n", i)
    src = (src[:j + 1] + '        $display("TOTAL %0d %0d", last - first, dut.sm.retired_count);\n'
           "        $finish;\n" + src[j + 1:])
    src = src.replace("always #20 gclk = ~gclk;",
                      "always #20 gclk = ~gclk;\n    integer cyc = 0, first = -1, last = 0;", 1)
    tracer = """
    always @(posedge gclk) begin
        cyc = cyc + 1;
        if (dut.sm.running) begin
            if (first < 0) first = cyc;
            last = cyc;
        end
    end
"""
    k = src.index("endmodule")
    return src[:k] + tracer + src[k:]


def run(work: Path, warps: int, body: list[str]) -> tuple[int, int]:
    asm = "\n".join(PROLOGUE + body + ["HALT"]) + "\n"
    hexfile = work / "kernel.hex"
    write_hex(assemble_bytes(asm, work), hexfile)
    tb = work / "tb.v"
    tb.write_text(testbench(warps, hexfile), encoding="utf-8")
    vvp = work / "tb.vvp"
    subprocess.run(["iverilog", "-g2012", "-o", str(vvp), str(tb)] + SOURCES,
                   check=True, cwd=RTL)
    out = subprocess.run(["vvp", str(vvp)], check=True, capture_output=True,
                         text=True, cwd=RTL).stdout
    match = re.search(r"TOTAL (\d+) (\d+)", out)
    return int(match.group(1)), int(match.group(2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--warps", type=int, nargs="+", default=[1, 8])
    parser.add_argument("--repeat", type=int, default=20,
                        help="copias de la instruccion por kernel (el codigo debe caber antes de 0x400)")
    parser.add_argument("--out", type=Path, help="escribe la tabla en Markdown")
    args = parser.parse_args()

    rows: dict[str, list[float]] = {name: [] for name in CASES}
    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)
        for warps in args.warps:
            base_cycles, base_retired = run(work, warps, [])
            for name, body in CASES.items():
                cycles, retired = run(work, warps, body * args.repeat)
                rows[name].append((cycles - base_cycles) / (retired - base_retired))

    header = "| Instruccion | " + " | ".join(f"{w} warp{'s' if w > 1 else ''}" for w in args.warps) + " |"
    lines = [header, "|---|" + "---:|" * len(args.warps)]
    for name, values in rows.items():
        lines.append(f"| {name} | " + " | ".join(f"{v:.1f}".replace(".", ",") for v in values) + " |")
    text = "\n".join(lines) + "\n"
    print(text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
