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

  reg [31:0] instruction_memory[0:15];
  integer retired_count = 0;

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
      imem_read_data <= instruction_memory[imem_address[5:2]];
    end

    if (reset) begin
      retired_count <= 0;
    end else if (instruction_retired) begin
      retired_count <= retired_count + 1;
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

    // An unimplemented opcode stops the CPU and records an error.
    instruction_memory[0] = 32'hf800_0000;  // TRAP is not implemented by the minimal CPU.
    reset_cpu();
    pulse_run();
    wait (!halted);
    wait (halted);
    @(posedge clk);
    #1;
    if (!error || error_code !== 8'h01) $fatal(1, "Invalid opcode error mismatch");
    if (retired_count !== 0) $fatal(1, "Invalid opcode was incorrectly retired");

    $display("PASS: minimal CPU behavior is correct");
    $finish;
  end
endmodule

`default_nettype wire
