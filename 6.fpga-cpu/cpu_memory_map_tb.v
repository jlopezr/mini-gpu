`timescale 1ns / 1ps
`default_nettype none

module cpu_memory_map_tb;

  reg clk = 1'b0;
  reg reset = 1'b1;
  reg run_request = 1'b0;
  reg halt_request = 1'b0;
  reg step_request = 1'b0;
  reg cpu_reset_request = 1'b0;

  reg [31:0] monitor_address = 32'h0000_0000;
  reg [7:0] monitor_write_data = 8'h00;
  reg monitor_write_enable = 1'b0;
  reg monitor_read_enable = 1'b0;

  wire [7:0] monitor_read_data;
  wire monitor_ready;
  wire monitor_error;
  wire halted;
  wire error;
  wire [7:0] error_code;
  wire instruction_retired;
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
  reg [4:0] debug_register_address = 5'd0;
  wire [31:0] debug_register_data;
  wire [31:0] debug_pc;
  integer instruction_cycle_count = 0;
  integer measured_instruction_cycles = 0;
  integer expected_instruction_cycles = 0;
  reg measuring_instruction = 1'b0;

  always #5 clk = ~clk;

  // Measure real instruction latency through the same registered EBR path
  // used by the FPGA top-level.
  always @(posedge clk) begin
    if (reset || cpu_reset_request) begin
      instruction_cycle_count <= 0;
      measured_instruction_cycles <= 0;
      expected_instruction_cycles <= 0;
      measuring_instruction <= 1'b0;
    end else if (cpu_i.state == 4'd1) begin
      instruction_cycle_count <= 1;
      measuring_instruction <= 1'b1;
    end else if (measuring_instruction) begin
      if (cpu_i.state == 4'd4) begin
        measured_instruction_cycles = instruction_cycle_count + 1;
        $display(
            "FPGA CYCLES: opcode=%02x pc=%08x cycles=%0d",
            cpu_i.opcode,
            cpu_i.pc - 4,
            measured_instruction_cycles
        );
        if (cpu_i.opcode == 6'h15 || cpu_i.opcode == 6'h16)
          expected_instruction_cycles = 14;
        else if (cpu_i.opcode == 6'h0a)
          expected_instruction_cycles = 13;
        else if (cpu_i.opcode >= 6'h07 && cpu_i.opcode <= 6'h09)
          expected_instruction_cycles = 10 + cpu_i.operand_b[4:0];
        else if (cpu_i.opcode >= 6'h20 && cpu_i.opcode <= 6'h25)
          expected_instruction_cycles = 11;
        else if (cpu_i.opcode == 6'h2f)
          expected_instruction_cycles = 10;
        else
          expected_instruction_cycles = 9;
        if (measured_instruction_cycles != expected_instruction_cycles)
          $fatal(
              1,
              "FPGA opcode %02x latency mismatch: expected %0d, got %0d",
              cpu_i.opcode,
              expected_instruction_cycles,
              measured_instruction_cycles
          );
        measuring_instruction <= 1'b0;
      end else begin
        instruction_cycle_count <= instruction_cycle_count + 1;
      end
    end
  end

  cpu cpu_i (
      .clk(clk),
      .reset(reset || cpu_reset_request),
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

  memory_map memory_map_i (
      .clk(clk),
      .reset(reset),
      .address(monitor_address),
      .write_data(monitor_write_data),
      .write_enable(monitor_write_enable),
      .read_enable(monitor_read_enable),
      .read_data(monitor_read_data),
      .ready(monitor_ready),
      .error(monitor_error),
      .cpu_halted(halted),
      .cpu_imem_valid(imem_valid),
      .cpu_imem_address(imem_address),
      .cpu_imem_read_data(imem_read_data),
      .cpu_imem_ready(imem_ready),
      .cpu_dmem_valid(dmem_valid),
      .cpu_dmem_address(dmem_address),
      .cpu_dmem_write_data(dmem_write_data),
      .cpu_dmem_write_enable(dmem_write_enable),
      .cpu_dmem_read_data(dmem_read_data),
      .cpu_dmem_ready(dmem_ready),
      .cpu_dmem_error(dmem_error)
  );

  task monitor_write_byte;
    input [31:0] address;
    input [7:0] data;
    begin
      wait (!monitor_ready);
      @(negedge clk);
      monitor_address = address;
      monitor_write_data = data;
      monitor_write_enable = 1'b1;
      @(negedge clk);
      monitor_write_enable = 1'b0;
      wait (monitor_ready);
      if (monitor_error) $fatal(1, "Monitor write failed at %08x", address);
    end
  endtask

  task monitor_write_word;
    input [31:0] address;
    input [31:0] data;
    begin
      monitor_write_byte(address, data[7:0]);
      monitor_write_byte(address + 1, data[15:8]);
      monitor_write_byte(address + 2, data[23:16]);
      monitor_write_byte(address + 3, data[31:24]);
    end
  endtask

  task expect_monitor_byte;
    input [31:0] address;
    input [7:0] expected;
    begin
      wait (!monitor_ready);
      @(negedge clk);
      monitor_address = address;
      monitor_read_enable = 1'b1;
      @(negedge clk);
      monitor_read_enable = 1'b0;
      wait (monitor_ready);
      #1;
      if (monitor_error || monitor_read_data !== expected) begin
        $fatal(1, "Monitor read mismatch at %08x", address);
      end
    end
  endtask

  initial begin
    $dumpvars(0, cpu_memory_map_tb);

    repeat (2) @(negedge clk);
    reset = 1'b0;
    @(negedge clk);

    // Program writes 0x1234 to global address 0x00100004, loads it, then halts.
    monitor_write_word(32'h0000_0000, 32'h4020_1234);  // MOVI R1, 0x1234
    monitor_write_word(32'h0000_0004, 32'h5c80_0010);  // MOVHI R4, 0x0010
    monitor_write_word(32'h0000_0008, 32'h4484_0004);  // ADDI R4, R4, 4
    monitor_write_word(32'h0000_000c, 32'h5824_0000);  // STORE R1, R4, 0
    monitor_write_word(32'h0000_0010, 32'h5444_0000);  // LOAD R2, R4, 0
    monitor_write_word(32'h0000_0014, 32'h54c0_0000);  // LOAD R6, R0, 0
    monitor_write_word(32'h0000_0018, 32'hfc00_0000);  // HALT

    @(negedge clk);
    run_request = 1'b1;
    @(negedge clk);
    run_request = 1'b0;
    wait (!halted);
    wait (halted);

    if (error || debug_pc !== 32'h0000_001c) $fatal(1, "CPU completion mismatch");

    debug_register_address = 5'd2;
    repeat (2) @(posedge clk);
    #1;
    if (debug_register_data !== 32'h0000_1234) $fatal(1, "R2 mismatch");

    // dmem can read bank 0: R6 receives the first instruction word.
    debug_register_address = 5'd6;
    repeat (2) @(posedge clk);
    #1;
    if (debug_register_data !== 32'h4020_1234) $fatal(1, "dmem bank 0 mismatch");

    // No backend translation is involved: CPU and monitor use the same address.
    expect_monitor_byte(32'h0010_0004, 8'h34);
    expect_monitor_byte(32'h0010_0005, 8'h12);
    expect_monitor_byte(32'h0010_0006, 8'h00);
    expect_monitor_byte(32'h0010_0007, 8'h00);

    // RESET_CPU clears architectural state but preserves both EBR contents.
    @(negedge clk);
    cpu_reset_request = 1'b1;
    @(negedge clk);
    cpu_reset_request = 1'b0;
    repeat (2) @(posedge clk);
    #1;

    if (!halted || error || debug_pc !== 32'h0000_0000)
      $fatal(1, "CPU reset state mismatch");
    if (debug_register_data !== 32'h0000_0000)
      $fatal(1, "CPU reset did not clear registers");

    expect_monitor_byte(32'h0010_0004, 8'h34);
    expect_monitor_byte(32'h0010_0005, 8'h12);

    // Program memory was preserved, so the CPU can run again without a reload.
    @(negedge clk);
    run_request = 1'b1;
    @(negedge clk);
    run_request = 1'b0;
    wait (!halted);
    wait (halted);
    if (error || debug_pc !== 32'h0000_001c)
      $fatal(1, "CPU did not rerun preserved program");

    // imem can fetch bank 1: branch from bank 0 to a HALT stored in bank 1.
    @(negedge clk);
    cpu_reset_request = 1'b1;
    @(negedge clk);
    cpu_reset_request = 1'b0;
    repeat (2) @(posedge clk);
    monitor_write_word(32'h0000_0000, 32'hbc03_ffff);  // BRA 0x00100000
    monitor_write_word(32'h0010_0000, 32'hfc00_0000);  // HALT
    @(negedge clk);
    run_request = 1'b1;
    @(negedge clk);
    run_request = 1'b0;
    wait (!halted);
    wait (halted);
    if (error || debug_pc !== 32'h0010_0004)
      $fatal(1, "imem could not execute from bank 1");

    $display("PASS: shared memory flow and CPU-only reset are correct");
    $finish;
  end
endmodule

`default_nettype wire
