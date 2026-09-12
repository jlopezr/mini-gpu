"""Rebuild the lane from the scalar core; arithmetic/FSM remain unchanged."""
from pathlib import Path

root = Path(__file__).resolve().parent
s = (root.parent / '6.fpga-cpu/cpu.v').read_text()
s = s.replace('module cpu (', 'module gpu_lane (\n    input [31:0] launch_pc,\n    input [31:0] thread_id,\n    input [31:0] register_a,\n    input [31:0] register_b,\n    output reg register_write_enable,\n    output reg [4:0] register_write_address,\n    output reg [31:0] register_write_data,')
s = s.replace('  wire [31:0] register_a;\n  wire [31:0] register_b;', '')
for line in ('  reg register_write_enable;\n', '  reg [4:0] register_write_address;\n', '  reg [31:0] register_write_data;\n'):
    s = s.replace(line, '')
start = s.index('  register_file register_file_i (')
end = s.index('\n  );', start) + len('\n  );')
s = s[:start] + '  assign debug_register_data = 32\'b0; // RF lives in gpu_sm.\n' + s[end:]
s = s.replace('if (run_request) begin\n            halted', 'if (run_request) begin\n            pc <= launch_pc;\n            halted')
s = s.replace('end else if (step_request) begin\n            halted', 'end else if (step_request) begin\n            pc <= launch_pc;\n            halted')
start = s.index('            OPCODE_GETTID: begin')
end = s.index('            end', start)
chunk = s[start:end]
import re
chunk = re.sub(r'register_write_data <= .*?;', 'register_write_data <= thread_id;', chunk)
s = s[:start] + chunk + s[end:]
s = s.replace("pc + 3'd4", "pc + 32'd4").replace("pc - 3'd4", "pc - 32'd4")
s = '// Derived by derive_lane.py from 6.fpga-cpu/cpu.v.\n// One instruction per step; external warp RF, launch PC and thread ID.\n' + s
(root / 'gpu_lane.v').write_text(s)
