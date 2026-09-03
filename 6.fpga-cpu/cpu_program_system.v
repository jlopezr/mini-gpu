`default_nettype none

/*
 * Isolated MiniCPU test system with separate 16 KiB program and data memories.
 *
 * Program memory occupies byte addresses 0x00000000 through 0x00003fff.
 * Instructions must be aligned to four bytes. An invalid fetch returns an
 * unsupported instruction, allowing the CPU to stop through its normal
 * invalid-opcode path instead of silently wrapping the memory address.
 *
 * This module is retained for the focused CPU testbench and is not instantiated
 * by top.v. The complete monitor/CPU arbitration lives in memory_map.v. Writes
 * through this test loader are accepted only while the CPU is halted.
 */
module cpu_program_system (
    input clk,
    input reset,

    input run_request,
    input halt_request,
    input step_request,

    output halted,
    output error,
    output [7:0] error_code,
    output instruction_retired,

    input [31:0] program_write_address,
    input [31:0] program_write_data,
    input [3:0] program_write_enable,
    output program_write_ready,

    input [4:0] debug_register_address,
    output [31:0] debug_register_data,
    output [31:0] debug_pc
);

  wire imem_valid;
  wire [31:0] imem_address;
  wire [31:0] imem_read_data;
  wire imem_ready;
  wire dmem_valid;
  wire [31:0] dmem_address;
  wire [31:0] dmem_write_data;
  wire [3:0] dmem_write_enable;
  wire [31:0] dmem_read_data;
  wire dmem_ready;
  wire dmem_error;

  wire address_in_range = (imem_address[31:14] == 18'h00000);
  wire address_aligned = (imem_address[1:0] == 2'b00);
  wire valid_address = address_in_range && address_aligned;

  wire [31:0] program_read_data;
  wire program_ready;
  reg invalid_ready;
  wire [31:0] data_read_data;
  wire data_ready;
  reg invalid_data_ready;

  wire loader_address_valid =
      (program_write_address[31:14] == 18'h00000) &&
      (program_write_address[1:0] == 2'b00);
  wire loader_write =
      (|program_write_enable) && halted && loader_address_valid;
  wire [11:0] program_word_address =
      loader_write ? program_write_address[13:2] : imem_address[13:2];

  cpu cpu_i (
      .clk(clk),
      .reset(reset),
      .run_request(run_request),
      .halt_request(halt_request),
      .step_request(step_request),
      .halted(halted),
      .error(error),
      .error_code(error_code),
      .instruction_retired(instruction_retired),
      .imem_valid(imem_valid),
      .imem_address(imem_address),
      .imem_read_data(imem_read_data),
      .imem_ready(imem_ready),
      .dmem_valid(dmem_valid),
      .dmem_address(dmem_address),
      .dmem_write_data(dmem_write_data),
      .dmem_write_enable(dmem_write_enable),
      .dmem_read_data(dmem_read_data),
      .dmem_ready(dmem_ready),
      .dmem_error(dmem_error),
      .debug_register_address(debug_register_address),
      .debug_register_data(debug_register_data),
      .debug_pc(debug_pc)
  );

  /*
   * The CPU sees data memory as a local Harvard address space starting at zero.
   * The complete top-level system exposes its data EBR at monitor address
   * 0x00100000; this isolated test module has no UART monitor.
   */
  wire data_address_valid =
      (dmem_address[31:14] == 18'h00000) &&
      (dmem_address[1:0] == 2'b00);

  memory data_memory (
      .clk(clk),
      .reset(reset),
      .address(dmem_address[13:2]),
      .write_data(dmem_write_data),
      .write_enable(dmem_write_enable & {4{dmem_valid && data_address_valid}}),
      .read_enable(dmem_valid && !(|dmem_write_enable) && data_address_valid),
      .read_data(data_read_data),
      .ready(data_ready)
  );

  memory program_memory (
      .clk(clk),
      .reset(reset),
      .address(program_word_address),
      .write_data(program_write_data),
      .write_enable(program_write_enable & {4{loader_write}}),
      .read_enable(imem_valid && valid_address && !loader_write),
      .read_data(program_read_data),
      .ready(program_ready)
  );

  always @(posedge clk) begin
    if (reset) begin
      invalid_ready <= 1'b0;
      invalid_data_ready <= 1'b0;
    end else begin
      invalid_ready <= imem_valid && !valid_address;
      invalid_data_ready <= dmem_valid && !data_address_valid;
    end
  end

  assign imem_read_data = valid_address ? program_read_data : 32'hf800_0000;
  assign imem_ready = program_ready || invalid_ready;
  assign program_write_ready = program_ready && loader_write;
  assign dmem_read_data = data_read_data;
  assign dmem_ready = data_ready || invalid_data_ready;
  assign dmem_error = invalid_data_ready;
endmodule

`default_nettype wire
