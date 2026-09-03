`default_nettype none

/*
 * Temporary Harvard memory map exposed through one monitor port:
 *
 *   0x00000000 - 0x00003fff: 16 KiB program memory
 *   0x00100000 - 0x00103fff: 16 KiB data memory
 *
 * The CPU will later receive independent instruction and data ports. For now,
 * this module provides the single routed port required by the UART monitor.
 */
module memory_map (
    input clk,
    input reset,
    input [31:0] address,
    input [7:0] write_data,
    input write_enable,
    input read_enable,
    output [7:0] read_data,
    output ready,
    output error
);

  wire program_selected = (address[31:14] == 18'h00000);
  wire data_selected = (address[31:14] == 18'h00040);
  wire request = write_enable || read_enable;

  wire [7:0] program_read_data;
  wire program_ready;
  wire [7:0] data_read_data;
  wire data_ready;

  reg invalid_ready;

  memory program_memory (
      .clk(clk),
      .reset(reset),
      .address(address[13:0]),
      .write_data(write_data),
      .write_enable(write_enable && program_selected),
      .read_enable(read_enable && program_selected),
      .read_data(program_read_data),
      .ready(program_ready)
  );

  memory data_memory (
      .clk(clk),
      .reset(reset),
      .address(address[13:0]),
      .write_data(write_data),
      .write_enable(write_enable && data_selected),
      .read_enable(read_enable && data_selected),
      .read_data(data_read_data),
      .ready(data_ready)
  );

  always @(posedge clk) begin
    if (reset) begin
      invalid_ready <= 1'b0;
    end else begin
      invalid_ready <= request && !program_selected && !data_selected;
    end
  end

  assign read_data = data_selected ? data_read_data : program_read_data;
  assign ready = program_ready || data_ready || invalid_ready;
  assign error = invalid_ready;
endmodule

`default_nettype wire
