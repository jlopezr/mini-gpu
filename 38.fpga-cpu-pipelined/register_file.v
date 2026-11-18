`default_nettype none

/* @reviewed 2026-10-09
 *
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
 * THIS FILE DIFFERS FROM THE ONE IN THE OTHER FOLDERS (experiment, 9 October
 * 2026). The others clear all 32 registers in the reset cycle, which forces
 * synthesis to use flip-flops: 1,061 FF plus 2,589 LUT4 of multiplexers for the
 * three reads. Here the bank is distributed RAM, and reset starts a 32-cycle
 * SWEEP that writes zero to every address instead.
 *
 * The RTL declares a single array, but a TRELLIS_DPR16X4 has only one read
 * port, so Yosys builds one copy of the RAM per read (A, B and debug). All
 * three copies share the same write port and therefore hold the same data.
 * Each copy is 32x32 bits = 2 cells deep x 8 cells wide = 16 cells, for a
 * total of 48 cells, 43 FF and 141 LUT4.
 *
 * While the sweep runs, and while `reset` is high, `busy` is 1 and reads are
 * not valid; the instantiating module must keep the CPU stalled. Normal writes
 * are ignored during the sweep for the same reason.
 *
 * R0 reads as zero because the sweep writes zero there and nothing else ever
 * writes that address (`normal_write` excludes it). There is no read-side mux
 * forcing zero, so any new write path into `registers` must keep that filter.
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

  // 0..31: sweeping; 32 (bit 5 set): done. Reset sets it back to 0. The
  // initial value also runs the sweep at power-up without a reset.
  reg [5:0] sweep = 6'd0;
  wire sweeping = !sweep[5];
  assign busy = reset || sweeping;

  /*
   * Debug is two cycles deep: first capture the requested address, then
   * capture the selected register. The debug port has its own RAM copy, so
   * the extra cycle is not caused by port sharing; it is inherited from the
   * flip-flop version, where it split the path from the distant monitor
   * register to a large 32-to-1 mux. With distributed RAM the read is only an
   * asynchronous DPR16X4 read plus a 2-to-1 mux, so the address register is
   * probably no longer needed, but it is kept: the monitor waits a fixed two
   * cycles anyway and UART traffic hides the latency. The CPU read ports
   * remain combinational. See 6.fpga-cpu/docs/timing.md.
   */
  reg [4:0] debug_address_registered;

  assign read_data_a = registers[read_address_a];
  assign read_data_b = registers[read_address_b];

  wire        normal_write = write_enable && write_address != 5'd0;
  wire [4:0]  waddr = sweeping ? sweep[4:0] : write_address;
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
