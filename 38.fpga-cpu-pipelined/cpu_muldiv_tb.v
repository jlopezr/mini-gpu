`timescale 1ns / 1ps
`default_nettype none

/*
 * MUL, MULHI, MULFX, DIV, DIVU, REM y REMU en la CPU pipelined.
 *
 * Resultados: cada par de operandos (esquinas y aleatorios) pasa por las siete
 * operaciones y se compara con un modelo de referencia escrito con la
 * aritmetica de 64 bits del simulador (1.isa/isa.md, "Multiplicacion y
 * division").
 *
 * Atajo REM/REMU tras DIV/DIVU: solo con la instruccion inmediatamente
 * anterior, los mismos registros fuente y un DIV que no pise sus fuentes. Se
 * comprueba el valor en los casos que NO deben acertar (instruccion en medio,
 * rd == ra, registros cambiados, tipo distinto) y el coste en ciclos en el
 * que si.
 *
 * Errores: division por cero en las cuatro, con el PC en la instruccion y sin
 * escribir rd. Parada (HALT del monitor) a mitad de una division y reanudacion.
 *
 * Costes: tope de ciclos para MUL, para DIV y para el REM que acierta.
 */
module cpu_muldiv_tb;

  reg clk = 1'b0;
  reg reset = 1'b1;
  reg run_request = 1'b0;
  reg halt_request = 1'b0;
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
      .run_request(run_request),
      .halt_request(halt_request),
      .step_request(1'b0),
      .halted(halted),
      .error(error),
      .error_code(error_code),
      .instruction_retired(instruction_retired),
      .imem_valid(imem_valid),
      .imem_address(imem_address),
      .imem_read_data(imem_read_data),
      .imem_ready(1'b1),
      .imem_rvalid(imem_rvalid),
      .dmem_valid(),
      .dmem_address(),
      .dmem_write_data(),
      .dmem_write_enable(),
      .dmem_read_data(32'h0000_0000),
      .dmem_ready(1'b0),
      .dmem_rvalid(1'b0),
      .dmem_error(1'b0),
      .dmem_waiting(),
      .debug_register_address(debug_register_address),
      .debug_register_data(debug_register_data),
      .debug_pc(debug_pc),
      .perf_stall()
  );

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

  // Las siete operaciones sobre (a, b). Con b == 0 solo las de multiplicar.
  task check_pair(input [31:0] a, input [31:0] b);
    reg [63:0] p;
    begin
      clear_memory();
      load_constant(5'd1, a);
      load_constant(5'd2, b);
      emit(rtype(OP_MUL, 5'd3, 5'd1, 5'd2));
      emit(rtype(OP_MULHI, 5'd4, 5'd1, 5'd2));
      emit(rtype(OP_MULFX, 5'd5, 5'd1, 5'd2));
      if (b != 0) begin
        emit(rtype(OP_DIV, 5'd6, 5'd1, 5'd2));
        emit(rtype(OP_REM, 5'd8, 5'd1, 5'd2));    // acierta (DIV justo antes)
        emit(rtype(OP_DIVU, 5'd7, 5'd1, 5'd2));
        emit(rtype(OP_REMU, 5'd9, 5'd1, 5'd2));   // acierta (DIVU justo antes)
        emit(rtype(OP_REM, 5'd10, 5'd1, 5'd2));   // tras REMU: no acierta
        emit(rtype(OP_REMU, 5'd11, 5'd1, 5'd2));  // tras REM: no acierta
        emit(rtype(OP_ADD, 5'd12, 5'd6, 5'd7));   // depende de dos divisiones
      end
      emit(rtype(OP_ADD, 5'd13, 5'd3, 5'd4));     // depende de MUL y MULHI
      run_ok("pair");
      p = smul(a, b);
      expect_register("MUL", 5'd3, p[31:0]);
      expect_register("MULHI", 5'd4, p[63:32]);
      expect_register("MULFX", 5'd5, p[47:16]);
      expect_register("ADD mul", 5'd13, p[31:0] + p[63:32]);
      if (b != 0) begin
        expect_register("DIV", 5'd6, ref_div(a, b));
        expect_register("REM", 5'd8, ref_rem(a, b));
        expect_register("DIVU", 5'd7, a / b);
        expect_register("REMU", 5'd9, a % b);
        expect_register("REM 2", 5'd10, ref_rem(a, b));
        expect_register("REMU 2", 5'd11, a % b);
        expect_register("ADD div", 5'd12, ref_div(a, b) + a / b);
      end
      if (errors != 0) $fatal(1, "check_pair(%08x, %08x): %0d fallo(s)", a, b, errors);
    end
  endtask

  // Ciclos que cuesta `body` respecto a un NOP en su sitio.
  integer base_cycles, body_cycles;
  // Operandos y dos NOP, para que lo medido no espere al ORI que los carga.
  task cost_prologue;
    begin
      clear_memory();
      load_constant(5'd1, 32'd1000);
      load_constant(5'd2, 32'd7);
      emit(NOP);
      emit(NOP);
    end
  endtask

  task measure_base;
    begin
      cost_prologue();
      emit(NOP);
      emit(NOP);
      run_ok("base");
      base_cycles = cycles;
    end
  endtask

  // ------------------------------------------------------------------- pruebas
  reg [31:0] corner[0:9];
  reg [31:0] ra_value, rb_value;
  integer i, j;
  integer seed = 32'h38_5eed;

  initial begin
    #20_000_000;
    $fatal(1, "cpu_muldiv_tb: timeout");
  end

  initial begin
    errors = 0;
    corner[0] = 32'd0;          corner[1] = 32'd1;          corner[2] = 32'hffff_ffff;
    corner[3] = 32'h8000_0000;  corner[4] = 32'h7fff_ffff;  corner[5] = 32'd7;
    corner[6] = 32'hffff_fff9;  corner[7] = 32'h0001_0000;  corner[8] = 32'hffff_0000;
    corner[9] = 32'h0001_8000;

    // 1. Esquinas, todas contra todas, y aleatorios.
    for (i = 0; i < 10; i = i + 1)
      for (j = 0; j < 10; j = j + 1) check_pair(corner[i], corner[j]);
    for (i = 0; i < 40; i = i + 1) begin
      ra_value = $random(seed);
      rb_value = $random(seed);
      if (i % 4 == 1) rb_value = rb_value >>> 20;  // divisores pequeños
      check_pair(ra_value, rb_value);
    end
    $display("1. resultados: 140 pares OK");

    // 2. El atajo no debe acertar. Cada caso calcula un REM cuyo valor cambia
    //    si se reutilizara el resto del DIV anterior.
    // 2a. Instruccion en medio que cambia una fuente.
    clear_memory();
    load_constant(5'd1, 32'd100);
    load_constant(5'd2, 32'd7);
    emit(rtype(OP_DIV, 5'd6, 5'd1, 5'd2));
    emit(addi(5'd1, 5'd1, 16'd1));                // R1 = 101
    emit(rtype(OP_REM, 5'd8, 5'd1, 5'd2));        // 101 % 7 = 3, no 2
    run_ok("2a");
    expect_register("2a", 5'd8, 32'd3);
    // 2b. El DIV pisa su propia fuente (rd == ra).
    clear_memory();
    load_constant(5'd1, 32'd100);
    load_constant(5'd2, 32'd7);
    emit(rtype(OP_DIV, 5'd1, 5'd1, 5'd2));        // R1 = 14
    emit(rtype(OP_REM, 5'd8, 5'd1, 5'd2));        // 14 % 7 = 0, no 2
    run_ok("2b");
    expect_register("2b", 5'd8, 32'd0);
    // 2c. El DIV pisa la otra fuente (rd == rb).
    clear_memory();
    load_constant(5'd1, 32'd100);
    load_constant(5'd2, 32'd30);
    emit(rtype(OP_DIV, 5'd2, 5'd1, 5'd2));        // R2 = 3
    emit(rtype(OP_REM, 5'd8, 5'd1, 5'd2));        // 100 % 3 = 1, no 100 % 30 = 10
    run_ok("2c");
    expect_register("2c", 5'd8, 32'd1);
    // 2d. Fuentes cambiadas de orden.
    clear_memory();
    load_constant(5'd1, 32'd100);
    load_constant(5'd2, 32'd7);
    emit(rtype(OP_DIV, 5'd6, 5'd1, 5'd2));
    emit(rtype(OP_REM, 5'd8, 5'd2, 5'd1));        // 7 % 100 = 7, no 2
    run_ok("2d");
    expect_register("2d", 5'd8, 32'd7);
    // 2e. Tipo distinto: REMU tras DIV y REM tras DIVU, con signo que importa.
    clear_memory();
    load_constant(5'd1, 32'hffff_ff9b);           // -101 (con -100 los dos restos dan 2)
    load_constant(5'd2, 32'd7);
    emit(rtype(OP_DIV, 5'd6, 5'd1, 5'd2));
    emit(rtype(OP_REMU, 5'd8, 5'd1, 5'd2));
    emit(rtype(OP_DIVU, 5'd7, 5'd1, 5'd2));
    emit(rtype(OP_REM, 5'd9, 5'd1, 5'd2));
    run_ok("2e");
    expect_register("2e REMU", 5'd8, 32'hffff_ff9b % 32'd7);  // 1; el del DIV es 3
    expect_register("2e REM", 5'd9, 32'hffff_fffd);  // -101 rem 7 = -3; el del DIVU es 1
    // 2f. Un MUL en medio (no deja etiqueta de division).
    clear_memory();
    load_constant(5'd1, 32'd100);
    load_constant(5'd2, 32'd7);
    emit(rtype(OP_DIV, 5'd6, 5'd1, 5'd2));
    emit(rtype(OP_MUL, 5'd1, 5'd1, 5'd2));        // R1 = 700
    emit(rtype(OP_REM, 5'd8, 5'd1, 5'd2));        // 700 % 7 = 0, no 2
    run_ok("2f");
    expect_register("2f", 5'd8, 32'd0);
    if (errors != 0) $fatal(1, "2. atajo: %0d fallo(s)", errors);
    $display("2. atajo REM/REMU: los casos que no deben acertar dan bien");

    // 3. Division por cero: error preciso en las cuatro, sin escribir rd.
    for (i = 0; i < 4; i = i + 1) begin
      clear_memory();
      load_constant(5'd1, 32'd100);
      load_constant(5'd3, 32'h5555_5555);
      emit(rtype(OP_DIV + i, 5'd3, 5'd1, 5'd2));  // R2 = 0 tras el reset
      emit(addi(5'd4, 5'd0, 16'd1));
      reset_and_run();
      wait_halt();
      if (!error || error_code !== 8'h04)
        $fatal(1, "3.%0d: error=%0d code=%02x, se esperaba 04", i, error, error_code);
      if (debug_pc !== 32'd16)
        $fatal(1, "3.%0d: pc %08x, se esperaba 00000010", i, debug_pc);
      expect_register("3 rd", 5'd3, 32'h5555_5555);
      expect_register("3 siguiente", 5'd4, 32'd0);
    end
    // 3b. REM por cero justo despues de un DIV valido con otro divisor.
    clear_memory();
    load_constant(5'd1, 32'd100);
    load_constant(5'd2, 32'd7);
    emit(rtype(OP_DIV, 5'd6, 5'd1, 5'd2));
    emit(rtype(OP_REM, 5'd8, 5'd1, 5'd5));        // R5 = 0
    reset_and_run();
    wait_halt();
    if (!error || error_code !== 8'h04 || debug_pc !== 32'd20)
      $fatal(1, "3b: error=%0d code=%02x pc=%08x", error, error_code, debug_pc);
    if (errors != 0) $fatal(1, "3. division por cero: %0d fallo(s)", errors);
    $display("3. division por cero: error preciso, rd intacto");

    // 4. HALT del monitor a mitad de una division, y RUN de nuevo.
    clear_memory();
    load_constant(5'd1, 32'd1000);
    load_constant(5'd2, 32'd7);
    emit(rtype(OP_DIV, 5'd6, 5'd1, 5'd2));        // palabra 4, pc 0x10
    emit(rtype(OP_REM, 5'd8, 5'd1, 5'd2));
    reset_and_run();
    wait (dut.ex_valid && dut.ex_pc == 32'h10);
    repeat (10) @(negedge clk);
    halt_request = 1'b1;
    @(negedge clk);
    halt_request = 1'b0;
    wait_halt();
    if (error || debug_pc !== 32'h10)
      $fatal(1, "4: tras HALT error=%0d pc=%08x, se esperaba pc 00000010", error, debug_pc);
    @(negedge clk);
    run_request = 1'b1;
    @(negedge clk);
    run_request = 1'b0;
    wait (!halted);
    wait_halt();
    if (error) $fatal(1, "4: error %02x tras reanudar", error_code);
    expect_register("4 DIV", 5'd6, 32'd142);
    expect_register("4 REM", 5'd8, 32'd6);
    if (errors != 0) $fatal(1, "4. parada: %0d fallo(s)", errors);
    $display("4. HALT a mitad de DIV: PC en la DIV y reanuda bien");

    // 5. Costes, respecto a dos NOP en el mismo sitio.
    measure_base();
    cost_prologue();
    emit(rtype(OP_MUL, 5'd3, 5'd1, 5'd2));
    emit(NOP);
    run_ok("cost MUL");
    body_cycles = cycles - base_cycles;
    $display("PERF MUL  +%0d ciclos", body_cycles);
    if (body_cycles > 4) $fatal(1, "5: MUL cuesta %0d ciclos de mas", body_cycles);

    cost_prologue();
    emit(rtype(OP_DIV, 5'd3, 5'd1, 5'd2));
    emit(NOP);
    run_ok("cost DIV");
    n = cycles - base_cycles;
    $display("PERF DIV  +%0d ciclos", n);
    if (n > 36) $fatal(1, "5: DIV cuesta %0d ciclos de mas", n);

    cost_prologue();
    emit(rtype(OP_DIV, 5'd3, 5'd1, 5'd2));
    emit(rtype(OP_REM, 5'd4, 5'd1, 5'd2));
    run_ok("cost DIV+REM");
    body_cycles = cycles - base_cycles - n;
    $display("PERF REM tras DIV  +%0d ciclos", body_cycles);
    if (body_cycles > 3) $fatal(1, "5: el REM que acierta cuesta %0d ciclos", body_cycles);
    expect_register("5 REM", 5'd4, 32'd6);
    if (errors != 0) $fatal(1, "5. costes: %0d fallo(s)", errors);

    $display("PASS: cpu_muldiv");
    $finish;
  end

endmodule

`default_nettype wire
