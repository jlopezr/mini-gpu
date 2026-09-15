`timescale 1ns / 1ps
`default_nettype none

/*
 * SLT y SLTU: comparaciones materializadas. Capability `compare`,
 * 1.isa/isa.md §3 "Control de flujo" y 1.isa/abi.md §12.
 *
 * Las dos comparten la resta registrada de 33 bits que ya usaban los branches
 * --STATE_EXECUTE arma `branch_difference`/`branch_a_sign`/`branch_b_sign`--,
 * pero en vez de decidir `branch_taken` y saltar, STATE_SLT_WRITE convierte
 * esa misma resta en 0 o 1 y la deja en `alu_result`, que STATE_ALU_WRITE
 * escribe igual que para ADD/SUB/AND/OR/XOR.
 *
 * Lo que se comprueba aqui:
 *
 *   1. SLT es con signo y SLTU sin signo, y dan resultados DISTINTOS para el
 *      mismo par de operandos cuando uno es negativo: es el caso que
 *      descubriria un comparador que solo mirase `diff[31]` sin los signos de
 *      los operandos por separado.
 *   2. Los bordes de la resta sin signo: 0 < 0xFFFFFFFF (SLTU) y el caso
 *      simetrico que no debe tomarse.
 *   3. Los dos idiomas de R0 que documenta la ISA: `SLT Rd, Ra, R0` da el
 *      signo de `Ra`, y `SLTU Rd, R0, Ra` da `Ra != 0`.
 *   4. El campo reservado sigue siendo `extra[10:0]`, igual que ADD: cualquier
 *      bit puesto da ERROR_INVALID_ENCODING.
 *   5. Ninguna de las dos toca PC: tras un SLT/SLTU la siguiente instruccion
 *      es la que sigue en memoria, no un salto.
 */
