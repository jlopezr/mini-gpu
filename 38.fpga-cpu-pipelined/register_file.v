`default_nettype none

/*
 * MiniISA register file.
 *
 * - 32 registers of 32 bits, of which R0 is hardwired to zero.
 * - Two combinational read ports for Ra and Rb.
 * - One synchronous write port for Rd.
 * - One registered read-only debug port.
 *
 * R0 IS HARDWIRED TO ZERO: writes are dropped, reads always return zero. It is
 * a rule of the ISA, not of this implementation, so this file is byte for byte
 * the same in every MiniCPU folder. See 1.isa/isa.md section 1.
 *
 * The write port is the only place that knows about R0. The read path is
 * deliberately untouched: reset clears all 32 entries and nothing ever writes
 * entry 0, so `registers[0]` is zero by construction and yosys propagates it as
 * a constant, removing the flops and the mux input on its own. An explicit
 * `(addr == 0) ? 0 : ...` would add a mux to the combinational read path, which
 * is the critical path this design has spent effort keeping short: it is what
 * forced STATE_DECODE to exist. See timing.md.
 */
module register_file (
    input clk,
    input reset,

    input [4:0] read_address_a,
    output [31:0] read_data_a,
    input [4:0] read_address_b,
    output [31:0] read_data_b,

    input write_enable,
    input [4:0] write_address,
    input [31:0] write_data,

    input [4:0] debug_address,
    output reg [31:0] debug_data
);

  reg [31:0] registers[0:31];
  integer index;

  /*
   * Debug is intentionally two cycles deep: first capture the requested
   * address, then capture the selected register. UART debug traffic tolerates
   * this latency and the large 32-to-1 mux no longer ends at a distant monitor
   * register. The CPU read ports remain combinational. See timing.md.
   */
  reg [4:0] debug_address_registered;

  assign read_data_a = registers[read_address_a];
  assign read_data_b = registers[read_address_b];
  always @(posedge clk) begin
    if (reset) begin
      debug_address_registered <= 5'd0;
      debug_data <= 32'h0000_0000;

      for (index = 0; index < 32; index = index + 1) begin
        registers[index] <= 32'h0000_0000;
      end
    end else begin
      debug_address_registered <= debug_address;
      debug_data <= registers[debug_address_registered];

      if (write_enable && write_address != 5'd0) begin
        registers[write_address] <= write_data;
      end
    end
  end
endmodule

`default_nettype wire
