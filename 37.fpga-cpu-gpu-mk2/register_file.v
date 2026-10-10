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
 * a rule of the ISA, not of this implementation. See 1.isa/isa.md section 1.
 *
 * This implementation uses distributed RAM. A 32-cycle sweep clears every
 * address after reset; while it runs, `busy` keeps the CPU stopped and reads
 * are not valid. Address zero remains hardwired by construction because the
 * sweep clears it and normal writes to it are discarded.
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
    output reg [31:0] debug_data,

    output busy
);

  reg [31:0] registers[0:31];

  // 0..31 sweep the bank; value 32 (bit 5 set) means initialization complete.
  reg [5:0] sweep = 6'd0;
  wire sweeping = !sweep[5];
  assign busy = reset || sweeping;

  /*
   * Debug is intentionally two cycles deep: first capture the requested
   * address, then capture the selected register. UART debug traffic tolerates
   * this latency and the large 32-to-1 mux no longer ends at a distant monitor
   * register. The CPU read ports remain combinational. See timing.md.
   */
  reg [4:0] debug_address_registered;

  assign read_data_a = registers[read_address_a];
  assign read_data_b = registers[read_address_b];

  wire normal_write = write_enable && write_address != 5'd0;
  wire [4:0] waddr = sweeping ? sweep[4:0] : write_address;
  wire [31:0] wdata = sweeping ? 32'h0000_0000 : write_data;

  always @(posedge clk) begin
    if (reset) sweep <= 6'd0;
    else if (sweeping) sweep <= sweep + 6'd1;

    if (sweeping || normal_write) registers[waddr] <= wdata;

    if (reset) begin
      debug_address_registered <= 5'd0;
      debug_data <= 32'h0000_0000;
    end else begin
      debug_address_registered <= debug_address;
      debug_data <= registers[debug_address_registered];
    end
  end
endmodule

`default_nettype wire
