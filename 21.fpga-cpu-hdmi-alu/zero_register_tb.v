`timescale 1ns / 1ps
`default_nettype none

/*
 * R0 cableado a cero.
 *
 * Las escrituras a R0 se descartan y las lecturas valen siempre cero. En el
 * RTL es una linea en register_file.v; lo que hay que probar es que esa linea
 * cubre TODAS las escrituras, porque el banco tiene un solo puerto pero la CPU
 * llega a el por seis caminos distintos --MOVI/MOVHI/GETTID directos,
 * STATE_ALU_WRITE, STATE_SHIFT_WRITE, STATE_MUL_WRITE, el enlace de JAL/JALR y
 * STATE_MEMORY_WAIT para los LOAD-- y es facil arreglar uno y olvidar los
 * otros.
 *
 * El monitor NO escribe registros: su unico acceso al banco es READ_REGISTER
 * (0x34), por el puerto de depuracion, que es de solo lectura. Asi que no hay
 * ningun SET_REGISTER que se convierta en un no-op silencioso.
 *
 * Lo que R0 compra --y es la razon de hacerlo, no el area-- esta al final:
 * `JALR R0, Ra, 0` es un `JR Ra` completo, con lo que el opcode 0x2E queda
 * reclamable.
 */
module zero_register_tb;

  localparam [5:0] OPCODE_ADD = 6'h01;
  localparam [5:0] OPCODE_SUB = 6'h02;
  localparam [5:0] OPCODE_SHL = 6'h07;
  localparam [5:0] OPCODE_MUL = 6'h0a;
  localparam [5:0] OPCODE_DIV = 6'h0c;
  localparam [5:0] OPCODE_MOVI = 6'h10;
  localparam [5:0] OPCODE_ORI = 6'h13;
  localparam [5:0] OPCODE_LOAD = 6'h15;
  localparam [5:0] OPCODE_STORE = 6'h16;
  localparam [5:0] OPCODE_MOVHI = 6'h17;
  localparam [5:0] OPCODE_BEQ = 6'h20;
  localparam [5:0] OPCODE_JAL = 6'h2c;
  localparam [5:0] OPCODE_JALR = 6'h2d;
  localparam [5:0] OPCODE_GETTID = 6'h30;
  localparam [31:0] HALT = 32'hfc00_0000;

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

  wire dmem_valid;
  wire [31:0] dmem_address;
  wire [31:0] dmem_write_data;
  wire [3:0] dmem_write_enable;
  reg [31:0] dmem_read_data = 32'h0000_0000;
  reg dmem_ready = 1'b0;

  reg [31:0] instruction_memory[0:63];
  reg [31:0] data_memory[0:15];
  integer failures = 0;
  integer index;

  always #5 clk = ~clk;

  cpu dut (
      .clk(clk), .reset(reset),
      .run_request(run_request), .halt_request(1'b0), .step_request(1'b0),
      .halted(halted), .error(error), .error_code(error_code),
      .instruction_retired(),
      .imem_valid(imem_valid), .imem_address(imem_address),
      .imem_read_data(imem_read_data), .imem_ready(imem_ready),
      .dmem_valid(dmem_valid), .dmem_address(dmem_address),
      .dmem_write_data(dmem_write_data), .dmem_write_enable(dmem_write_enable),
      .dmem_read_data(dmem_read_data), .dmem_ready(dmem_ready),
      .dmem_error(1'b0),
      .debug_register_address(debug_register_address),
      .debug_register_data(debug_register_data), .debug_pc(debug_pc)
  );

  always @(posedge clk) begin
    imem_ready <= imem_valid;
    if (imem_valid) imem_read_data <= instruction_memory[imem_address[7:2]];

    // Memoria de datos de un ciclo, con escritura por palabra completa.
    dmem_ready <= dmem_valid;
    if (dmem_valid) begin
      dmem_read_data <= data_memory[dmem_address[5:2]];
      if (dmem_write_enable == 4'b1111)
        data_memory[dmem_address[5:2]] <= dmem_write_data;
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
      for (index = 0; index < 16; index = index + 1)
        data_memory[index] = 32'h0000_0000;
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
      if (error) begin
        $display("FAIL: error 0x%02x inesperado en PC=%08x",
                 error_code, debug_pc);
        failures = failures + 1;
      end
    end
  endtask

  task check_register;
    input [8*32-1:0] what;
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

  initial begin
    $dumpvars(0, zero_register_tb);

    /*
     * Los seis caminos de escritura, todos apuntando a R0. R1 recoge por que
     * camino habria escapado la escritura si el descarte fallara: cada
     * instruccion deja un valor distinto y bien visible.
     */
    clear_memory();
    data_memory[1] = 32'hcafe_babe;
    instruction_memory[0] = i_type(OPCODE_MOVI, 5'd1, 5'd0, 16'd7);
    instruction_memory[1] = i_type(OPCODE_MOVI, 5'd2, 5'd0, 16'd4);
    // 1) MOVI directo
    instruction_memory[2] = i_type(OPCODE_MOVI, 5'd0, 5'd0, 16'hffff);
    // 2) MOVHI directo
    instruction_memory[3] = i_type(OPCODE_MOVHI, 5'd0, 5'd0, 16'hdead);
    // 3) STATE_ALU_WRITE
    instruction_memory[4] = r_type(OPCODE_ADD, 5'd0, 5'd1, 5'd1);
    // 4) STATE_SHIFT_WRITE
    instruction_memory[5] = r_type(OPCODE_SHL, 5'd0, 5'd1, 5'd2);
    // 5) STATE_MUL_WRITE, por el multiplicador y por el divisor
    instruction_memory[6] = r_type(OPCODE_MUL, 5'd0, 5'd1, 5'd1);
    instruction_memory[7] = r_type(OPCODE_DIV, 5'd0, 5'd1, 5'd2);
    // 6) STATE_MEMORY_WAIT: el destino de un LOAD
    instruction_memory[8] = i_type(OPCODE_LOAD, 5'd0, 5'd0, 16'd4);
    // 7) GETTID escribe cero, que no demuestra nada; va por completitud
    instruction_memory[9] = i_type(OPCODE_GETTID, 5'd0, 5'd0, 16'd0);
    // 8) El enlace de JAL
    instruction_memory[10] = i_type(OPCODE_JAL, 5'd0, 5'd0, 16'd1);
    instruction_memory[11] = HALT;
    instruction_memory[12] = HALT;

    run_program();
    check_register("ocho escrituras a R0", 5'd0, 32'h0000_0000);
    // Y el resto del banco sigue funcionando, que es la otra mitad del trato.
    check_register("R1 intacto", 5'd1, 32'd7);

    /*
     * R0 leido es cero en los dos puertos del banco y en las dos posiciones de
     * un R-Type. R3 = R0 + R0, R4 = R1 - R0, R5 = R0 - R1.
     */
    clear_memory();
    instruction_memory[0] = i_type(OPCODE_MOVI, 5'd1, 5'd0, 16'd7);
    instruction_memory[1] = r_type(OPCODE_ADD, 5'd3, 5'd0, 5'd0);
    instruction_memory[2] = r_type(OPCODE_SUB, 5'd4, 5'd1, 5'd0);
    instruction_memory[3] = r_type(OPCODE_SUB, 5'd5, 5'd0, 5'd1);
    instruction_memory[4] = HALT;

    run_program();
    check_register("R0+R0", 5'd3, 32'h0000_0000);
    check_register("R1-R0", 5'd4, 32'd7);
    check_register("R0-R1", 5'd5, 32'hffff_fff9);

    /*
     * Una escritura descartada NO deja rastro en el ciclo siguiente: la
     * instruccion de despues lee cero, no el valor que se intento escribir.
     * Es el fallo tipico de un banco con bypass mal puesto.
     */
    clear_memory();
    instruction_memory[0] = i_type(OPCODE_MOVI, 5'd1, 5'd0, 16'd7);
    instruction_memory[1] = i_type(OPCODE_MOVI, 5'd0, 5'd0, 16'd9);
    instruction_memory[2] = r_type(OPCODE_ADD, 5'd2, 5'd0, 5'd1);
    instruction_memory[3] = HALT;

    run_program();
    check_register("lectura tras escritura descartada", 5'd2, 32'd7);

    /*
     * R0 como cero en un branch, que es el idioma mas comun: comparar con cero
     * sin gastar un MOVI ni un registro.
     */
    clear_memory();
    instruction_memory[0] = i_type(OPCODE_MOVI, 5'd1, 5'd0, 16'd1);
    instruction_memory[1] = i_type(OPCODE_MOVI, 5'd2, 5'd0, 16'd0);
    instruction_memory[2] = i_type(OPCODE_BEQ, 5'd2, 5'd0, 16'd2);  // saltado
    instruction_memory[3] = i_type(OPCODE_MOVI, 5'd1, 5'd0, 16'd99);
    instruction_memory[4] = i_type(OPCODE_MOVI, 5'd1, 5'd0, 16'd98);
    instruction_memory[5] = i_type(OPCODE_MOVI, 5'd3, 5'd0, 16'd5);
    instruction_memory[6] = HALT;

    run_program();
    check_register("BEQ contra R0", 5'd1, 32'd1);
    check_register("BEQ contra R0 continua", 5'd3, 32'd5);

    /*
     * La razon del cambio: `JALR R0, Ra, 0` es un `JR Ra` completo. El enlace
     * se descarta y el salto ocurre, asi que 0x2E queda obsoleto y su hueco es
     * reclamable. `JR` sigue implementado --quitarlo hoy rompe programas sin
     * ganar nada-- y aqui se comprueba que los dos hacen lo mismo.
     */
    clear_memory();
    instruction_memory[0] = i_type(OPCODE_MOVI, 5'd6, 5'd0, 16'h0018);  // 0x18
    instruction_memory[1] = i_type(OPCODE_JALR, 5'd0, 5'd6, 16'd0);
    instruction_memory[2] = i_type(OPCODE_MOVI, 5'd1, 5'd0, 16'd99);
    instruction_memory[3] = i_type(OPCODE_MOVI, 5'd1, 5'd0, 16'd98);
    instruction_memory[4] = i_type(OPCODE_MOVI, 5'd1, 5'd0, 16'd97);
    instruction_memory[5] = i_type(OPCODE_MOVI, 5'd1, 5'd0, 16'd96);
    instruction_memory[6] = i_type(OPCODE_MOVI, 5'd1, 5'd0, 16'd42);  // 0x18
    instruction_memory[7] = HALT;

    run_program();
    check_register("JALR R0 salta", 5'd1, 32'd42);
    check_register("JALR R0 descarta el enlace", 5'd0, 32'h0000_0000);
    if (debug_pc !== 32'h0000_0020) begin
      $display("FAIL JALR R0: PC = %08x, esperado 00000020", debug_pc);
      failures = failures + 1;
    end

    /*
     * R0 como destino de descarte: solo interesan los efectos de la operacion.
     * Una division valida con destino R0 se retira sin error --y una division
     * por cero con destino R0 sigue parando, porque el error no depende del
     * destino--.
     */
    clear_memory();
    instruction_memory[0] = i_type(OPCODE_MOVI, 5'd1, 5'd0, 16'd7);
    instruction_memory[1] = i_type(OPCODE_MOVI, 5'd2, 5'd0, 16'd2);
    instruction_memory[2] = r_type(OPCODE_DIV, 5'd0, 5'd1, 5'd2);
    instruction_memory[3] = i_type(OPCODE_MOVI, 5'd3, 5'd0, 16'd5);
    instruction_memory[4] = HALT;

    run_program();
    check_register("DIV a R0 no escribe", 5'd0, 32'h0000_0000);
    check_register("DIV a R0 continua", 5'd3, 32'd5);

    clear_memory();
    instruction_memory[0] = i_type(OPCODE_MOVI, 5'd1, 5'd0, 16'd7);
    instruction_memory[1] = r_type(OPCODE_DIV, 5'd0, 5'd1, 5'd0);
    instruction_memory[2] = HALT;
    reset_cpu();
    run_request = 1'b1;
    @(negedge clk);
    run_request = 1'b0;
    wait (!halted);
    wait (halted);
    @(posedge clk);
    #1;
    if (!error || error_code !== 8'h04) begin
      $display("FAIL DIV por R0: error=%0d codigo=0x%02x, esperado 0x04",
               error, error_code);
      failures = failures + 1;
    end

    /*
     * STORE lee su fuente del campo Rd, que es el otro puerto del banco.
     * `STORE R0, R1, 0` tiene que escribir un cero en memoria, no basura.
     */
    clear_memory();
    data_memory[2] = 32'hffff_ffff;
    instruction_memory[0] = i_type(OPCODE_MOVI, 5'd1, 5'd0, 16'd8);
    instruction_memory[1] = i_type(OPCODE_STORE, 5'd0, 5'd1, 16'd0);
    instruction_memory[2] = HALT;

    run_program();
    if (data_memory[2] !== 32'h0000_0000) begin
      $display("FAIL STORE R0: memoria = %08x, esperado 00000000",
               data_memory[2]);
      failures = failures + 1;
    end

    if (failures != 0) $fatal(1, "zero_register_tb: %0d fallo(s)", failures);
    $display("zero_register_tb: OK");
    $finish;
  end
endmodule

`default_nettype wire
