`timescale 1ns / 1ps
`default_nettype none

/*
 * Camino rapido de MULHI, REM y REMU: el medio resultado que la CPU ya tiene.
 *
 * ==========================================================================
 * Como esta montado este testbench, que es lo unico interesante de el
 * ==========================================================================
 *
 * Hay DOS CPUs, no una: `fast` con ALU_FAST_PATH a uno y `slow` con
 * ALU_FAST_PATH a cero. Las dos ejecutan el mismo programa desde su propia
 * memoria de instrucciones y al final se comparan los TREINTA Y DOS registros,
 * el PC y el estado de error.
 *
 * Esta montado asi porque el riesgo de esta optimizacion no es que rompa algo
 * ruidosamente: es que un acierto indebido devuelva un numero plausible y
 * equivocado solo en ciertas secuencias. Comparar contra una tabla de valores
 * esperados solo encuentra lo que a uno se le ocurrio tabular; comparar contra
 * la misma CPU con el atajo desarmado encuentra cualquier diferencia, la haya
 * previsto o no. El contrato es literal: «no debe cambiar ni un resultado,
 * solo los ciclos», y eso es exactamente lo que se comprueba.
 *
 * Los ciclos tambien se comprueban, y en los dos sentidos:
 *
 *   - En las secuencias de ACIERTO, `fast` tiene que tardar MENOS. Sin esto,
 *     un camino rapido que no se activara nunca pasaria el testbench entero.
 *   - En las secuencias de FALLO, tiene que tardar EXACTAMENTE lo mismo. Es la
 *     forma de ver que el atajo no se cuela donde no debe, incluso cuando por
 *     casualidad el numero saliera bien.
 *
 * Las secuencias de fallo son el grueso de la lista: operandos distintos,
 * instruccion intercalada, tipo cruzado, `rd` pisando a `ra` o a `rb`, MULFX
 * --que multiplica magnitudes y por eso no puede armar-- y arranque en frio.
 */
