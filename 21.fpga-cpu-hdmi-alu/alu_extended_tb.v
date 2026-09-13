`timescale 1ns / 1ps
`default_nettype none

/*
 * Las cuatro reservadas de la familia ALU: MULHI, DIVU, REM y REMU.
 *
 * Este testbench mide SOLO los operadores. Entre cada dos instrucciones
 * aritmeticas hay un NOP a proposito, que invalida la etiqueta del camino
 * rapido: aqui todo se calcula desde cero. El camino rapido tiene su propio
 * testbench, alu_fast_path_tb.v, y su contrato es precisamente que no cambia
 * ninguno de los numeros que se fijan aqui.
 *
 * MULHI ES CON SIGNO. La ISA no lo decia; la decision esta escrita en
 * 1.isa/isa.md §3 y razonada en docs/alu-extendida.md. El producto de 64 bits
 * que construye el RTL es el UNSIGNED, asi que la mitad alta signed necesita
 * una correccion --restar b si a es negativo y restar a si b lo es-- y no basta
 * con cablear los bits de arriba. Por eso la mitad de los vectores llevan
 * operandos negativos: si la correccion faltara, los positivos seguirian
 * pasando.
 *
 * El resto lleva el signo del DIVIDENDO, no el del cociente. Los cuatro cruces
 * de signo de 7 y 2 estan aqui por eso.
 */
