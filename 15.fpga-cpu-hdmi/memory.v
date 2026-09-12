`default_nettype none

/*
 * 16 KiB synchronous memory organized as 4096 little-endian 32-bit words.
 * Each byte lane has an independent write enable so a byte-oriented monitor
 * and a 32-bit CPU can share the same physical storage.
 */
module memory #(
    parameter ADDRESS_WIDTH = 12
) (
    input clk,
    input reset,
    input [ADDRESS_WIDTH-1:0] address,
    input [31:0] write_data,
    input [3:0] write_enable,
    input read_enable,
    output reg [31:0] read_data,
    output reg ready
);

  reg [31:0] data[0:(1<<ADDRESS_WIDTH)-1];

  always @(posedge clk) begin
    ready <= 1'b0;

    if (reset) begin
      read_data <= 32'h0000_0000;
      ready <= 1'b0;
    end else if (|write_enable) begin
      if (write_enable[0]) data[address][7:0] <= write_data[7:0];
      if (write_enable[1]) data[address][15:8] <= write_data[15:8];
      if (write_enable[2]) data[address][23:16] <= write_data[23:16];
      if (write_enable[3]) data[address][31:24] <= write_data[31:24];
      ready <= 1'b1;
    end else if (read_enable) begin
      read_data <= data[address];
      ready <= 1'b1;
    end
  end
endmodule

`default_nettype wire