module alu_fast_path_tb;

  localparam [5:0] OPCODE_NOP = 6'h00;
  localparam [5:0] OPCODE_ADD = 6'h01;
  localparam [5:0] OPCODE_MULFX = 6'h03;
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

  reg clk = 1'b0;
  reg reset = 1'b1;
  reg run_request = 1'b0;
  reg [4:0] debug_register_address = 5'd0;

  reg [31:0] instruction_memory[0:63];
  integer failures = 0;
  integer index;

  always #5 clk = ~clk;

  // --- CPU con el camino rapido armado ---------------------------------
  reg [31:0] fast_imem_data = 32'h0000_0000;
  reg fast_imem_ready = 1'b0;
  wire fast_halted, fast_error, fast_imem_valid;
  wire [7:0] fast_error_code;
  wire [31:0] fast_imem_address, fast_debug_data, fast_pc;

  cpu #(.ALU_FAST_PATH(1'b1)) fast (
      .clk(clk), .reset(reset),
      .run_request(run_request), .halt_request(1'b0), .step_request(1'b0),
      .halted(fast_halted), .error(fast_error), .error_code(fast_error_code),
      .instruction_retired(),
      .imem_valid(fast_imem_valid), .imem_address(fast_imem_address),
      .imem_read_data(fast_imem_data), .imem_ready(fast_imem_ready),
      .dmem_valid(), .dmem_address(), .dmem_write_data(), .dmem_write_enable(),
      .dmem_read_data(32'h0000_0000), .dmem_ready(1'b0), .dmem_error(1'b0),
      .debug_register_address(debug_register_address),
      .debug_register_data(fast_debug_data), .debug_pc(fast_pc)
  );

  // --- La misma CPU con el camino rapido desarmado ----------------------
  reg [31:0] slow_imem_data = 32'h0000_0000;
  reg slow_imem_ready = 1'b0;
  wire slow_halted, slow_error, slow_imem_valid;
  wire [7:0] slow_error_code;
  wire [31:0] slow_imem_address, slow_debug_data, slow_pc;

  cpu #(.ALU_FAST_PATH(1'b0)) slow (
      .clk(clk), .reset(reset),
      .run_request(run_request), .halt_request(1'b0), .step_request(1'b0),
      .halted(slow_halted), .error(slow_error), .error_code(slow_error_code),
      .instruction_retired(),
      .imem_valid(slow_imem_valid), .imem_address(slow_imem_address),
      .imem_read_data(slow_imem_data), .imem_ready(slow_imem_ready),
      .dmem_valid(), .dmem_address(), .dmem_write_data(), .dmem_write_enable(),
      .dmem_read_data(32'h0000_0000), .dmem_ready(1'b0), .dmem_error(1'b0),
      .debug_register_address(debug_register_address),
      .debug_register_data(slow_debug_data), .debug_pc(slow_pc)
  );

  // Cada CPU lee de su propia copia: no van en paralelo, que es el objetivo.
  always @(posedge clk) begin
    fast_imem_ready <= fast_imem_valid;
    if (fast_imem_valid)
      fast_imem_data <= instruction_memory[fast_imem_address[7:2]];
    slow_imem_ready <= slow_imem_valid;
    if (slow_imem_valid)
      slow_imem_data <= instruction_memory[slow_imem_address[7:2]];
  end

  // Ciclos de cada CPU desde que arranca hasta que se para.
  integer fast_cycles = 0;
  integer slow_cycles = 0;
  always @(posedge clk) begin
    if (reset) begin
      fast_cycles <= 0;
      slow_cycles <= 0;
    end else begin
      if (!fast_halted) fast_cycles <= fast_cycles + 1;
      if (!slow_halted) slow_cycles <= slow_cycles + 1;
    end
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

  // R1 = a, R2 = b, R5 = un tercer valor con el que romper la coincidencia.
  task load_operands;
    input [31:0] a;
    input [31:0] b;
    begin
      instruction_memory[0] = i_type(OPCODE_MOVHI, 5'd1, 5'd0, a[31:16]);
      instruction_memory[1] = i_type(OPCODE_ORI, 5'd1, 5'd1, a[15:0]);
      instruction_memory[2] = i_type(OPCODE_MOVHI, 5'd2, 5'd0, b[31:16]);
      instruction_memory[3] = i_type(OPCODE_ORI, 5'd2, 5'd2, b[15:0]);
      instruction_memory[4] = i_type(OPCODE_ORI, 5'd5, 5'd0, 16'd3);
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

  /*
   * Ejecuta el programa cargado en las dos CPUs, compara todo el estado
   * arquitectonico y contrasta los ciclos con lo que se esperaba del atajo.
   *
   * `expect_faster` = 1 exige que el atajo se haya activado; 0 exige que no.
   */
  task compare_run;
    input [8*32-1:0] what;
    input expect_faster;
    begin
      reset_cpu();
      run_request = 1'b1;
      @(negedge clk);
      run_request = 1'b0;
      wait (!fast_halted || !slow_halted);
      wait (fast_halted && slow_halted);
      @(posedge clk);
      #1;

      if (fast_error !== slow_error || fast_error_code !== slow_error_code) begin
        $display("FAIL %0s: error fast=%0d/0x%02x slow=%0d/0x%02x",
                 what, fast_error, fast_error_code,
                 slow_error, slow_error_code);
        failures = failures + 1;
      end
      if (fast_pc !== slow_pc) begin
        $display("FAIL %0s: PC fast=%08x slow=%08x", what, fast_pc, slow_pc);
        failures = failures + 1;
      end

      for (index = 0; index < 32; index = index + 1) begin
        debug_register_address = index[4:0];
        repeat (3) @(posedge clk);
        #1;
        if (fast_debug_data !== slow_debug_data) begin
          $display("FAIL %0s: R%0d fast=%08x slow=%08x",
                   what, index, fast_debug_data, slow_debug_data);
          failures = failures + 1;
        end
      end

      if (expect_faster) begin
        if (fast_cycles >= slow_cycles) begin
          $display("FAIL %0s: el atajo no se activo (fast=%0d, slow=%0d)",
                   what, fast_cycles, slow_cycles);
          failures = failures + 1;
        end else begin
          $display("  %0s: acierto, %0d ciclos frente a %0d",
                   what, fast_cycles, slow_cycles);
        end
      end else begin
        if (fast_cycles !== slow_cycles) begin
          $display("FAIL %0s: el atajo se colo (fast=%0d, slow=%0d)",
                   what, fast_cycles, slow_cycles);
          failures = failures + 1;
        end
      end
    end
  endtask

  /*
   * Una secuencia de dos instrucciones: la que arma la etiqueta y la que
   * pregunta por ella. `filler` se mete enmedio si no es HALT.
   */
  task sequence_case;
    input [8*32-1:0] what;
    input [31:0] a;
    input [31:0] b;
    input [31:0] first;
    input [31:0] filler;
    input [31:0] second;
    input expect_faster;
    begin
      clear_memory();
      load_operands(a, b);
      instruction_memory[5] = first;
      if (filler === HALT) begin
        instruction_memory[6] = second;
        instruction_memory[7] = HALT;
      end else begin
        instruction_memory[6] = filler;
        instruction_memory[7] = second;
        instruction_memory[8] = HALT;
      end
      compare_run(what, expect_faster);
    end
  endtask

  initial begin
    $dumpvars(0, alu_fast_path_tb);

    // =====================================================================
    // ACIERTOS: la instruccion inmediatamente anterior es la que toca
    // =====================================================================

    // MULHI detras de su MUL. Operandos negativos para que la correccion de
    // signo tenga que aplicarse tambien por el camino corto.
    sequence_case("MULHI tras MUL", 32'h12345678, 32'h9abcdef0,
                  r_type(OPCODE_MUL, 5'd3, 5'd1, 5'd2), HALT,
                  r_type(OPCODE_MULHI, 5'd4, 5'd1, 5'd2), 1'b1);

    // REM detras de su DIV: el premio gordo, 32 ciclos de division.
    sequence_case("REM tras DIV", 32'hfffffff9, 32'h00000002,
                  r_type(OPCODE_DIV, 5'd3, 5'd1, 5'd2), HALT,
                  r_type(OPCODE_REM, 5'd4, 5'd1, 5'd2), 1'b1);

    // REMU detras de su DIVU.
    sequence_case("REMU tras DIVU", 32'hfffffff9, 32'h00000002,
                  r_type(OPCODE_DIVU, 5'd3, 5'd1, 5'd2), HALT,
                  r_type(OPCODE_REMU, 5'd4, 5'd1, 5'd2), 1'b1);

    // =====================================================================
    // FALLOS. Cada uno es una forma distinta de que la etiqueta mintiera.
    // =====================================================================

    // Instruccion intercalada. La condicion es «la inmediatamente anterior»,
    // no «alguna en algun momento».
    sequence_case("REM con NOP enmedio", 32'hfffffff9, 32'h00000002,
                  r_type(OPCODE_DIV, 5'd3, 5'd1, 5'd2), NOP,
                  r_type(OPCODE_REM, 5'd4, 5'd1, 5'd2), 1'b0);
    sequence_case("MULHI con NOP enmedio", 32'h12345678, 32'h9abcdef0,
                  r_type(OPCODE_MUL, 5'd3, 5'd1, 5'd2), NOP,
                  r_type(OPCODE_MULHI, 5'd4, 5'd1, 5'd2), 1'b0);

    // Operandos distintos: R5 en lugar de R2.
    sequence_case("REM con otro Rb", 32'hfffffff9, 32'h00000002,
                  r_type(OPCODE_DIV, 5'd3, 5'd1, 5'd2), HALT,
                  r_type(OPCODE_REM, 5'd4, 5'd1, 5'd5), 1'b0);
    sequence_case("MULHI con otro Ra", 32'h12345678, 32'h9abcdef0,
                  r_type(OPCODE_MUL, 5'd3, 5'd1, 5'd2), HALT,
                  r_type(OPCODE_MULHI, 5'd4, 5'd5, 5'd2), 1'b0);

    // Tipo cruzado: REM detras de un MUL de los mismos numeros.
    sequence_case("REM tras MUL", 32'hfffffff9, 32'h00000002,
                  r_type(OPCODE_MUL, 5'd3, 5'd1, 5'd2), HALT,
                  r_type(OPCODE_REM, 5'd4, 5'd1, 5'd2), 1'b0);
    // Tipo cruzado: MULHI detras de un DIV.
    sequence_case("MULHI tras DIV", 32'hfffffff9, 32'h00000002,
                  r_type(OPCODE_DIV, 5'd3, 5'd1, 5'd2), HALT,
                  r_type(OPCODE_MULHI, 5'd4, 5'd1, 5'd2), 1'b0);
    /*
     * Signo cruzado, que es el mas sutil de los tres: DIV trabaja sobre
     * magnitudes y DIVU sobre los operandos crudos, asi que con un dividendo
     * negativo el resto que dejan es distinto. Si TAG_DIV y TAG_DIVU fuesen
     * el mismo tipo, este caso daria un numero plausible y equivocado.
     */
    sequence_case("REMU tras DIV signed", 32'hfffffff9, 32'h00000002,
                  r_type(OPCODE_DIV, 5'd3, 5'd1, 5'd2), HALT,
                  r_type(OPCODE_REMU, 5'd4, 5'd1, 5'd2), 1'b0);
    sequence_case("REM tras DIVU", 32'hfffffff9, 32'h00000002,
                  r_type(OPCODE_DIVU, 5'd3, 5'd1, 5'd2), HALT,
                  r_type(OPCODE_REM, 5'd4, 5'd1, 5'd2), 1'b0);

    /*
     * MULFX no arma. Multiplica MAGNITUDES --niega los operandos negativos
     * antes de entrar al multiplicador-- asi que el producto de 64 bits que
     * deja no es el de `a * b` sin signo, y un MULHI que se lo creyera daria
     * el valor absoluto del alto.
     */
    sequence_case("MULHI tras MULFX", 32'h12345678, 32'h9abcdef0,
                  r_type(OPCODE_MULFX, 5'd3, 5'd1, 5'd2), HALT,
                  r_type(OPCODE_MULHI, 5'd4, 5'd1, 5'd2), 1'b0);

    /*
     * `rd` pisa una fuente. La operacion destruye su propio operando, asi que
     * los numeros de registro siguen coincidiendo pero los VALORES ya no. Es
     * el unico caso en el que la comparacion de 5 bits no basta por si sola,
     * y por eso la condicion de armado lo excluye a mano.
     */
    sequence_case("REM tras DIV con rd==ra", 32'hfffffff9, 32'h00000002,
                  r_type(OPCODE_DIV, 5'd1, 5'd1, 5'd2), HALT,
                  r_type(OPCODE_REM, 5'd4, 5'd1, 5'd2), 1'b0);
    sequence_case("REM tras DIV con rd==rb", 32'hfffffff9, 32'h00000002,
                  r_type(OPCODE_DIV, 5'd2, 5'd1, 5'd2), HALT,
                  r_type(OPCODE_REM, 5'd4, 5'd1, 5'd2), 1'b0);
    sequence_case("MULHI tras MUL con rd==ra", 32'h12345678, 32'h9abcdef0,
                  r_type(OPCODE_MUL, 5'd1, 5'd1, 5'd2), HALT,
                  r_type(OPCODE_MULHI, 5'd4, 5'd1, 5'd2), 1'b0);
    sequence_case("MULHI tras MUL con rd==rb", 32'h12345678, 32'h9abcdef0,
                  r_type(OPCODE_MUL, 5'd2, 5'd1, 5'd2), HALT,
                  r_type(OPCODE_MULHI, 5'd4, 5'd1, 5'd2), 1'b0);

    // Arranque en frio: MULHI y REM sin nada delante que pudiera armar.
    sequence_case("MULHI en frio", 32'h12345678, 32'h9abcdef0,
                  NOP, HALT,
                  r_type(OPCODE_MULHI, 5'd4, 5'd1, 5'd2), 1'b0);
    sequence_case("REM en frio", 32'hfffffff9, 32'h00000002,
                  NOP, HALT,
                  r_type(OPCODE_REM, 5'd4, 5'd1, 5'd2), 1'b0);

    /*
     * Una division por cero no deja etiqueta. La CPU para con error, asi que
     * lo que se compara es que las dos paren igual: si el armado estuviera en
     * STATE_EXECUTE en vez de en STATE_MUL_WRITE, la etiqueta quedaria puesta
     * por una operacion que nunca produjo resto.
     */
    clear_memory();
    load_operands(32'h0000_0007, 32'h0000_0000);
    instruction_memory[5] = r_type(OPCODE_DIV, 5'd3, 5'd1, 5'd2);
    instruction_memory[6] = r_type(OPCODE_REM, 5'd4, 5'd1, 5'd2);
    instruction_memory[7] = HALT;
    compare_run("DIV por cero", 1'b0);

    /*
     * Una cadena larga, con aciertos y fallos mezclados y resultados que se
     * alimentan unos a otros. Aqui no se predice nada a mano: lo unico que se
     * afirma es que las dos CPUs acaban con los mismos 32 registros.
     */
    clear_memory();
    load_operands(32'hfedcba98, 32'h00000123);
    instruction_memory[5] = r_type(OPCODE_MUL, 5'd3, 5'd1, 5'd2);
    instruction_memory[6] = r_type(OPCODE_MULHI, 5'd4, 5'd1, 5'd2);
    instruction_memory[7] = r_type(OPCODE_DIV, 5'd6, 5'd1, 5'd2);
    instruction_memory[8] = r_type(OPCODE_REM, 5'd7, 5'd1, 5'd2);
    instruction_memory[9] = r_type(OPCODE_ADD, 5'd8, 5'd4, 5'd7);
    instruction_memory[10] = r_type(OPCODE_DIVU, 5'd9, 5'd8, 5'd2);
    instruction_memory[11] = r_type(OPCODE_REMU, 5'd10, 5'd8, 5'd2);
    instruction_memory[12] = r_type(OPCODE_MUL, 5'd11, 5'd10, 5'd10);
    instruction_memory[13] = r_type(OPCODE_MULHI, 5'd12, 5'd10, 5'd10);
    instruction_memory[14] = r_type(OPCODE_DIV, 5'd13, 5'd13, 5'd2);
    instruction_memory[15] = r_type(OPCODE_REM, 5'd14, 5'd13, 5'd2);
    instruction_memory[16] = HALT;
    compare_run("cadena mezclada", 1'b1);

    if (failures != 0) $fatal(1, "alu_fast_path_tb: %0d fallo(s)", failures);
    $display("alu_fast_path_tb: OK");
    $finish;
  end
endmodule

`default_nettype wire
