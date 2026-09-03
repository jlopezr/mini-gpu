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

  wire [31:0] program_read_data;
  wire program_ready;
  wire [31:0] data_read_data;
  wire data_ready;

  wire [3:0] byte_write_enable =
      4'b0001 << address[1:0];
  wire [31:0] word_write_data = {
    write_data, write_data, write_data, write_data
  };
  wire [31:0] selected_read_word =
      data_selected ? data_read_data : program_read_data;

  reg invalid_ready;

  /*
   * Registered monitor read path.
   *
   * A physical BRAM returns a complete 32-bit word. The monitor, however,
   * consumes only one of its four bytes. Performing BRAM selection, program/data
   * selection and byte selection in the same cycle produced a path that did not
   * meet the 120 MHz timing constraint.
   *
   * When either memory raises ready, these registers capture both the selected
   * word and address[1:0], which identifies the requested little-endian byte.
   * routed_ready is delayed by the same cycle so the monitor never observes
   * ready before routed_read_word and routed_byte_offset are valid.
   *
   * This adds one clock cycle of read latency but splits the path into:
   *
   *   BRAM -> routed_read_word -> byte multiplexer -> monitor
   */
  reg routed_ready;
  reg [31:0] routed_read_word;
  reg [1:0] routed_byte_offset;

  memory program_memory (
      .clk(clk),
      .reset(reset),
      .address(address[13:2]),
      .write_data(word_write_data),
      .write_enable(byte_write_enable & {4{write_enable && program_selected}}),
      .read_enable(read_enable && program_selected),
      .read_data(program_read_data),
      .ready(program_ready)
  );

  memory data_memory (
      .clk(clk),
      .reset(reset),
      .address(address[13:2]),
      .write_data(word_write_data),
      .write_enable(byte_write_enable & {4{write_enable && data_selected}}),
      .read_enable(read_enable && data_selected),
      .read_data(data_read_data),
      .ready(data_ready)
  );

  always @(posedge clk) begin
    if (reset) begin
      invalid_ready <= 1'b0;
      routed_ready <= 1'b0;
      routed_read_word <= 32'h0000_0000;
      routed_byte_offset <= 2'd0;
    end else begin
      invalid_ready <= request && !program_selected && !data_selected;
      routed_ready <= program_ready || data_ready;

      if (program_ready || data_ready) begin
        routed_read_word <= selected_read_word;
        routed_byte_offset <= address[1:0];
      end
    end
  end

  assign read_data =
      routed_byte_offset == 2'd0 ? routed_read_word[7:0] :
      routed_byte_offset == 2'd1 ? routed_read_word[15:8] :
      routed_byte_offset == 2'd2 ? routed_read_word[23:16] :
                                   routed_read_word[31:24];
  assign ready = routed_ready || invalid_ready;
  assign error = invalid_ready;
endmodule

`default_nettype wire
