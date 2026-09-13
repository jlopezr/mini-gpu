`timescale 1ns / 1ps
`default_nettype none

/*
 * Desplazamientos con cantidad inmediata: SHLI, SHRI y SARI.
 *
 * Opcion B de 1.isa/propuesta-v0.2.md §4.2: sin opcodes nuevos. SHL (0x07),
 * SHR (0x08) y SAR (0x09) siguen siendo R-Type y el bit 10 del campo `extra`
 * pasa a significar «la cantidad es inmediata», tomandola de los cinco bits del
 * campo Rb.
 *
 * Lo que se comprueba aqui:
 *
 *   1. Las tres instrucciones con cantidad inmediata dan lo mismo que con
 *      cantidad en registro, para los bordes 0 y 31 y para un valor de enmedio.
 *   2. Con cantidad inmediata NO se lee el registro cuyo numero coincide con la
 *      cantidad. Es el fallo que un test descuidado no ve: si el mux tomara el
 *      registro en vez del campo, un `SHLI Rd, Ra, 4` con R4 valiendo 4
 *      «funcionaria» igual. Por eso cada caso deja en ese registro un valor
 *      distinto de la cantidad a proposito.
 *   3. El campo reservado de estos tres opcodes pasa a ser `extra[9:0]`:
 *      `extra[10]` con el resto a cero es valido, y cualquier bit de [9:0]
 *      puesto sigue dando ERROR_INVALID_ENCODING.
 *   4. La cuenta de ciclos sale de la cantidad inmediata, no de operand_b.
 */
