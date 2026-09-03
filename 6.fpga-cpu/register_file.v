`default_nettype none

/*
 * MiniISA v0.1 register file.
 *
 * - 32 general-purpose registers of 32 bits.
 * - Two combinational read ports for Ra and Rb.
 * - One synchronous write port for Rd.
 * - One combinational read-only debug port.
 * - R0 is a normal writable register in MiniISA v0.1.
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
    output [31:0] debug_data
);

  reg [31:0] registers[0:31];
  integer index;

  assign read_data_a = registers[read_address_a];
  assign read_data_b = registers[read_address_b];
  assign debug_data = registers[debug_address];

  always @(posedge clk) begin
    if (reset) begin
      for (index = 0; index < 32; index = index + 1) begin
        registers[index] <= 32'h0000_0000;
      end
    end else if (write_enable) begin
      registers[write_address] <= write_data;
    end
  end
endmodule

`default_nettype wire