module alu_extended_tb;

  localparam [5:0] OPCODE_MUL = 6'h0a;
  localparam [5:0] OPCODE_MULHI = 6'h0b;
  localparam [5:0] OPCODE_DIV = 6'h0c;
  localparam [5:0] OPCODE_DIVU = 6'h0d;
  localparam [5:0] OPCODE_REM = 6'h0e;
  localparam [5:0] OPCODE_REMU = 6'h0f;
  localparam [5:0] OPCODE_ORI = 6'h13;
  localparam [5:0] OPCODE_MOVHI = 6'h17;
  localparam [31:0] NOP = 32'h0000_0000;
  localparam [31:0] HALT = 32'hfc00_0000;

  localparam [7:0] ERROR_DIVISION_BY_ZERO = 8'h04;
  localparam [7:0] ERROR_INVALID_ENCODING = 8'h05;

  reg clk = 1'b0;
  reg reset = 1'b1;
  reg run_request = 1'b0;
  reg [4:0] debug_register_address = 5'd0;
  reg [31:0] imem_read_data = 32'h0000_0000;
  reg imem_ready = 1'b0;

  wire halted;
  wire error;
  wire [7:0] error_code;
  wire imem_valid;
  wire [31:0] imem_address;
  wire [31:0] debug_register_data;
  wire [31:0] debug_pc;

  reg [31:0] instruction_memory[0:63];
  integer failures = 0;
  integer index;

  always #5 clk = ~clk;

  cpu dut (
      .clk(clk),
      .reset(reset),
      .run_request(run_request),
      .halt_request(1'b0),
      .step_request(1'b0),
      .halted(halted),
      .error(error),
      .error_code(error_code),
      .instruction_retired(),
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

  always @(posedge clk) begin
    imem_ready <= imem_valid;
    if (imem_valid) imem_read_data <= instruction_memory[imem_address[7:2]];
  end

  function [31:0] r_type;
    input [5:0] op;
    input [4:0] rd;
    input [4:0] ra;
    input [4:0] rb;
    begin
      r_type = {op, rd, ra, rb, 11'd0};
    end
  endfunction

  function [31:0] i_type;
    input [5:0] op;
    input [4:0] x;
    input [4:0] y;
    input [15:0] imm;
    begin
      i_type = {op, x, y, imm};
    end
  endfunction

  task clear_memory;
    begin
      for (index = 0; index < 64; index = index + 1)
        instruction_memory[index] = HALT;
    end
  endtask

  // R1 = a, R2 = b. MOVHI + ORI porque MOVI solo alcanza un signed16.
  task load_operands;
    input [31:0] a;
    input [31:0] b;
    begin
      instruction_memory[0] = i_type(OPCODE_MOVHI, 5'd1, 5'd0, a[31:16]);
      instruction_memory[1] = i_type(OPCODE_ORI, 5'd1, 5'd1, a[15:0]);
      instruction_memory[2] = i_type(OPCODE_MOVHI, 5'd2, 5'd0, b[31:16]);
      instruction_memory[3] = i_type(OPCODE_ORI, 5'd2, 5'd2, b[15:0]);
    end
  endtask

  task reset_cpu;
    begin
      @(negedge clk);
      reset = 1'b1;
      repeat (2) @(negedge clk);
      reset = 1'b0;
      @(negedge clk);
    end
  endtask

  task run_program;
    begin
      reset_cpu();
      run_request = 1'b1;
      @(negedge clk);
      run_request = 1'b0;
      wait (!halted);
      wait (halted);
      @(posedge clk);
      #1;
    end
  endtask

  // El mensaje lleva los dos operandos porque, con veintidos vectores, saber
  // que fallo «MULHI» no sirve de nada sin saber con que.
  task check_result;
    input [8*8-1:0] what;
    input [31:0] a;
    input [31:0] b;
    input [4:0] address;
    input [31:0] expected;
    begin
      debug_register_address = address;
      repeat (3) @(posedge clk);
      #1;
      if (debug_register_data !== expected) begin
        $display("FAIL %0s(%08x, %08x) = %08x, esperado %08x",
                 what, a, b, debug_register_data, expected);
        failures = failures + 1;
      end
    end
  endtask

  /*
   * Un vector de multiplicacion: MUL y MULHI sobre los mismos operandos, con
   * un NOP enmedio. Se comprueban las dos mitades juntas porque juntas SON el
   * producto de 64 bits, y un error de acarreo entre ellas se ve mejor asi.
   */
  task mul_case;
    input [31:0] a;
    input [31:0] b;
    input [31:0] expected_high;
    input [31:0] expected_low;
    begin
      clear_memory();
      load_operands(a, b);
      instruction_memory[4] = r_type(OPCODE_MUL, 5'd3, 5'd1, 5'd2);
      instruction_memory[5] = NOP;
      instruction_memory[6] = r_type(OPCODE_MULHI, 5'd4, 5'd1, 5'd2);
      instruction_memory[7] = HALT;

      run_program();
      if (error) begin
        $display("FAIL MUL %08x*%08x: error 0x%02x", a, b, error_code);
        failures = failures + 1;
      end
      check_result("MUL", a, b, 5'd3, expected_low);
      check_result("MULHI", a, b, 5'd4, expected_high);
    end
  endtask

  /*
   * Un vector de division: las cuatro instrucciones sobre los mismos
   * operandos, separadas por NOP.
   */
  task div_case;
    input [31:0] a;
    input [31:0] b;
    input [31:0] expected_div;
    input [31:0] expected_divu;
    input [31:0] expected_rem;
    input [31:0] expected_remu;
    begin
      clear_memory();
      load_operands(a, b);
      instruction_memory[4] = r_type(OPCODE_DIV, 5'd3, 5'd1, 5'd2);
      instruction_memory[5] = NOP;
      instruction_memory[6] = r_type(OPCODE_DIVU, 5'd4, 5'd1, 5'd2);
      instruction_memory[7] = NOP;
      instruction_memory[8] = r_type(OPCODE_REM, 5'd5, 5'd1, 5'd2);
      instruction_memory[9] = NOP;
      instruction_memory[10] = r_type(OPCODE_REMU, 5'd6, 5'd1, 5'd2);
      instruction_memory[11] = HALT;

      run_program();
      if (error) begin
        $display("FAIL DIV %08x/%08x: error 0x%02x", a, b, error_code);
        failures = failures + 1;
      end
      check_result("DIV", a, b, 5'd3, expected_div);
      check_result("DIVU", a, b, 5'd4, expected_divu);
      check_result("REM", a, b, 5'd5, expected_rem);
      check_result("REMU", a, b, 5'd6, expected_remu);
    end
  endtask

  // Division por cero: las cuatro instrucciones paran igual, con el PC en la
  // instruccion culpable.
  task zero_divisor_case;
    input [8*48-1:0] what;
    input [5:0] op;
    begin
      clear_memory();
      load_operands(32'h0000_0007, 32'h0000_0000);
      instruction_memory[4] = r_type(op, 5'd3, 5'd1, 5'd2);
      instruction_memory[5] = HALT;

      run_program();
      if (!error || error_code !== ERROR_DIVISION_BY_ZERO) begin
        $display("FAIL %0s por cero: error=%0d codigo=0x%02x, esperado 0x04",
                 what, error, error_code);
        failures = failures + 1;
      end
      if (debug_pc !== 32'h0000_0010) begin
        $display("FAIL %0s por cero: PC = %08x, esperado 00000010",
                 what, debug_pc);
        failures = failures + 1;
      end
    end
  endtask

  task expect_encoding_error;
    input [8*48-1:0] what;
    input [31:0] instruction;
    begin
      clear_memory();
      instruction_memory[0] = instruction;
      run_program();
      if (!error || error_code !== ERROR_INVALID_ENCODING) begin
        $display("FAIL %0s: error=%0d codigo=0x%02x, esperado 0x05",
                 what, error, error_code);
        failures = failures + 1;
      end
    end
  endtask

  initial begin
    $dumpvars(0, alu_extended_tb);

    // ---- MUL / MULHI ----------------------------------------------------
    //                a           b           alto        bajo
    mul_case(32'h00010000, 32'h00010000, 32'h00000001, 32'h00000000);
    mul_case(32'hffffffff, 32'hffffffff, 32'h00000000, 32'h00000001);
    mul_case(32'hffffffff, 32'h00000001, 32'hffffffff, 32'hffffffff);
    mul_case(32'h7fffffff, 32'h7fffffff, 32'h3fffffff, 32'h00000001);
    mul_case(32'h80000000, 32'h80000000, 32'h40000000, 32'h00000000);
    mul_case(32'h80000000, 32'h00000002, 32'hffffffff, 32'h00000000);
    mul_case(32'hffff0000, 32'h00020000, 32'hfffffffe, 32'h00000000);
    mul_case(32'h00000003, 32'h00000005, 32'h00000000, 32'h0000000f);
    mul_case(32'h12345678, 32'h9abcdef0, 32'hf8cc93d6, 32'h242d2080);
    // Conmutado: el mismo par al reves debe dar lo mismo.
    mul_case(32'h9abcdef0, 32'h12345678, 32'hf8cc93d6, 32'h242d2080);
    mul_case(32'hffffffff, 32'h80000000, 32'h00000000, 32'h80000000);

    // ---- DIV / DIVU / REM / REMU ----------------------------------------
    //                a           b           DIV         DIVU        REM         REMU
    div_case(32'h00000007, 32'h00000002, 32'h00000003, 32'h00000003,
             32'h00000001, 32'h00000001);
    div_case(32'hfffffff9, 32'h00000002, 32'hfffffffd, 32'h7ffffffc,
             32'hffffffff, 32'h00000001);
    div_case(32'h00000007, 32'hfffffffe, 32'hfffffffd, 32'h00000000,
             32'h00000001, 32'h00000007);
    div_case(32'hfffffff9, 32'hfffffffe, 32'h00000003, 32'h00000000,
             32'hffffffff, 32'hfffffff9);
    div_case(32'h80000000, 32'h00000003, 32'hd5555556, 32'h2aaaaaaa,
             32'hfffffffe, 32'h00000002);
    // El desbordamiento clasico: -2^31 / -1 no cabe en signed32 y hace wrap.
    div_case(32'h80000000, 32'hffffffff, 32'h80000000, 32'h00000000,
             32'h00000000, 32'h80000000);
    div_case(32'hffffffff, 32'h00000002, 32'h00000000, 32'h7fffffff,
             32'hffffffff, 32'h00000001);
    div_case(32'h00000001, 32'hffffffff, 32'hffffffff, 32'h00000000,
             32'h00000000, 32'h00000001);
    div_case(32'h00000000, 32'h00000005, 32'h00000000, 32'h00000000,
             32'h00000000, 32'h00000000);
    div_case(32'h00000005, 32'h00000007, 32'h00000000, 32'h00000000,
             32'h00000005, 32'h00000005);
    div_case(32'h7fffffff, 32'h7fffffff, 32'h00000001, 32'h00000001,
             32'h00000000, 32'h00000000);

    // ---- Division por cero ----------------------------------------------
    zero_divisor_case("DIV", OPCODE_DIV);
    zero_divisor_case("DIVU", OPCODE_DIVU);
    zero_divisor_case("REM", OPCODE_REM);
    zero_divisor_case("REMU", OPCODE_REMU);

    // ---- Encoding: los cuatro opcodes nuevos exigen extra = 0 ------------
    expect_encoding_error("MULHI extra",
                          {OPCODE_MULHI, 5'd1, 5'd2, 5'd3, 11'd1});
    expect_encoding_error("DIVU extra",
                          {OPCODE_DIVU, 5'd1, 5'd2, 5'd3, 11'h400});
    expect_encoding_error("REM extra",
                          {OPCODE_REM, 5'd1, 5'd2, 5'd3, 11'h7ff});
    expect_encoding_error("REMU extra",
                          {OPCODE_REMU, 5'd1, 5'd2, 5'd3, 11'd2});

    if (failures != 0) $fatal(1, "alu_extended_tb: %0d fallo(s)", failures);
    $display("alu_extended_tb: OK");
    $finish;
  end
endmodule

`default_nettype wire