module shift_immediate_tb;

  localparam [5:0] OPCODE_SHL = 6'h07;
  localparam [5:0] OPCODE_SHR = 6'h08;
  localparam [5:0] OPCODE_SAR = 6'h09;
  localparam [5:0] OPCODE_MOVI = 6'h10;
  localparam [5:0] OPCODE_MOVHI = 6'h17;
  localparam [5:0] OPCODE_ORI = 6'h13;
  localparam [10:0] IMMEDIATE = 11'd1024;   // extra[10]

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
        instruction_memory[index] = 32'hfc00_0000;    // HALT
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
   * Un caso: carga 0x89ABCDEF en R1, deja `poison` en el registro cuyo numero
   * es la cantidad, y desplaza de las dos formas --registro e inmediato-- para
   * comparar los dos resultados con el esperado.
   *
   * `poison` es lo que hace util el caso: si el camino inmediato leyera el
   * registro numero `amount` en vez del campo, el resultado saldria distinto.
   */
  task shift_case;
    input [8*40-1:0] what;
    input [5:0] op;
    input [31:0] value;
    input [4:0] amount;
    input [31:0] poison;
    input [31:0] expected;
    begin
      clear_memory();
      // R1 = value
      instruction_memory[0] = i_type(OPCODE_MOVHI, 5'd1, 5'd0, value[31:16]);
      instruction_memory[1] = i_type(OPCODE_ORI, 5'd1, 5'd1, value[15:0]);
      // R2 = amount, la cantidad en registro
      instruction_memory[2] = i_type(OPCODE_MOVI, 5'd2, 5'd0, {11'd0, amount});
      // El registro numero `amount` recibe basura, no la cantidad.
      instruction_memory[3] = i_type(OPCODE_MOVI, amount, 5'd0, poison[15:0]);
      // R3 = shift con registro; R4 = shift con inmediato
      instruction_memory[4] = r_type(op, 5'd3, 5'd1, 5'd2, 11'd0);
      instruction_memory[5] = r_type(op, 5'd4, 5'd1, amount, IMMEDIATE);
      instruction_memory[6] = 32'hfc00_0000;

      run_program();
      if (error) begin
        $display("FAIL %0s: error inesperado 0x%02x", what, error_code);
        failures = failures + 1;
      end
      // R3 solo vale como referencia si `amount` no es 2 ni 1: si lo fuera, el
      // MOVI de basura habria pisado el operando. Los casos elegidos lo evitan.
      check_register(what, 5'd3, expected);
      check_register(what, 5'd4, expected);
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
      instruction_memory[1] = 32'hfc00_0000;
      run_program();
      if (error) begin
        $display("FAIL %0s: error 0x%02x inesperado", what, error_code);
        failures = failures + 1;
      end
    end
  endtask

  initial begin
    $dumpvars(0, shift_immediate_tb);

    // ---- SHLI ----------------------------------------------------------
    // Cantidad 0: el borde que se salta STATE_SHIFT_STEP entero.
    shift_case("SHLI 0", OPCODE_SHL, 32'h89ab_cdef, 5'd0,
               32'h0000_dead, 32'h89ab_cdef);
    // Cantidad 31: el otro borde.
    shift_case("SHLI 31", OPCODE_SHL, 32'h89ab_cdef, 5'd31,
               32'h0000_beef, 32'h8000_0000);
    shift_case("SHLI 4", OPCODE_SHL, 32'h89ab_cdef, 5'd4,
               32'h0000_0007, 32'h9abc_def0);

    // ---- SHRI, logico --------------------------------------------------
    shift_case("SHRI 0", OPCODE_SHR, 32'h89ab_cdef, 5'd0,
               32'h0000_dead, 32'h89ab_cdef);
    shift_case("SHRI 31", OPCODE_SHR, 32'h89ab_cdef, 5'd31,
               32'h0000_beef, 32'h0000_0001);
    shift_case("SHRI 4", OPCODE_SHR, 32'h89ab_cdef, 5'd4,
               32'h0000_0009, 32'h089a_bcde);

    // ---- SARI, aritmetico: el signo se propaga -------------------------
    shift_case("SARI 0", OPCODE_SAR, 32'h89ab_cdef, 5'd0,
               32'h0000_dead, 32'h89ab_cdef);
    shift_case("SARI 31", OPCODE_SAR, 32'h89ab_cdef, 5'd31,
               32'h0000_beef, 32'hffff_ffff);
    shift_case("SARI 4", OPCODE_SAR, 32'h89ab_cdef, 5'd4,
               32'h0000_000a, 32'hf89a_bcde);
    // Positivo: SARI y SHRI coinciden.
    shift_case("SARI 4 positivo", OPCODE_SAR, 32'h1234_5678, 5'd4,
               32'h0000_000a, 32'h0123_4567);

    // ---- Encoding ------------------------------------------------------
    // extra[10] solo: valido, es el modo inmediato.
    expect_no_error("SHLI extra=0x400",
                    r_type(OPCODE_SHL, 5'd1, 5'd2, 5'd3, IMMEDIATE));
    // Cualquier bit de extra[9:0] sigue siendo reservado.
    expect_encoding_error("SHL extra[0]",
                          r_type(OPCODE_SHL, 5'd1, 5'd2, 5'd3, 11'd1));
    expect_encoding_error("SHR extra[9]",
                          r_type(OPCODE_SHR, 5'd1, 5'd2, 5'd3, 11'h200));
    expect_encoding_error("SAR extra[10]+[3]",
                          r_type(OPCODE_SAR, 5'd1, 5'd2, 5'd3,
                                 IMMEDIATE | 11'd8));

    // ---- El contador de pasos tambien sale del inmediato ----------------
    // R5 vale cero y no se toca. Si `shift_remaining` se cargase de operand_b
    // en vez de la cantidad inmediata, esto se saltaria STATE_SHIFT_STEP y
    // dejaria R2 = 1 en lugar de 32.
    clear_memory();
    instruction_memory[0] = i_type(OPCODE_MOVI, 5'd1, 5'd0, 16'd1);
    instruction_memory[1] = r_type(OPCODE_SHL, 5'd2, 5'd1, 5'd5, IMMEDIATE);
    instruction_memory[2] = 32'hfc00_0000;
    run_program();
    check_register("SHLI cantidad del campo", 5'd2, 32'h0000_0020);

    if (failures != 0) $fatal(1, "shift_immediate_tb: %0d fallo(s)", failures);
    $display("shift_immediate_tb: OK");
    $finish;
  end
endmodule

`default_nettype wire