module compare_tb;

  localparam [5:0] OPCODE_SLT = 6'h26;
  localparam [5:0] OPCODE_SLTU = 6'h27;
  localparam [5:0] OPCODE_MOVI = 6'h10;
  localparam [5:0] OPCODE_MOVHI = 6'h17;
  localparam [5:0] OPCODE_ORI = 6'h13;
  localparam [31:0] NOP = 32'h0000_0000;
  localparam [31:0] HALT = 32'hfc00_0000;

  localparam [7:0] ERROR_NONE = 8'h00;
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
  wire instruction_retired;
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

  always @(posedge clk) begin
    imem_ready <= imem_valid;
    if (imem_valid) imem_read_data <= instruction_memory[imem_address[7:2]];
  end

  function [31:0] r_type;
    input [5:0] op;
    input [4:0] rd;
    input [4:0] ra;
    input [4:0] rb;
    input [10:0] extra;
    begin
      r_type = {op, rd, ra, rb, extra};
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

  task check_register;
    input [8*40-1:0] what;
    input [4:0] address;
    input [31:0] expected;
    begin
      debug_register_address = address;
      repeat (3) @(posedge clk);
      #1;
      if (debug_register_data !== expected) begin
        $display("FAIL %0s: R%0d = %08x, esperado %08x",
                 what, address, debug_register_data, expected);
        failures = failures + 1;
      end
    end
  endtask

  /*
   * Un caso: carga `a` en R1 y `b` en R2, ejecuta SLT y SLTU con los mismos
   * operandos y compara los dos resultados por separado. Los dos opcodes se
   * prueban siempre juntos porque es exactamente donde divergen --el mismo
   * par de bits produce respuestas distintas segun el signo se tenga en
   * cuenta o no.
   */
  task compare_case;
    input [8*40-1:0] what;
    input [31:0] a;
    input [31:0] b;
    input expected_slt;
    input expected_sltu;
    begin
      clear_memory();
      instruction_memory[0] = i_type(OPCODE_MOVHI, 5'd1, 5'd0, a[31:16]);
      instruction_memory[1] = i_type(OPCODE_ORI, 5'd1, 5'd1, a[15:0]);
      instruction_memory[2] = i_type(OPCODE_MOVHI, 5'd2, 5'd0, b[31:16]);
      instruction_memory[3] = i_type(OPCODE_ORI, 5'd2, 5'd2, b[15:0]);
      instruction_memory[4] = r_type(OPCODE_SLT, 5'd3, 5'd1, 5'd2, 11'd0);
      instruction_memory[5] = r_type(OPCODE_SLTU, 5'd4, 5'd1, 5'd2, 11'd0);
      instruction_memory[6] = HALT;

      run_program();
      if (error) begin
        $display("FAIL %0s: error inesperado 0x%02x", what, error_code);
        failures = failures + 1;
      end
      check_register(what, 5'd3, {31'd0, expected_slt});
      check_register(what, 5'd4, {31'd0, expected_sltu});
      // Ni SLT ni SLTU tocan PC: se retiran como cualquier ALU R-Type. El
      // programa tiene 7 palabras (0x00..0x18, la ultima el HALT) y el fetch
      // adelanta PC antes de ejecutar, asi que el HALT retirado deja 0x1C.
      if (debug_pc !== 32'h0000_001C) begin
        $display("FAIL %0s: PC = %08x, esperado 0000001C (sin saltos)",
                 what, debug_pc);
        failures = failures + 1;
      end
    end
  endtask

  task expect_encoding_error;
    input [8*40-1:0] what;
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
      if (debug_pc !== 32'h0000_0000) begin
        $display("FAIL %0s: PC = %08x, esperado 00000000", what, debug_pc);
        failures = failures + 1;
      end
    end
  endtask

  task expect_no_error;
    input [8*40-1:0] what;
    input [31:0] instruction;
    begin
      clear_memory();
      instruction_memory[0] = instruction;
      instruction_memory[1] = HALT;
      run_program();
      if (error) begin
        $display("FAIL %0s: error 0x%02x inesperado", what, error_code);
        failures = failures + 1;
      end
    end
  endtask

  initial begin
    $dumpvars(0, compare_tb);

    // ---- El discriminante: positivo contra negativo ---------------------
    // a = 5, b = -1 (0xFFFFFFFF). Con signo, -1 < 5: SLT = 1. Sin signo,
    // 0xFFFFFFFF es el mayor de los dos: SLTU = 0. Un comparador que solo
    // mirara diff[31] sin los signos por separado daria el mismo bit a los dos.
    compare_case("5 vs -1", 32'd5, 32'hFFFF_FFFF, 1'b0, 1'b1);

    // El simetrico: a = -1, b = 5.
    compare_case("-1 vs 5", 32'hFFFF_FFFF, 32'd5, 1'b1, 1'b0);

    // ---- Iguales: ninguna de las dos toma la rama ------------------------
    compare_case("iguales", 32'h1234_5678, 32'h1234_5678, 1'b0, 1'b0);

    // ---- Bordes sin signo --------------------------------------------
    // 0 vs 0xFFFFFFFF: sin signo 0 es el menor de los dos (SLTU=1), pero con
    // signo 0xFFFFFFFF es -1 y 0 no es menor que -1 (SLT=0). Es la pareja que
    // demuestra por que no basta con `diff[31]` sin mirar los signos aparte.
    compare_case("0 vs 0xFFFFFFFF", 32'h0000_0000, 32'hFFFF_FFFF, 1'b0, 1'b1);
    compare_case("0xFFFFFFFF vs 0", 32'hFFFF_FFFF, 32'h0000_0000, 1'b1, 1'b0);

    // ---- El overflow classico de un SLT mal hecho --------------------
    // INT_MAX (0x7FFFFFFF) vs INT_MIN (0x80000000): la resta de 32 bits
    // desborda el rango signed, así que un comparador que solo mirara
    // `diff[31]` en vez de los signos de los operandos por separado vería
    // 0x7FFFFFFF - 0x80000000 = 0xFFFFFFFF, bit31 = 1, y diria SLT = 1. La
    // respuesta correcta es 0: INT_MAX no es menor que INT_MIN. Es el caso
    // que separa "restar y mirar el signo del resultado" de "comparar los
    // signos de los operandos", y ninguno de los pares de arriba lo cubre.
    compare_case("INT_MAX vs INT_MIN", 32'h7FFF_FFFF, 32'h8000_0000, 1'b0, 1'b1);
    compare_case("INT_MIN vs INT_MAX", 32'h8000_0000, 32'h7FFF_FFFF, 1'b1, 1'b0);

    // ---- Dos negativos: el signo no decide por si solo --------------------
    // -1 (0xFFFFFFFF) vs -2 (0xFFFFFFFE): con signo -2 < -1, SLT(a,b) = 0.
    // Sin signo 0xFFFFFFFF > 0xFFFFFFFE, SLTU(a,b) = 0 tambien: coinciden,
    // pero por razones opuestas, y hace falta el otro orden para separarlas.
    compare_case("-1 vs -2", 32'hFFFF_FFFF, 32'hFFFF_FFFE, 1'b0, 1'b0);
    compare_case("-2 vs -1", 32'hFFFF_FFFE, 32'hFFFF_FFFF, 1'b1, 1'b1);

    // ---- Los dos idiomas de R0 que documenta la ISA -----------------------
    // SLT Rd, Ra, R0 materializa el signo de Ra.
    clear_memory();
    instruction_memory[0] = i_type(OPCODE_MOVHI, 5'd1, 5'd0, 16'h8000);
    instruction_memory[1] = r_type(OPCODE_SLT, 5'd2, 5'd1, 5'd0, 11'd0);
    instruction_memory[2] = HALT;
    run_program();
    check_register("SLT Rd,Ra,R0 con Ra negativo", 5'd2, 32'd1);

    clear_memory();
    instruction_memory[0] = i_type(OPCODE_MOVI, 5'd1, 5'd0, 16'd7);
    instruction_memory[1] = r_type(OPCODE_SLT, 5'd2, 5'd1, 5'd0, 11'd0);
    instruction_memory[2] = HALT;
    run_program();
    check_register("SLT Rd,Ra,R0 con Ra positivo", 5'd2, 32'd0);

    // SLTU Rd, R0, Ra materializa Ra != 0.
    clear_memory();
    instruction_memory[0] = i_type(OPCODE_MOVI, 5'd1, 5'd0, 16'd0);
    instruction_memory[1] = r_type(OPCODE_SLTU, 5'd2, 5'd0, 5'd1, 11'd0);
    instruction_memory[2] = HALT;
    run_program();
    check_register("SLTU Rd,R0,Ra con Ra=0", 5'd2, 32'd0);

    clear_memory();
    instruction_memory[0] = i_type(OPCODE_MOVI, 5'd1, 5'd0, 16'd1);
    instruction_memory[1] = r_type(OPCODE_SLTU, 5'd2, 5'd0, 5'd1, 11'd0);
    instruction_memory[2] = HALT;
    run_program();
    check_register("SLTU Rd,R0,Ra con Ra!=0", 5'd2, 32'd1);

    // ---- Encoding: extra[10:0] a cero, igual que ADD ----------------------
    expect_no_error("SLT extra=0", r_type(OPCODE_SLT, 5'd1, 5'd2, 5'd3, 11'd0));
    expect_encoding_error("SLT extra[0]",
                          r_type(OPCODE_SLT, 5'd1, 5'd2, 5'd3, 11'd1));
    expect_encoding_error("SLTU extra[10]",
                          r_type(OPCODE_SLTU, 5'd1, 5'd2, 5'd3, 11'h400));

    if (failures != 0) $fatal(1, "compare_tb: %0d fallo(s)", failures);
    $display("compare_tb: OK");
    $finish;
  end
endmodule

`default_nettype wire
