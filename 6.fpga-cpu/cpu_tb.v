`timescale 1ns / 1ps
`default_nettype none

module cpu_tb;

  reg clk = 1'b0;
  reg reset = 1'b1;
  reg run_request = 1'b0;
  reg halt_request = 1'b0;
  reg step_request = 1'b0;
  reg [4:0] debug_register_address = 5'd0;
  reg [31:0] imem_read_data = 32'h0000_0000;
  reg imem_ready = 1'b0;

  wire halted;
  wire error;
  wire [7:0] error_code;
  wire instruction_retired;
  wire imem_valid;
  wire [31:0] imem_address;
  wire [31:0] debug_register_data;
  wire [31:0] debug_pc;

  reg [31:0] instruction_memory[0:31];
  integer retired_count = 0;
  integer instruction_cycle_count = 0;
  integer measured_instruction_cycles = 0;
  integer expected_instruction_cycles = 0;
  reg measuring_instruction = 1'b0;

  always #5 clk = ~clk;

  cpu dut (
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
      .dmem_valid(),
      .dmem_address(),
      .dmem_write_data(),
      .dmem_write_enable(),
      .dmem_read_data(32'h0000_0000),
      .dmem_ready(1'b0),
      .dmem_error(1'b0),
      .debug_register_address(debug_register_address),
      .debug_register_data(debug_register_data),
      .debug_pc(debug_pc)
  );

  // One-cycle-latency instruction memory model.
  always @(posedge clk) begin
    imem_ready <= imem_valid;
    if (imem_valid) begin
      imem_read_data <= instruction_memory[imem_address[6:2]];
    end

    if (reset) begin
      retired_count <= 0;
    end else if (instruction_retired) begin
      retired_count <= retired_count + 1;
    end
  end

  // Measure from STATE_FETCH_REQUEST through STATE_RETIRE. With this
  // testbench's one-cycle instruction-memory model, ordinary instructions
  // take six cycles, BRA seven, conditional branches eight, and shifts
  // 7 + Rb[4:0]. LOAD/STORE are excluded because their data-memory latency is
  // intentionally defined by the valid/ready handshake.
  always @(posedge clk) begin
    if (reset) begin
      instruction_cycle_count <= 0;
      measured_instruction_cycles <= 0;
      expected_instruction_cycles <= 0;
      measuring_instruction <= 1'b0;
    end else if (dut.state == 4'd1) begin
      instruction_cycle_count <= 1;
      measuring_instruction <= 1'b1;
    end else if (measuring_instruction) begin
      if (dut.state == 4'd4) begin
        measured_instruction_cycles = instruction_cycle_count + 1;
        if (dut.opcode >= 6'h07 && dut.opcode <= 6'h09)
          expected_instruction_cycles = 7 + dut.operand_b[4:0];
        else if (dut.opcode >= 6'h20 && dut.opcode <= 6'h25)
          expected_instruction_cycles = 8;
        else if (dut.opcode == 6'h2f)
          expected_instruction_cycles = 7;
        else
          expected_instruction_cycles = 6;

        $display(
            "CYCLES: opcode=%02x pc=%08x cycles=%0d",
            dut.opcode,
            dut.pc - 4,
            measured_instruction_cycles
        );
        if (dut.opcode != 6'h15 && dut.opcode != 6'h16 &&
            measured_instruction_cycles != expected_instruction_cycles)
          $fatal(
              1,
              "Opcode %02x latency mismatch: expected %0d, got %0d",
              dut.opcode,
              expected_instruction_cycles,
              measured_instruction_cycles
          );
        measuring_instruction <= 1'b0;
      end else begin
        instruction_cycle_count <= instruction_cycle_count + 1;
      end
    end
  end

  task reset_cpu;
    begin
      @(negedge clk);
      reset = 1'b1;
      repeat (2) @(negedge clk);
      reset = 1'b0;
      @(negedge clk);
    end
  endtask

  task pulse_run;
    begin
      run_request = 1'b1;
      @(negedge clk);
      run_request = 1'b0;
    end
  endtask

  task pulse_step;
    begin
      step_request = 1'b1;
      @(negedge clk);
      step_request = 1'b0;
    end
  endtask

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

  initial begin
    $dumpvars(0, cpu_tb);

    // minimal.asm: MOVI R1,10; MOVI R2,20; ADD R3,R1,R2; HALT.
    instruction_memory[0] = 32'h4020_000a;
    instruction_memory[1] = 32'h4040_0014;
    instruction_memory[2] = 32'h0461_1000;
    instruction_memory[3] = 32'hfc00_0000;

    reset_cpu();
    if (!halted || debug_pc !== 0 || error) $fatal(1, "Reset state mismatch");

    pulse_run();
    wait (!halted);
    wait (halted);
    @(posedge clk);
    #1;
    expect_register(5'd1, 32'd10);
    expect_register(5'd2, 32'd20);
    expect_register(5'd3, 32'd30);
    if (debug_pc !== 32'h0000_0010) $fatal(1, "Final PC mismatch");
    if (retired_count !== 4) $fatal(1, "Retired instruction count mismatch");
    if (error) $fatal(1, "Unexpected CPU error");

    // STEP executes exactly one instruction; R0 remains a normal register.
    instruction_memory[0] = 32'h4000_ffff;  // MOVI R0, -1
    instruction_memory[1] = 32'hfc00_0000;  // HALT
    reset_cpu();
    pulse_step();
    wait (!halted);
    wait (halted);
    @(posedge clk);
    #1;
    expect_register(5'd0, 32'hffff_ffff);
    if (debug_pc !== 32'h0000_0004) $fatal(1, "STEP PC mismatch");
    if (retired_count !== 1) $fatal(1, "STEP retired more than one instruction");

    // A halt request received during an instruction stops at its retirement.
    instruction_memory[0] = 32'h4020_000a;
    instruction_memory[1] = 32'h4040_0014;
    reset_cpu();
    pulse_run();
    wait (dut.state == 3'd3);
    halt_request = 1'b1;
    @(posedge clk);
    @(negedge clk);
    halt_request = 1'b0;
    wait (halted);
    @(posedge clk);
    #1;
    if (retired_count !== 1) $fatal(1, "HALT request did not stop at retirement");
    if (debug_pc !== 32'h0000_0004) $fatal(1, "HALT request PC mismatch");

    // First ALU extension batch: NOP, SUB, AND, OR and XOR.
    instruction_memory[0] = 32'h4020_ffff;  // MOVI R1, -1
    instruction_memory[1] = 32'h4040_0001;  // MOVI R2, 1
    instruction_memory[2] = 32'h0000_0000;  // NOP
    instruction_memory[3] = 32'h0862_0800;  // SUB R3, R2, R1 -> 2
    instruction_memory[4] = 32'h1081_1000;  // AND R4, R1, R2 -> 1
    instruction_memory[5] = 32'h14a1_1000;  // OR  R5, R1, R2 -> ffffffff
    instruction_memory[6] = 32'h18c1_1000;  // XOR R6, R1, R2 -> fffffffe
    instruction_memory[7] = 32'h08e0_1000;  // SUB R7, R0, R2 -> ffffffff
    instruction_memory[8] = 32'hfc00_0000;  // HALT
    reset_cpu();
    pulse_run();
    wait (!halted);
    wait (halted);
    @(posedge clk);
    #1;
    expect_register(5'd0, 32'h0000_0000);
    expect_register(5'd3, 32'h0000_0002);
    expect_register(5'd4, 32'h0000_0001);
    expect_register(5'd5, 32'hffff_ffff);
    expect_register(5'd6, 32'hffff_fffe);
    expect_register(5'd7, 32'hffff_ffff);
    if (debug_pc !== 32'h0000_0024) $fatal(1, "ALU batch final PC mismatch");
    if (retired_count !== 9) $fatal(1, "ALU batch retired count mismatch");
    if (error) $fatal(1, "ALU batch raised an unexpected error");

    // Immediate ALU batch. Logical immediates are zero-extended, unlike ADDI.
    instruction_memory[0] = 32'h4020_fffe;  // MOVI R1, -2
    instruction_memory[1] = 32'h4441_0005;  // ADDI R2, R1, 5 -> 3
    instruction_memory[2] = 32'h4861_8001;  // ANDI R3, R1, 8001 -> 8000
    instruction_memory[3] = 32'h4c82_8000;  // ORI  R4, R2, 8000 -> 8003
    instruction_memory[4] = 32'h50a4_ffff;  // XORI R5, R4, ffff -> 7ffc
    instruction_memory[5] = 32'h5cc0_abcd;  // MOVHI R6, abcd -> abcd0000
    instruction_memory[6] = 32'hc0e0_0000;  // GETTID R7 -> 0 in MiniCPU
    instruction_memory[7] = 32'hfc00_0000;  // HALT
    reset_cpu();
    pulse_run();
    wait (!halted);
    wait (halted);
    @(posedge clk);
    #1;
    expect_register(5'd1, 32'hffff_fffe);
    expect_register(5'd2, 32'h0000_0003);
    expect_register(5'd3, 32'h0000_8000);
    expect_register(5'd4, 32'h0000_8003);
    expect_register(5'd5, 32'h0000_7ffc);
    expect_register(5'd6, 32'habcd_0000);
    expect_register(5'd7, 32'h0000_0000);
    if (debug_pc !== 32'h0000_0020) $fatal(1, "Immediate batch final PC mismatch");
    if (retired_count !== 8) $fatal(1, "Immediate batch retired count mismatch");
    if (error) $fatal(1, "Immediate batch raised an unexpected error");

    // Shift batch. Only the low five bits of Rb select the shift amount.
    instruction_memory[0] = 32'h4020_0001;  // MOVI R1, 1
    instruction_memory[1] = 32'h4040_0004;  // MOVI R2, 4
    instruction_memory[2] = 32'h1c61_1000;  // SHL R3, R1, R2 -> 16
    instruction_memory[3] = 32'h4080_fff0;  // MOVI R4, -16
    instruction_memory[4] = 32'h20a4_1000;  // SHR R5, R4, R2 -> 0fffffff
    instruction_memory[5] = 32'h24c4_1000;  // SAR R6, R4, R2 -> ffffffff
    instruction_memory[6] = 32'h40e0_ffff;  // MOVI R7, -1; low five bits = 31
    instruction_memory[7] = 32'h1d01_3800;  // SHL R8, R1, R7 -> 80000000
    instruction_memory[8] = 32'hfc00_0000;  // HALT
    reset_cpu();
    pulse_run();
    wait (!halted);
    wait (halted);
    @(posedge clk);
    #1;
    expect_register(5'd3, 32'h0000_0010);
    expect_register(5'd5, 32'h0fff_ffff);
    expect_register(5'd6, 32'hffff_ffff);
    expect_register(5'd8, 32'h8000_0000);
    if (debug_pc !== 32'h0000_0024) $fatal(1, "Shift batch final PC mismatch");
    if (retired_count !== 9) $fatal(1, "Shift batch retired count mismatch");
    if (error) $fatal(1, "Shift batch raised an unexpected error");

    // Every conditional branch is taken. Interleaved TRAPs catch a wrong
    // comparison or target, and BRA skips the final one unconditionally.
    instruction_memory[0]  = 32'h4020_ffff;  // MOVI R1, -1
    instruction_memory[1]  = 32'h4040_0001;  // MOVI R2, 1
    instruction_memory[2]  = 32'h8021_0001;  // BEQ  R1, R1, +1
    instruction_memory[3]  = 32'hf800_0000;  // TRAP (must be skipped)
    instruction_memory[4]  = 32'h8422_0001;  // BNE  R1, R2, +1
    instruction_memory[5]  = 32'hf800_0000;
    instruction_memory[6]  = 32'h8822_0001;  // BLT  R1, R2, +1 (signed)
    instruction_memory[7]  = 32'hf800_0000;
    instruction_memory[8]  = 32'h8c41_0001;  // BGE  R2, R1, +1 (signed)
    instruction_memory[9]  = 32'hf800_0000;
    instruction_memory[10] = 32'h9041_0001;  // BLTU R2, R1, +1
    instruction_memory[11] = 32'hf800_0000;
    instruction_memory[12] = 32'h9422_0001;  // BGEU R1, R2, +1
    instruction_memory[13] = 32'hf800_0000;
    instruction_memory[14] = 32'hbc00_0001;  // BRA +1
    instruction_memory[15] = 32'hf800_0000;
    instruction_memory[16] = 32'h4060_1234;  // MOVI R3, 1234
    instruction_memory[17] = 32'hfc00_0000;  // HALT
    reset_cpu();
    pulse_run();
    wait (!halted);
    wait (halted);
    @(posedge clk);
    #1;
    expect_register(5'd3, 32'h0000_1234);
    if (debug_pc !== 32'h0000_0048) $fatal(1, "Branch batch final PC mismatch");
    if (retired_count !== 11) $fatal(1, "Branch batch retired count mismatch");
    if (error) $fatal(1, "Branch batch raised an unexpected error");

    // Complementary false cases: an incorrectly taken branch skips the MOVI
    // immediately following it and is detected in the destination register.
    instruction_memory[0]  = 32'h4020_ffff;  // MOVI R1, -1
    instruction_memory[1]  = 32'h4040_0001;  // MOVI R2, 1
    instruction_memory[2]  = 32'h8022_0001;  // BEQ  R1, R2: false
    instruction_memory[3]  = 32'h4140_0001;  // MOVI R10, 1
    instruction_memory[4]  = 32'h8421_0001;  // BNE  R1, R1: false
    instruction_memory[5]  = 32'h4160_0001;  // MOVI R11, 1
    instruction_memory[6]  = 32'h8841_0001;  // BLT  R2, R1: false (signed)
    instruction_memory[7]  = 32'h4180_0001;  // MOVI R12, 1
    instruction_memory[8]  = 32'h8c22_0001;  // BGE  R1, R2: false (signed)
    instruction_memory[9]  = 32'h41a0_0001;  // MOVI R13, 1
    instruction_memory[10] = 32'h9022_0001;  // BLTU R1, R2: false
    instruction_memory[11] = 32'h41c0_0001;  // MOVI R14, 1
    instruction_memory[12] = 32'h9441_0001;  // BGEU R2, R1: false
    instruction_memory[13] = 32'h41e0_0001;  // MOVI R15, 1
    instruction_memory[14] = 32'hfc00_0000;  // HALT
    reset_cpu();
    pulse_run();
    wait (!halted);
    wait (halted);
    @(posedge clk);
    #1;
    expect_register(5'd10, 32'h0000_0001);
    expect_register(5'd11, 32'h0000_0001);
    expect_register(5'd12, 32'h0000_0001);
    expect_register(5'd13, 32'h0000_0001);
    expect_register(5'd14, 32'h0000_0001);
    expect_register(5'd15, 32'h0000_0001);
    if (debug_pc !== 32'h0000_003c) $fatal(1, "False-branch final PC mismatch");
    if (retired_count !== 15) $fatal(1, "False-branch retired count mismatch");
    if (error) $fatal(1, "False-branch batch raised an unexpected error");

    // TRAP is a deliberate error stop and leaves PC at the offending instruction.
    instruction_memory[0] = 32'hf800_0000;
    reset_cpu();
    pulse_run();
    wait (!halted);
    wait (halted);
    @(posedge clk);
    #1;
    if (!error || error_code !== 8'h03) $fatal(1, "Explicit TRAP error mismatch");
    if (debug_pc !== 0) $fatal(1, "Explicit TRAP PC mismatch");
    if (retired_count !== 0) $fatal(1, "TRAP was incorrectly retired");

    // A known opcode with nonzero reserved fields has a distinct error code.
    instruction_memory[0] = 32'h0000_0001;  // NOP with reserved bit 0 set.
    reset_cpu();
    pulse_run();
    wait (!halted);
    wait (halted);
    @(posedge clk);
    #1;
    if (!error || error_code !== 8'h05) $fatal(1, "Invalid encoding error mismatch");
    if (debug_pc !== 0) $fatal(1, "Invalid encoding PC mismatch");

    // A reserved opcode remains an invalid opcode, independently of encoding.
    instruction_memory[0] = 32'h6c00_0000;  // Reserved opcode 0x1b.
    reset_cpu();
    pulse_run();
    wait (!halted);
    wait (halted);
    @(posedge clk);
    #1;
    if (!error || error_code !== 8'h01) $fatal(1, "Invalid opcode error mismatch");
    if (debug_pc !== 0) $fatal(1, "Invalid opcode PC mismatch");

    $display("PASS: minimal CPU behavior is correct");
    $finish;
  end
endmodule

`default_nettype wire
