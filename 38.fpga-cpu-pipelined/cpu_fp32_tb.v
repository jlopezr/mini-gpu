`timescale 1ns / 1ps
`default_nettype none

// FP32 forwarding, cancellation, encoding, R0 and precise retirement.
module cpu_fp32_tb;

  reg clk = 1'b0;
  reg reset = 1'b1;
  reg run_request = 1'b0;
  reg halt_request = 1'b0;
  reg step_request = 1'b0;
  reg [31:0] dmem_read_data = 32'h40000000;
  reg dmem_rvalid = 0;
  wire dmem_valid;
  integer response_delay = 0;
  wire fp_retired;
  integer fp_count = 0;
  reg [4:0] debug_register_address = 5'd0;
  reg [31:0] imem_read_data = 32'h0000_0000;
  reg imem_rvalid = 1'b0;

  wire halted;
  wire error;
  wire [7:0] error_code;
  wire instruction_retired;
  wire imem_valid;
  wire [31:0] imem_address;
  wire [31:0] debug_register_data;
  wire [31:0] debug_pc;

  localparam integer WORDS = 64;
  reg [31:0] instruction_memory[0:WORDS-1];
  integer cycles = 0;
  integer k, n, errors, pc;

  always #5 clk = ~clk;

  cpu dut (
      .clk(clk),
      .reset(reset),
      .soft_reset(1'b0),
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
      .imem_ready(1'b1),
      .imem_rvalid(imem_rvalid),
      .dmem_valid(dmem_valid),
      .dmem_address(),
      .dmem_write_data(),
      .dmem_write_enable(),
      .dmem_read_data(dmem_read_data),
      .dmem_ready(1'b1),
      .dmem_rvalid(dmem_rvalid),
      .dmem_error(1'b0),
      .dmem_waiting(),
      .debug_register_address(debug_register_address),
      .debug_register_data(debug_register_data),
      .debug_pc(debug_pc),
      .perf_stall(), .perf_muldiv_retired(fp_retired),
      // Sin D-cache: cada LOAD pide en MEM.
      .dcache_lookup_address(), .dcache_hit(1'b0), .dcache_read_data(32'd0),
      .dcache_mem_advance(), .dcache_ex_load(), .dcache_ex_store(),
      .dcache_ex_write_data(), .dcache_ex_write_enable()
  );

  // Deliberately delayed LOAD response, to hold the FP consumer in EX.
  always @(posedge clk) begin
    dmem_rvalid <= 0;
    if (reset) begin response_delay <= 0; fp_count <= 0; end
    else begin
      if (dmem_valid) response_delay <= 6;
      else if (response_delay != 0) begin
        response_delay <= response_delay - 1;
        if (response_delay == 1) dmem_rvalid <= 1;
      end
      if (fp_retired) fp_count <= fp_count + 1;
    end
  end

  // Acierto de instruction_buffer: una peticion por ciclo, respuesta al siguiente.
  always @(posedge clk) begin
    imem_rvalid <= imem_valid;
    if (imem_valid) imem_read_data <= instruction_memory[imem_address[7:2]];
    if (!halted) cycles <= cycles + 1;
  end

  // ---------------------------------------------------------------- codificacion
  localparam [5:0] OP_MULFX = 6'h03, OP_ADD = 6'h01, OP_MUL = 6'h0a, OP_MULHI = 6'h0b,
                   OP_DIV = 6'h0c, OP_DIVU = 6'h0d, OP_REM = 6'h0e, OP_REMU = 6'h0f;
  localparam [31:0] HALT = 32'hfc00_0000;
  localparam [31:0] NOP = 32'h0000_0000;

  function [31:0] rtype(input [5:0] op, input [4:0] rd, input [4:0] ra, input [4:0] rb);
    rtype = {op, rd, ra, rb, 11'd0};
  endfunction
  function [31:0] movhi(input [4:0] rd, input [15:0] imm);
    movhi = {6'h17, rd, 5'd0, imm};
  endfunction
  function [31:0] ori(input [4:0] rd, input [4:0] ra, input [15:0] imm);
    ori = {6'h13, rd, ra, imm};
  endfunction
  function [31:0] addi(input [4:0] rd, input [4:0] ra, input [15:0] imm);
    addi = {6'h11, rd, ra, imm};
  endfunction

  // ------------------------------------------------------------------ referencia
  function [63:0] smul(input [31:0] a, input [31:0] b);
    smul = {{32{a[31]}}, a} * {{32{b[31]}}, b};
  endfunction
  function [31:0] ref_div(input [31:0] a, input [31:0] b);
    if (a == 32'h8000_0000 && b == 32'hffff_ffff) ref_div = 32'h8000_0000;
    else ref_div = $signed(a) / $signed(b);
  endfunction
  function [31:0] ref_rem(input [31:0] a, input [31:0] b);
    if (a == 32'h8000_0000 && b == 32'hffff_ffff) ref_rem = 32'd0;
    else ref_rem = $signed(a) % $signed(b);
  endfunction

  // ---------------------------------------------------------------------- tareas
  task clear_memory;
    begin
      for (k = 0; k < WORDS; k = k + 1) instruction_memory[k] = HALT;
      pc = 0;
    end
  endtask

  task emit(input [31:0] word);
    begin
      instruction_memory[pc] = word;
      pc = pc + 1;
    end
  endtask

  task load_constant(input [4:0] rd, input [31:0] value);
    begin
      emit(movhi(rd, value[31:16]));
      emit(ori(rd, rd, value[15:0]));
    end
  endtask

  task reset_and_run;
    begin
      @(negedge clk);
      reset = 1'b1;
      repeat (2) @(negedge clk);
      reset = 1'b0;
      wait (!dut.register_file_busy);
      @(negedge clk);
      cycles = 0;
      run_request = 1'b1;
      @(negedge clk);
      run_request = 1'b0;
      wait (!halted);
    end
  endtask

  task wait_halt;
    begin
      wait (halted);
      @(posedge clk);
      #1;
    end
  endtask

  // Corre el programa y espera que pare sin error.
  task run_ok(input [8*16-1:0] name);
    begin
      reset_and_run();
      wait_halt();
      if (error) $fatal(1, "%0s: error %02x en pc %08x", name, error_code, debug_pc);
    end
  endtask

  task expect_register(input [8*16-1:0] name, input [4:0] address, input [31:0] expected);
    begin
      debug_register_address = address;
      repeat (2) @(posedge clk);  // the debug read port is registered
      #1;
      if (debug_register_data !== expected) begin
        $display("%0s: R%0d = %08x, se esperaba %08x", name, address,
                 debug_register_data, expected);
        errors = errors + 1;
      end
    end
  endtask


  initial begin
    #1000000;
    $fatal(1, "FP32 CPU timeout");
  end

  initial begin
    errors = 0;
    clear_memory();
    load_constant(1, 32'h3fc00000); // 1.5
    load_constant(2, 32'h40100000); // 2.25, immediately forwarded to FADD
    emit(rtype(6'h38, 3, 1, 2));   // 3.75
    emit(rtype(6'h39, 4, 3, 1));   // 2.25, FP -> FP
    emit(rtype(6'h3a, 5, 4, 1));   // 3.375
    emit(rtype(6'h3b, 6, 5, 1));   // 2.25
    emit(rtype(OP_ADD, 7, 6, 0));  // FP -> integer
    emit(rtype(6'h3b, 0, 1, 0));   // infinity discarded by R0; no integer fault
    emit(rtype(6'h3b, 8, 0, 0));   // 0/0 = canonical NaN
    emit(rtype(6'h38, 1, 1, 1));   // rd == ra == rb
    run_ok("FP chain");
    expect_register("FADD", 3, 32'h40700000);
    expect_register("FSUB", 4, 32'h40100000);
    expect_register("FMUL", 5, 32'h40580000);
    expect_register("FDIV", 6, 32'h40100000);
    expect_register("FP -> int", 7, 32'h40100000);
    expect_register("R0", 0, 0);
    expect_register("NaN", 8, 32'h7fc00000);
    expect_register("alias", 1, 32'h40400000);

    if (fp_count != 7) $fatal(1, "FP retired count %0d, expected 7", fp_count);

    clear_memory();
    emit({6'h15, 5'd1, 5'd0, 16'd1024}); // LOAD R1, R0, 1024 -> 2.0
    emit(rtype(6'h38, 2, 1, 1));         // held until MEM returns
    run_ok("LOAD -> FP");
    expect_register("LOAD consumer", 2, 32'h40800000);

    // Invalid reserved bits must fault at this instruction, before writing rd.
    for (n = 0; n < 4; n = n + 1) begin
      clear_memory();
      load_constant(3, 32'h12345678);
      emit(rtype(6'h38 + n, 3, 0, 0) | 1);
      emit(addi(4, 0, 99));
      reset_and_run(); wait_halt();
      if (!error || error_code != 5 || debug_pc != 8)
        $fatal(1, "FP invalid encoding: error=%b code=%d pc=%h", error, error_code, debug_pc);
      expect_register("precise rd", 3, 32'h12345678);
      expect_register("younger", 4, 0);
    end

    // FEQ/FLT/FLE (ALU), FTOI/ITOF (FP unit) and EXT MIN/MAX/MINU/MAXU/CLZ,
    // with forwarding between them. Expected values match tools/fp32.py.
    clear_memory();
    load_constant(1, 32'h3fc00000);                     // 1.5
    load_constant(2, 32'hc0100000);                     // -2.25
    load_constant(9, 32'h7fc00000);                     // NaN
    emit(rtype(6'h3c, 3, 2, 1) | 1);                    // FLT -2.25 < 1.5 = 1
    emit(rtype(6'h3c, 4, 1, 2) | 2);                    // FLE 1.5 <= -2.25 = 0
    emit(rtype(6'h3c, 5, 9, 9));                        // FEQ NaN = 0
    emit(rtype(6'h3d, 6, 1, 0) | 16);                   // FTOI 1.5, 16 = 0x18000
    emit(rtype(6'h3d, 7, 6, 0) | 32'h30);               // ITOF 0x18000, 16 = 1.5 (FP -> FP)
    emit(rtype(6'h3c, 8, 7, 1));                        // FEQ: 1
    emit(rtype(6'h3d, 10, 2, 0));                       // FTOI -2.25 = -2
    emit(rtype(6'h1e, 11, 10, 3));                      // MIN(-2, 1) = -2
    emit(rtype(6'h1e, 12, 10, 3) | 1);                  // MAX = 1
    emit(rtype(6'h1e, 13, 10, 3) | 2);                  // MINU = 1
    emit(rtype(6'h1e, 14, 10, 3) | 3);                  // MAXU = 0xfffffffe
    emit(rtype(6'h1e, 15, 6, 0) | 9);                   // CLZ 0x18000 = 15
    emit(rtype(6'h1e, 16, 0, 0) | 9);                   // CLZ 0 = 32
    emit(rtype(6'h3d, 17, 15, 0) | 32'h20);             // ITOF 15 = 15.0 (ALU -> FP)
    run_ok("cmp/cvt/ext");
    expect_register("FLT", 3, 1);
    expect_register("FLE", 4, 0);
    expect_register("FEQ NaN", 5, 0);
    expect_register("FTOI Q16", 6, 32'h00018000);
    expect_register("ITOF Q16", 7, 32'h3fc00000);
    expect_register("FEQ", 8, 1);
    expect_register("FTOI", 10, 32'hfffffffe);
    expect_register("MIN", 11, 32'hfffffffe);
    expect_register("MAX", 12, 1);
    expect_register("MINU", 13, 1);
    expect_register("MAXU", 14, 32'hfffffffe);
    expect_register("CLZ", 15, 15);
    expect_register("CLZ 0", 16, 32);
    expect_register("ITOF", 17, 32'h41700000);

    // Reserved selectors and functions: invalid opcode (1); reserved fields:
    // invalid encoding (5). Both before writing rd.
    for (n = 0; n < 6; n = n + 1) begin
      clear_memory();
      load_constant(3, 32'h12345678);
      case (n)
        0: emit(rtype(6'h3c, 3, 0, 0) | 3);          // FCMP selector 3
        1: emit(rtype(6'h3d, 3, 0, 0) | 32'h40);     // FCVT conversion 2
        2: emit(rtype(6'h1e, 3, 0, 0) | 4);          // EXT function 4 (not implemented)
        3: emit(rtype(6'h3c, 3, 0, 0) | 4);          // FCMP extra[2]
        4: emit(rtype(6'h3d, 3, 0, 1));              // FCVT Rb != 0
        default: emit(rtype(6'h1e, 3, 0, 1) | 9);    // CLZ Rb != 0
      endcase
      emit(addi(4, 0, 99));
      reset_and_run(); wait_halt();
      if (!error || error_code != (n < 3 ? 1 : 5) || debug_pc != 8)
        $fatal(1, "cmp/cvt/ext reserved %0d: error=%b code=%d pc=%h", n, error, error_code, debug_pc);
      expect_register("precise rd", 3, 32'h12345678);
      expect_register("younger", 4, 0);
    end

    // HALT from the monitor cancels an in-flight divide; RUN restarts it.
    clear_memory();
    load_constant(1, 32'h40c00000);
    load_constant(2, 32'h40000000);
    emit(rtype(6'h3b, 3, 1, 2));
    emit(rtype(6'h38, 4, 3, 2));
    reset_and_run();
    wait (dut.fp32_unit.divisor_busy);
    @(negedge clk); halt_request = 1;
    @(negedge clk); halt_request = 0;
    wait_halt();
    expect_register("cancelled", 3, 0);
    repeat (40) @(negedge clk);
    run_request = 1;
    @(negedge clk); run_request = 0;
    wait (!halted); wait_halt();
    if (error) $fatal(1, "FP resume error");
    expect_register("resume", 3, 32'h40400000);
    expect_register("no stale result", 4, 32'h40a00000);
    // STEP retires exactly one FP instruction, cancelling the younger one.
    clear_memory();
    emit(rtype(6'h38, 1, 0, 0));
    emit(addi(2, 0, 99));
    @(negedge clk); reset = 1;
    repeat (2) @(negedge clk);
    reset = 0;
    wait (!dut.register_file_busy);
    @(negedge clk); step_request = 1;
    @(negedge clk); step_request = 0;
    wait (!halted); wait_halt();
    if (error || debug_pc != 4) $fatal(1, "FP STEP failed pc=%h", debug_pc);
    expect_register("STEP younger", 2, 0);
    if (fp_count != 1) $fatal(1, "STEP FP retire count=%d", fp_count);
    if (errors != 0) $fatal(1, "FP CPU: %0d errors", errors);
    $display("PASS: cpu_fp32"); $finish;
  end
endmodule
`default_nettype wire
