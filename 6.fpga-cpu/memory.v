`default_nettype none

module memory #(
    parameter ADDRESS_WIDTH = 14
) (
    input clk,
    input reset,
    input [31:0] address,
    input [7:0] write_data,
    input write_enable,
    input read_enable,
    output reg [7:0] read_data,
    output reg ready,
    output reg error
);

  reg [7:0] data[0:(1<<ADDRESS_WIDTH)-1];

  always @(posedge clk) begin
    ready <= 1'b0;
    error <= 1'b0;

    if (reset) begin
      read_data <= 8'h00;
      ready <= 1'b0;
      error <= 1'b0;
    end else if ((write_enable || read_enable) && address[31:ADDRESS_WIDTH] != 0) begin
      ready <= 1'b1;
      error <= 1'b1;
    end else if (write_enable) begin
      data[address[ADDRESS_WIDTH-1:0]] <= write_data;
      ready <= 1'b1;
    end else if (read_enable) begin
      read_data <= data[address[ADDRESS_WIDTH-1:0]];
      ready <= 1'b1;
    end
  end
endmodule

`default_nettype wire
