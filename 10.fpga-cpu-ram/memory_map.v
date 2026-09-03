`default_nettype none

/*
 * Harvard memory map shared by the UART monitor and CPU:
 *
 *   0x00000000 - 0x00003fff: 16 KiB program memory
 *   0x00100000 - 0x00103fff: 16 KiB data memory
 *
 * The monitor owns both memories while the CPU is halted. While it is running,
 * the CPU has a read-only instruction port and a read/write data port.
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
    output error,

    input cpu_halted,
    input cpu_imem_valid,
    input [31:0] cpu_imem_address,
    output [31:0] cpu_imem_read_data,
    output cpu_imem_ready,

    input cpu_dmem_valid,
    input [31:0] cpu_dmem_address,
    input [31:0] cpu_dmem_write_data,
    input [3:0] cpu_dmem_write_enable,
    output [31:0] cpu_dmem_read_data,
    output cpu_dmem_ready,
    output cpu_dmem_error
);

  wire program_selected = (address[31:14] == 18'h00000);
  wire data_selected = (address[31:14] == 18'h00040);
  wire request = write_enable || read_enable;
  wire monitor_request_allowed = request && cpu_halted;

  wire cpu_imem_address_valid =
      (cpu_imem_address[31:14] == 18'h00000) &&
      (cpu_imem_address[1:0] == 2'b00);
  wire cpu_dmem_address_valid =
      (cpu_dmem_address[31:14] == 18'h00000) &&
      (cpu_dmem_address[1:0] == 2'b00);

  wire [31:0] program_read_data;
  wire program_ready;
  wire [31:0] data_read_data;
  wire data_ready;

  wire [3:0] byte_write_enable =
      4'b0001 << address[1:0];
  wire [31:0] word_write_data = {
    write_data, write_data, write_data, write_data
  };
  reg invalid_ready;
  reg invalid_cpu_imem_ready;
  reg invalid_cpu_dmem_ready;
  reg [31:0] routed_cpu_imem_read_data;
  reg routed_cpu_imem_ready;
  reg [31:0] routed_cpu_dmem_read_data;
  reg routed_cpu_dmem_ready;
  reg routed_cpu_dmem_error;

  /*
   * Request registers form the timing boundary immediately before each EBR.
   * Address validation and monitor/CPU arbitration therefore cannot become
   * part of the EBR clock-enable path. valid/ready absorbs the extra cycle.
   * See timing.md, "Registro de las solicitudes a EBR".
   */
  reg [11:0] program_request_address;
  reg [31:0] program_request_write_data;
  reg [3:0] program_request_write_enable;
  reg program_request_read_enable;
  reg [11:0] data_request_address;
  reg [31:0] data_request_write_data;
  reg [3:0] data_request_write_enable;
  reg data_request_read_enable;

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
   * ready before the routed word registers and byte offset are valid.
   *
   * This adds one clock cycle of read latency but splits the path into:
   *
   *   BRAM -> routed program/data registers -> byte multiplexer -> monitor
   */
  reg routed_ready;
  reg [31:0] routed_program_read_word;
  reg [31:0] routed_data_read_word;
  reg routed_data_selected;
  reg [1:0] routed_byte_offset;

  memory program_memory (
      .clk(clk),
      .reset(reset),
      .address(program_request_address),
      .write_data(program_request_write_data),
      .write_enable(program_request_write_enable),
      .read_enable(program_request_read_enable),
      .read_data(program_read_data),
      .ready(program_ready)
  );

  memory data_memory (
      .clk(clk),
      .reset(reset),
      .address(data_request_address),
      .write_data(data_request_write_data),
      .write_enable(data_request_write_enable),
      .read_enable(data_request_read_enable),
      .read_data(data_read_data),
      .ready(data_ready)
  );

  always @(posedge clk) begin
    if (reset) begin
      invalid_ready <= 1'b0;
      invalid_cpu_imem_ready <= 1'b0;
      invalid_cpu_dmem_ready <= 1'b0;
      routed_cpu_imem_read_data <= 32'h0000_0000;
      routed_cpu_imem_ready <= 1'b0;
      routed_cpu_dmem_read_data <= 32'h0000_0000;
      routed_cpu_dmem_ready <= 1'b0;
      routed_cpu_dmem_error <= 1'b0;
      routed_ready <= 1'b0;
      routed_program_read_word <= 32'h0000_0000;
      routed_data_read_word <= 32'h0000_0000;
      routed_data_selected <= 1'b0;
      routed_byte_offset <= 2'd0;
      program_request_address <= 12'd0;
      program_request_write_data <= 32'h0000_0000;
      program_request_write_enable <= 4'b0000;
      program_request_read_enable <= 1'b0;
      data_request_address <= 12'd0;
      data_request_write_data <= 32'h0000_0000;
      data_request_write_enable <= 4'b0000;
      data_request_read_enable <= 1'b0;
    end else begin
      program_request_write_enable <= 4'b0000;
      program_request_read_enable <= 1'b0;
      data_request_write_enable <= 4'b0000;
      data_request_read_enable <= 1'b0;

      if (cpu_halted) begin
        program_request_address <= address[13:2];
        program_request_write_data <= word_write_data;
        program_request_write_enable <= byte_write_enable & {
          4{write_enable && program_selected}
        };
        program_request_read_enable <= read_enable && program_selected;

        data_request_address <= address[13:2];
        data_request_write_data <= word_write_data;
        data_request_write_enable <= byte_write_enable & {
          4{write_enable && data_selected}
        };
        data_request_read_enable <= read_enable && data_selected;
      end else begin
        program_request_address <= cpu_imem_address[13:2];
        program_request_read_enable <=
            cpu_imem_valid && cpu_imem_address_valid;

        data_request_address <= cpu_dmem_address[13:2];
        data_request_write_data <= cpu_dmem_write_data;
        data_request_write_enable <= cpu_dmem_write_enable & {
          4{cpu_dmem_valid && cpu_dmem_address_valid}
        };
        data_request_read_enable <=
            cpu_dmem_valid && !(|cpu_dmem_write_enable) &&
            cpu_dmem_address_valid;
      end

      invalid_ready <= request &&
          (!cpu_halted || (!program_selected && !data_selected));
      invalid_cpu_imem_ready <=
          cpu_imem_valid && !cpu_halted && !cpu_imem_address_valid;
      invalid_cpu_dmem_ready <=
          cpu_dmem_valid && !cpu_halted && !cpu_dmem_address_valid;
      routed_ready <= cpu_halted && (program_ready || data_ready);
      routed_cpu_imem_ready <=
          !cpu_halted && (program_ready || invalid_cpu_imem_ready);
      routed_cpu_dmem_ready <=
          !cpu_halted && (data_ready || invalid_cpu_dmem_ready);
      routed_cpu_dmem_error <= invalid_cpu_dmem_ready;

      if (!cpu_halted && (program_ready || invalid_cpu_imem_ready)) begin
        routed_cpu_imem_read_data <=
            invalid_cpu_imem_ready ? 32'hf800_0000 : program_read_data;
      end

      if (!cpu_halted && data_ready) begin
        routed_cpu_dmem_read_data <= data_read_data;
      end

      if (program_ready || data_ready) begin
        routed_byte_offset <= address[1:0];
        routed_data_selected <= data_ready;
      end

      if (program_ready) routed_program_read_word <= program_read_data;
      if (data_ready) routed_data_read_word <= data_read_data;
    end
  end

  assign read_data =
      routed_byte_offset == 2'd0 ?
          (routed_data_selected ? routed_data_read_word[7:0] :
                                  routed_program_read_word[7:0]) :
      routed_byte_offset == 2'd1 ?
          (routed_data_selected ? routed_data_read_word[15:8] :
                                  routed_program_read_word[15:8]) :
      routed_byte_offset == 2'd2 ?
          (routed_data_selected ? routed_data_read_word[23:16] :
                                  routed_program_read_word[23:16]) :
          (routed_data_selected ? routed_data_read_word[31:24] :
                                  routed_program_read_word[31:24]);
  assign ready = routed_ready || invalid_ready;
  assign error = invalid_ready;
  /*
   * Register both CPU RAM outputs before asserting ready. ECP5 EBR has a
   * sizeable clock-to-output delay; this stage keeps that delay out of the CPU
   * instruction and write-back paths while preserving the valid/ready contract.
   */
  assign cpu_imem_read_data = routed_cpu_imem_read_data;
  assign cpu_imem_ready = routed_cpu_imem_ready;
  assign cpu_dmem_read_data = routed_cpu_dmem_read_data;
  assign cpu_dmem_ready = routed_cpu_dmem_ready;
  assign cpu_dmem_error = routed_cpu_dmem_error;
endmodule

`default_nettype wire
