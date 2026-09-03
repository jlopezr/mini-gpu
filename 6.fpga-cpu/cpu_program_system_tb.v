`timescale 1ns / 1ps
`default_nettype none

module cpu_program_system_tb;

  reg clk = 1'b0;
  reg reset = 1'b1;
  reg run_request = 1'b0;
  reg halt_request = 1'b0;
  reg step_request = 1'b0;
  reg [4:0] debug_register_address = 5'd0;
  reg [31:0] program_write_address = 32'h0000_0000;
  reg [31:0] program_write_data = 32'h0000_0000;
  reg [3:0] program_write_enable = 4'b0000;

  wire halted;
  wire error;
  wire [7:0] error_code;
  wire instruction_retired;
  wire program_write_ready;
  wire [31:0] debug_register_data;
  wire [31:0] debug_pc;

  integer retired_count = 0;

  always #5 clk = ~clk;

  cpu_program_system dut (
      .clk(clk),
      .reset(reset),
      .run_request(run_request),
      .halt_request(halt_request),
      .step_request(step_request),
      .halted(halted),
      .error(error),
      .error_code(error_code),
      .instruction_retired(instruction_retired),
      .program_write_address(program_write_address),
      .program_write_data(program_write_data),
      .program_write_enable(program_write_enable),
      .program_write_ready(program_write_ready),
      .debug_register_address(debug_register_address),
      .debug_register_data(debug_register_data),
      .debug_pc(debug_pc)
  );

  always @(posedge clk) begin
    if (reset) begin
      retired_count <= 0;
    end else if (instruction_retired) begin
      retired_count <= retired_count + 1;
    end
  end

  task expect_register;
    input [4:0] address;
    input [31:0] expected;
    begin
      debug_register_address = address;
      repeat (2) @(posedge clk);
      #1;

      if (debug_register_data !== expected) begin
        $fatal(
            1,
            "R%0d mismatch: expected %08x, got %08x",
            address,
            expected,
            debug_register_data
        );
      end
    end
  endtask

  task write_program_word;
    input [31:0] address;
    input [31:0] data;
    begin
      @(negedge clk);
      program_write_address = address;
      program_write_data = data;
      program_write_enable = 4'b1111;
      @(negedge clk);
      program_write_enable = 4'b0000;
    end
  endtask

  task reset_system;
    begin
      @(negedge clk);
      reset = 1'b1;
      repeat (2) @(negedge clk);
      reset = 1'b0;
      @(negedge clk);
    end
  endtask

  task run_until_halted;
    begin
      run_request = 1'b1;
      @(negedge clk);
      run_request = 1'b0;
      wait (!halted);
      wait (halted);

      // Account for the final instruction_retired pulse in retired_count.
      @(posedge clk);
      #1;
    end
  endtask

  initial begin
    $dumpvars(0, cpu_program_system_tb);

    reset_system();

    if (!halted || debug_pc !== 32'h0000_0000 || error) begin
      $fatal(1, "Reset state mismatch");
    end

    // Load the program through the same write interface the monitor will use.
    write_program_word(32'h0000_0000, 32'h4020_1234);  // MOVI R1, 0x1234
    write_program_word(32'h0000_0004, 32'h4080_0008);  // MOVI R4, 8
    write_program_word(32'h0000_0008, 32'h5824_fffc);  // STORE R1, R4, -4
    write_program_word(32'h0000_000c, 32'h5440_0004);  // LOAD R2, R0, 4
    write_program_word(32'h0000_0010, 32'h5464_fffc);  // LOAD R3, R4, -4
    write_program_word(32'h0000_0014, 32'hfc00_0000);  // HALT

    run_until_halted();

    expect_register(5'd1, 32'h0000_1234);
    expect_register(5'd2, 32'h0000_1234);
    expect_register(5'd3, 32'h0000_1234);
    expect_register(5'd4, 32'h0000_0008);

    if (debug_pc !== 32'h0000_0018) $fatal(1, "Final PC mismatch");
    if (retired_count !== 6) $fatal(1, "Retired instruction count mismatch");
    if (error || error_code !== 8'h00) $fatal(1, "Unexpected CPU error");

    // A word access not aligned to four bytes must trap and not retire.
    reset_system();
    write_program_word(32'h0000_0000, 32'h4020_1234);  // MOVI R1, 0x1234
    write_program_word(32'h0000_0004, 32'h5820_0002);  // STORE R1, R0, 2
    write_program_word(32'h0000_0008, 32'hfc00_0000);  // HALT (not reached)
    run_until_halted();

    if (!error || error_code !== 8'h02) $fatal(1, "Unaligned access did not trap");
    if (retired_count !== 1) $fatal(1, "Unaligned STORE was incorrectly retired");

    // The local data address space ends at byte address 0x00003fff.
    reset_system();
    write_program_word(32'h0000_0000, 32'h4080_4000);  // MOVI R4, 0x4000
    write_program_word(32'h0000_0004, 32'h5444_0000);  // LOAD R2, R4, 0
    write_program_word(32'h0000_0008, 32'hfc00_0000);  // HALT (not reached)
    run_until_halted();

    if (!error || error_code !== 8'h02) $fatal(1, "Out-of-range access did not trap");
    if (retired_count !== 1) $fatal(1, "Out-of-range LOAD was incorrectly retired");

    $display("PASS: CPU executes LOAD and STORE using physical Harvard memories");
    $finish;
  end
endmodule

`default_nettype wire
