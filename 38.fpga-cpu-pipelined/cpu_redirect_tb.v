`timescale 1ns / 1ps
`default_nettype none

/*
 * Redireccion del salto registrada (cpu.v, if_redirect).
 *
 * Un salto tomado se decide en EX y redirige IF al ciclo siguiente. Detras
 * de el vienen dos instrucciones del camino equivocado: la que pasa de ID a
 * EX mientras el salto decide (entra como burbuja) y la que ID tiene en el
 * ciclo de la redireccion. Ninguna debe ejecutarse en EX, ni escribir, ni
 * fallar, ni parar por dependencia. Este banco pone de todo en esos huecos y
 * comprueba que no deja rastro:
 *
 *   1. TRAP, DIV por cero, JAL, STORE y ADDI en el camino equivocado, en
 *      el primer hueco y en los dos.
 *   2. Saltos encadenados: el destino de un salto es otro salto.
 *   3. STEP sobre el salto: PC en el destino y la siguiente instruccion es la
 *      del destino.
 *   4. HALT del monitor en cada ciclo de un bucle (barrido), y RUN: el
 *      resultado final no cambia, y el HALT de detras del salto no se adelanta.
 *   5. Salto tomado esperando en ID con EX ocupado por una MUL o una DIV.
 *   6. Prediccion estatica fallada: salto hacia atras no tomado y salida de
 *      un bucle.
 *   7. Pila de retornos: anidamiento mas hondo que la pila y un retorno a
 *      otra direccion que la apilada.
 *   8. BTB con alias: un salto que encuentra el destino de otro, y una
 *      instruccion que no es un salto predicha como tomada.
 *
 * Todo con aciertos de la I-cache de 1, 2 (la real) y 3 ciclos.
 */
module cpu_redirect_tb;

  reg clk = 1'b0;
  reg reset = 1'b1;
  reg run_request = 1'b0;
  reg halt_request = 1'b0;
  reg step_request = 1'b0;
  reg [4:0] debug_register_address = 5'd0;
  wire [31:0] imem_read_data;
  wire imem_rvalid;

  wire halted;
  wire error;
  wire [7:0] error_code;
  wire instruction_retired;
  wire imem_valid;
  wire [31:0] imem_address;
  wire [31:0] debug_register_data;
  wire [31:0] debug_pc;
  wire dmem_valid;

  localparam integer WORDS = 64;
  reg [31:0] instruction_memory[0:WORDS-1];
  integer k, pc, d, errors;
  integer retired = 0;

  always #5 clk = ~clk;

  // Sin memoria de datos: un acceso que llegara a EX se quedaria esperando
  // para siempre (dmem_ready = 0), y el banco lo ve como un cuelgue.
  // BTB diminuta (4 entradas, 1 bit de etiqueta): dos instrucciones a 32 bytes
  // comparten entrada, y el caso 8 lo aprovecha. Los demas casos corren igual
  // con ella; la BTB de verdad la usan cpu_tb, cpu_perf_tb y la suite.
  cpu #(.BTB_BITS(2), .BTB_TAG_BITS(1)) dut (
      .clk(clk), .reset(reset),
      .run_request(run_request), .halt_request(halt_request),
      .step_request(step_request),
      .halted(halted), .error(error), .error_code(error_code),
      .instruction_retired(instruction_retired),
      .imem_valid(imem_valid), .imem_address(imem_address),
      .imem_read_data(imem_read_data), .imem_ready(1'b1), .imem_rvalid(imem_rvalid),
      .dmem_valid(dmem_valid), .dmem_address(), .dmem_write_data(),
      .dmem_write_enable(), .dmem_read_data(32'h0000_0000), .dmem_ready(1'b0),
      .dmem_rvalid(1'b0), .dmem_error(1'b0), .dmem_waiting(),
      .debug_register_address(debug_register_address),
      .debug_register_data(debug_register_data), .debug_pc(debug_pc),
      .perf_stall(), .perf_muldiv_retired());

  // Memoria de instrucciones con latencia de acierto `imem_latency` (1 a 3):
  // la CPU tiene que dar lo mismo con cualquiera. La real tarda 2.
  integer imem_latency = 2;
  reg [2:0] imem_pipe_valid = 3'b000;
  reg [31:0] imem_pipe_data[0:2];
  always @(posedge clk) begin
    imem_pipe_valid <= reset ? 3'b000 : {imem_pipe_valid[1:0], imem_valid};
    imem_pipe_data[0] <= instruction_memory[imem_address[7:2]];
    imem_pipe_data[1] <= imem_pipe_data[0];
    imem_pipe_data[2] <= imem_pipe_data[1];
  end
  assign imem_rvalid = imem_pipe_valid[imem_latency - 1];
  assign imem_read_data = imem_pipe_data[imem_latency - 1];

  always @(posedge clk) begin
    if (reset) retired <= 0;
    else if (instruction_retired) retired <= retired + 1;
    if (dmem_valid) $fatal(1, "un acceso a datos llego a EX en pc %08x", dut.ex_pc);
  end

  // ---------------------------------------------------------------- codificacion
  localparam [31:0] HALT = 32'hfc00_0000;
  localparam [31:0] TRAP = 32'hf800_0000;
  function [31:0] addi(input [4:0] rd, input [4:0] ra, input [15:0] imm);
    addi = {6'h11, rd, ra, imm};
  endfunction
  function [31:0] rtype(input [5:0] op, input [4:0] rd, input [4:0] ra, input [4:0] rb);
    rtype = {op, rd, ra, rb, 11'd0};
  endfunction
  // Saltos: destino = PC + 4 + 4 * offset.
  function [31:0] beq(input [4:0] a, input [4:0] b, input [15:0] offset);
    beq = {6'h20, a, b, offset};
  endfunction
  function [31:0] bne(input [4:0] a, input [4:0] b, input [15:0] offset);
    bne = {6'h21, a, b, offset};
  endfunction
  function [31:0] bra(input [25:0] offset);
    bra = {6'h2f, offset};
  endfunction
  function [31:0] jal(input [4:0] rd, input [15:0] offset);
    jal = {6'h2c, rd, 5'd0, offset};
  endfunction
  // JR ra (destino = ra); JR R31 es el retorno de mini-cc.
  function [31:0] jr(input [4:0] ra);
    jr = {6'h2e, 5'd0, ra, 16'd0};
  endfunction
  function [31:0] store(input [4:0] rd, input [4:0] ra, input [15:0] imm);
    store = {6'h16, rd, ra, imm};
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

  task do_reset;
    begin
      @(negedge clk);
      reset = 1'b1;
      repeat (2) @(negedge clk);
      reset = 1'b0;
      wait (!dut.register_file_busy);
      @(negedge clk);
    end
  endtask

  task pulse(input integer which);  // 0 run, 1 step, 2 halt
    begin
      @(negedge clk);
      if (which == 0) run_request = 1'b1;
      else if (which == 1) step_request = 1'b1;
      else halt_request = 1'b1;
      @(negedge clk);
      run_request = 1'b0;
      step_request = 1'b0;
      halt_request = 1'b0;
    end
  endtask

  task wait_halt;
    integer guard;
    begin
      guard = 0;
      while (!halted && guard < 5000) begin
        @(posedge clk);
        guard = guard + 1;
      end
      if (!halted) $fatal(1, "la CPU no para (pc %08x)", debug_pc);
      @(posedge clk);
      #1;
    end
  endtask

  task run_ok(input [8*24-1:0] name);
    begin
      do_reset();
      pulse(0);
      wait (!halted);
      wait_halt();
      if (error) $fatal(1, "%0s: error %02x en pc %08x", name, error_code, debug_pc);
    end
  endtask

  task expect_register(input [8*24-1:0] name, input [4:0] address, input [31:0] expected);
    begin
      debug_register_address = address;
      repeat (2) @(posedge clk);
      #1;
      if (debug_register_data !== expected) begin
        $display("%0s: R%0d = %08x, se esperaba %08x", name, address,
                 debug_register_data, expected);
        errors = errors + 1;
      end
    end
  endtask

  task expect_pc(input [8*24-1:0] name, input [31:0] expected);
    begin
      if (debug_pc !== expected) begin
        $display("%0s: pc %08x, se esperaba %08x", name, debug_pc, expected);
        errors = errors + 1;
      end
    end
  endtask

  // -------------------------------------------------------------------- pruebas
  initial begin
    #5_000_000;
    $fatal(1, "cpu_redirect_tb: timeout");
  end

  integer lat;
  initial begin
    errors = 0;
    for (lat = 1; lat <= 3; lat = lat + 1) begin
    imem_latency = lat;
    $display("-- latencia de la I-cache: %0d", lat);

    // 1. Lo que hay detras de un salto tomado no deja rastro. Cada salto
    //    salta UNA instruccion, la del camino equivocado.
    clear_memory();
    emit(addi(5'd5, 5'd0, 16'd7));       // R5 = 7 (divisor; R6 = 0)
    emit(beq(5'd0, 5'd0, 16'd1));        // tomado
    emit(TRAP);                          //   camino equivocado
    emit(bne(5'd5, 5'd0, 16'd1));        // tomado
    emit(rtype(6'h0c, 5'd7, 5'd5, 5'd6)); //   DIV R7 = R5 / R6 (por cero)
    emit(bra(26'd1));                    // tomado
    emit(jal(5'd8, 16'd10));             //   JAL R8 (escribiria R8 y saltaria)
    emit(beq(5'd0, 5'd0, 16'd1));        // tomado
    emit(store(5'd5, 5'd0, 16'h0400));   //   STORE (colgaria la CPU)
    emit(beq(5'd0, 5'd0, 16'd1));        // tomado
    emit(addi(5'd2, 5'd0, 16'd99));      //   R2 = 99
    emit(addi(5'd3, 5'd2, 16'd1));       // R3 = R2 + 1 = 1: R2 no se escribio
    emit(HALT);
    run_ok("1 camino equivocado");
    expect_register("1 R7", 5'd7, 32'd0);
    expect_register("1 R8", 5'd8, 32'd0);
    expect_register("1 R2", 5'd2, 32'd0);
    expect_register("1 R3", 5'd3, 32'd1);
    expect_pc("1 HALT", 32'd52);       // el HALT (0x30) se retira: PC a la siguiente
    if (errors != 0) $fatal(1, "1: %0d fallo(s)", errors);
    $display("1. camino equivocado tras salto tomado: sin efectos");

    // 1b. Igual, saltando DOS: la primera entra en EX como burbuja mientras
    //     el salto decide, y la segunda esta en ID durante la redireccion.
    clear_memory();
    emit(addi(5'd5, 5'd0, 16'd7));        // 0  R5 = 7
    emit(beq(5'd0, 5'd0, 16'd2));         // 4  tomado -> 16
    emit(store(5'd5, 5'd0, 16'h0400));    // 8    STORE (colgaria la CPU)
    emit(TRAP);                           // 12
    emit(bne(5'd5, 5'd0, 16'd2));         // 16 tomado -> 28
    emit(jal(5'd8, 16'd10));              // 20   JAL R8
    emit(rtype(6'h0c, 5'd7, 5'd5, 5'd6)); // 24   DIV por cero
    emit(bra(26'd2));                     // 28 tomado -> 40
    emit(addi(5'd2, 5'd0, 16'd99));       // 32   R2 = 99
    emit(store(5'd2, 5'd0, 16'h0400));    // 36   STORE con el R2 de arriba
    emit(addi(5'd3, 5'd2, 16'd1));        // 40 R3 = R2 + 1 = 1
    emit(HALT);                           // 44
    run_ok("1b dos huecos");
    expect_register("1b R7", 5'd7, 32'd0);
    expect_register("1b R8", 5'd8, 32'd0);
    expect_register("1b R2", 5'd2, 32'd0);
    expect_register("1b R3", 5'd3, 32'd1);
    expect_pc("1b HALT", 32'd48);
    if (errors != 0) $fatal(1, "1b: %0d fallo(s)", errors);
    $display("1b. dos instrucciones tras el salto tomado: sin efectos");

    // 2. Saltos encadenados: cada destino es otro salto tomado.
    clear_memory();
    emit(bra(26'd3));                    // 0 -> 4
    emit(addi(5'd1, 5'd1, 16'd1));       // 1 (no)
    emit(bra(26'd4));                    // 2 -> 7
    emit(addi(5'd1, 5'd1, 16'd2));       // 3 (no)
    emit(beq(5'd0, 5'd0, 16'hfffd));     // 4 -> 2
    emit(addi(5'd1, 5'd1, 16'd4));       // 5 (no)
    emit(addi(5'd1, 5'd1, 16'd8));       // 6 (no)
    emit(addi(5'd1, 5'd1, 16'd16));      // 7  R1 = 16
    emit(HALT);
    run_ok("2 encadenados");
    expect_register("2 R1", 5'd1, 32'd16);
    if (errors != 0) $fatal(1, "2: %0d fallo(s)", errors);
    $display("2. saltos encadenados: llega al destino del destino");

    // 3. STEP sobre un salto tomado y despues sobre su destino.
    clear_memory();
    emit(addi(5'd1, 5'd0, 16'd1));       // 0
    emit(beq(5'd0, 5'd0, 16'd2));        // 1 -> 4
    emit(addi(5'd2, 5'd0, 16'd5));       // 2 (no)
    emit(addi(5'd2, 5'd0, 16'd6));       // 3 (no)
    emit(addi(5'd3, 5'd0, 16'd9));       // 4
    emit(HALT);
    do_reset();
    pulse(1);
    wait (!halted);
    wait_halt();
    expect_pc("3 step 1", 32'd4);
    pulse(1);
    wait (!halted);
    wait_halt();
    expect_pc("3 step salto", 32'd16);
    expect_register("3 R2", 5'd2, 32'd0);
    pulse(1);
    wait (!halted);
    wait_halt();
    expect_pc("3 step destino", 32'd20);
    expect_register("3 R3", 5'd3, 32'd9);
    expect_register("3 R2 tras destino", 5'd2, 32'd0);
    if (error) $fatal(1, "3: error %02x", error_code);
    if (errors != 0) $fatal(1, "3: %0d fallo(s)", errors);
    $display("3. STEP sobre un salto tomado: PC en el destino");

    // 4. HALT del monitor en cada ciclo de un bucle corto, y RUN. Detras del
    //    salto hay un HALT, en el camino equivocado mientras el bucle salta:
    //    ni parando en el ciclo de la redireccion debe ejecutarse antes de
    //    tiempo.
    clear_memory();
    emit(addi(5'd1, 5'd0, 16'd6));       // 0  R1 = 6 vueltas
    emit(addi(5'd2, 5'd2, 16'd3));       // 1  R2 += 3
    emit(addi(5'd1, 5'd1, 16'hffff));    // 2  R1 -= 1
    emit(bne(5'd1, 5'd0, 16'hfffd));     // 3  -> 1
    emit(HALT);                          // 4  al salir del bucle
    for (d = 0; d < 60; d = d + 1) begin
      do_reset();
      pulse(0);
      repeat (d) @(negedge clk);
      if (!halted) begin
        halt_request = 1'b1;
        @(negedge clk);
        halt_request = 1'b0;
        wait_halt();
        if (error) $fatal(1, "4 (d=%0d): error %02x al parar", d, error_code);
        pulse(0);
        wait (!halted);
      end
      wait_halt();
      if (error) $fatal(1, "4 (d=%0d): error %02x", d, error_code);
      expect_register("4 R2", 5'd2, 32'd18);
      expect_register("4 R1", 5'd1, 32'd0);
      if (errors != 0) $fatal(1, "4 (d=%0d): %0d fallo(s)", d, errors);
    end
    $display("4. HALT en cada ciclo de un bucle y RUN: mismo resultado");

    // 5. Salto tomado esperando en ID mientras EX esta ocupado (MUL y DIV
    //    de varios ciclos): la decision se repite cada ciclo, pero solo
    //    redirige el ciclo en que el salto pasa a EX.
    clear_memory();
    emit(addi(5'd1, 5'd0, 16'd100));
    emit(addi(5'd2, 5'd0, 16'd7));
    emit(rtype(6'h0a, 5'd3, 5'd1, 5'd2)); // MUL R3 = 700
    emit(beq(5'd0, 5'd0, 16'd1));         // tomado, independiente del MUL
    emit(addi(5'd4, 5'd0, 16'd1));        //   (no)
    emit(rtype(6'h0c, 5'd5, 5'd1, 5'd2)); // DIV R5 = 14
    emit(jal(5'd7, 16'd1));               // tomado, independiente del DIV: R7 = 32
    emit(addi(5'd4, 5'd4, 16'd2));        //   (no)
    emit(addi(5'd6, 5'd3, 16'd1));        // R6 = 701
    emit(HALT);
    run_ok("5 EX ocupado");
    // Un salto que se perdiera de ID no cambia ningun registro (IF ya va al
    // destino), pero no se retira, y un JAL perderia su enlace.
    if (retired !== 8) begin
      $display("5: retiradas %0d, se esperaban 8", retired);
      errors = errors + 1;
    end
    expect_register("5 R7", 5'd7, 32'd28);
    expect_register("5 R3", 5'd3, 32'd700);
    expect_register("5 R5", 5'd5, 32'd14);
    expect_register("5 R4", 5'd4, 32'd0);
    expect_register("5 R6", 5'd6, 32'd701);
    if (errors != 0) $fatal(1, "5: %0d fallo(s)", errors);
    $display("5. salto tomado detras de MUL/DIV: redirige una vez");

    // 6. Prediccion estatica que falla (cpu.v, seccion 02b): un salto hacia
    //    atras que no se toma, con un TRAP en el destino que se predijo, y la
    //    salida de un bucle, cuyo camino equivocado decrementaria R1 otra vez.
    clear_memory();
    emit(bra(26'd1));                     // 0  -> 8
    emit(TRAP);                           // 4  destino predicho del BEQ
    emit(addi(5'd5, 5'd0, 16'd1));        // 8
    emit(beq(5'd5, 5'd0, 16'hfffd));      // 12 hacia atras, no se toma
    emit(addi(5'd1, 5'd0, 16'd3));        // 16
    emit(addi(5'd1, 5'd1, 16'hffff));     // 20 R1 -= 1
    emit(bne(5'd1, 5'd0, 16'hfffe));      // 24 -> 20, tres vueltas
    emit(addi(5'd2, 5'd0, 16'd5));        // 28
    emit(HALT);                           // 32
    run_ok("6 prediccion fallada");
    if (retired !== 12) begin
      $display("6: retiradas %0d, se esperaban 12", retired);
      errors = errors + 1;
    end
    expect_register("6 R1", 5'd1, 32'd0);
    expect_register("6 R2", 5'd2, 32'd5);
    expect_pc("6 HALT", 32'd36);
    if (errors != 0) $fatal(1, "6: %0d fallo(s)", errors);
    $display("6. salto hacia atras no tomado y salida de bucle: sin efectos");

    // 6b. Un BRA predicho espera en la cabeza de la cola mientras EX hace una
    //     MUL, y detras se llena la cola con TRAP: al predecir se descartan.
    clear_memory();
    emit(addi(5'd1, 5'd0, 16'd100));      // 0
    emit(addi(5'd2, 5'd0, 16'd7));        // 4
    emit(rtype(6'h0a, 5'd3, 5'd1, 5'd2)); // 8  MUL R3 = 700
    emit(addi(5'd4, 5'd0, 16'd1));        // 12 espera en ID
    emit(bra(26'd3));                     // 16 -> 32, espera en la cabeza
    emit(TRAP);                           // 20 cola detras del BRA
    emit(TRAP);                           // 24
    emit(TRAP);                           // 28
    emit(addi(5'd6, 5'd3, 16'd1));        // 32 R6 = 701
    emit(HALT);                           // 36
    run_ok("6b cola llena");
    expect_register("6b R6", 5'd6, 32'd701);
    expect_pc("6b HALT", 32'd40);
    if (errors != 0) $fatal(1, "6b: %0d fallo(s)", errors);
    $display("6b. salto predicho con la cola llena detras: la descarta");

    // 7. Pila de retornos: diez llamadas anidadas (la pila tiene 8) y un
    //    retorno a otra direccion que la apilada (g suma 8 a R31).
    clear_memory();
    emit(jal(5'd31, 16'd6));              // 0  llama a f1 (palabra 7)
    emit(addi(5'd20, 5'd0, 16'd99));      // 4
    emit(jal(5'd31, 16'd54));             // 8  llama a g (palabra 57)
    emit(TRAP);                           // 12 retorno apilado, no el real
    emit(TRAP);                           // 16
    emit(addi(5'd22, 5'd0, 16'd1));       // 20 retorno real de g
    emit(HALT);                           // 24
    emit(rtype(6'h01, 5'd1, 5'd31, 5'd0));  // f1: R1 = R31
    emit(jal(5'd31, 16'd3));          //   llama a f2
    emit(addi(5'd21, 5'd21, 16'd1));
    emit(rtype(6'h01, 5'd31, 5'd1, 5'd0));
    emit(jr(5'd31));
    emit(rtype(6'h01, 5'd2, 5'd31, 5'd0));  // f2: R2 = R31
    emit(jal(5'd31, 16'd3));          //   llama a f3
    emit(addi(5'd21, 5'd21, 16'd1));
    emit(rtype(6'h01, 5'd31, 5'd2, 5'd0));
    emit(jr(5'd31));
    emit(rtype(6'h01, 5'd3, 5'd31, 5'd0));  // f3: R3 = R31
    emit(jal(5'd31, 16'd3));          //   llama a f4
    emit(addi(5'd21, 5'd21, 16'd1));
    emit(rtype(6'h01, 5'd31, 5'd3, 5'd0));
    emit(jr(5'd31));
    emit(rtype(6'h01, 5'd4, 5'd31, 5'd0));  // f4: R4 = R31
    emit(jal(5'd31, 16'd3));          //   llama a f5
    emit(addi(5'd21, 5'd21, 16'd1));
    emit(rtype(6'h01, 5'd31, 5'd4, 5'd0));
    emit(jr(5'd31));
    emit(rtype(6'h01, 5'd5, 5'd31, 5'd0));  // f5: R5 = R31
    emit(jal(5'd31, 16'd3));          //   llama a f6
    emit(addi(5'd21, 5'd21, 16'd1));
    emit(rtype(6'h01, 5'd31, 5'd5, 5'd0));
    emit(jr(5'd31));
    emit(rtype(6'h01, 5'd6, 5'd31, 5'd0));  // f6: R6 = R31
    emit(jal(5'd31, 16'd3));          //   llama a f7
    emit(addi(5'd21, 5'd21, 16'd1));
    emit(rtype(6'h01, 5'd31, 5'd6, 5'd0));
    emit(jr(5'd31));
    emit(rtype(6'h01, 5'd7, 5'd31, 5'd0));  // f7: R7 = R31
    emit(jal(5'd31, 16'd3));          //   llama a f8
    emit(addi(5'd21, 5'd21, 16'd1));
    emit(rtype(6'h01, 5'd31, 5'd7, 5'd0));
    emit(jr(5'd31));
    emit(rtype(6'h01, 5'd8, 5'd31, 5'd0));  // f8: R8 = R31
    emit(jal(5'd31, 16'd3));          //   llama a f9
    emit(addi(5'd21, 5'd21, 16'd1));
    emit(rtype(6'h01, 5'd31, 5'd8, 5'd0));
    emit(jr(5'd31));
    emit(rtype(6'h01, 5'd9, 5'd31, 5'd0));  // f9: R9 = R31
    emit(jal(5'd31, 16'd3));          //   llama a f10
    emit(addi(5'd21, 5'd21, 16'd1));
    emit(rtype(6'h01, 5'd31, 5'd9, 5'd0));
    emit(jr(5'd31));
    emit(rtype(6'h01, 5'd10, 5'd31, 5'd0));  // f10: R10 = R31
    emit(addi(5'd23, 5'd0, 16'd1));   //   la mas honda
    emit(addi(5'd21, 5'd21, 16'd1));
    emit(rtype(6'h01, 5'd31, 5'd10, 5'd0));
    emit(jr(5'd31));
    emit(addi(5'd31, 5'd31, 16'd8));      // g: vuelve 8 bytes mas alla
    emit(jr(5'd31));
    run_ok("7 pila de retornos");
    expect_register("7 R21", 5'd21, 32'd10);
    expect_register("7 R20", 5'd20, 32'd99);
    expect_register("7 R22", 5'd22, 32'd1);
    expect_register("7 R1", 5'd1, 32'd4);
    expect_pc("7 HALT", 32'd28);
    if (errors != 0) $fatal(1, "7: %0d fallo(s)", errors);
    $display("7. llamadas mas hondas que la pila y retorno cambiado: bien");

    // 8. BTB con alias (seccion 02c): las palabras 2, 10 y 18 comparten
    //    entrada. El BNE de la 2 la llena (destino 1); el BEQ de la 10 la
    //    encuentra con el destino de otro (debe ir a la 12, no a la 1) y la
    //    reescribe; el ADDI de la 18 no es un salto y la BTB lo da por tomado
    //    hacia la 12, que sumaria 1 a R5 otra vez.
    clear_memory();
    emit(addi(5'd1, 5'd0, 16'd3));        // 0
    emit(addi(5'd1, 5'd1, 16'hffff));     // 4  R1 -= 1
    emit(bne(5'd1, 5'd0, 16'hfffe));      // 8  -> 4
    emit(addi(5'd3, 5'd0, 16'd7));        // 12
    for (k = 0; k < 6; k = k + 1) emit(32'h0000_0000);  // 16-36 NOP
    emit(beq(5'd0, 5'd0, 16'd1));         // 40 -> 48 (alias de la 8)
    emit(TRAP);                           // 44
    emit(addi(5'd5, 5'd5, 16'd1));        // 48 R5 += 1
    for (k = 0; k < 5; k = k + 1) emit(32'h0000_0000);  // 52-68 NOP
    emit(addi(5'd2, 5'd0, 16'd5));        // 72 (alias de la 8, no es salto)
    emit(addi(5'd4, 5'd0, 16'd9));        // 76
    emit(HALT);                           // 80
    run_ok("8 alias en la BTB");
    if (retired !== 24) begin
      $display("8: retiradas %0d, se esperaban 24", retired);
      errors = errors + 1;
    end
    expect_register("8 R1", 5'd1, 32'd0);
    expect_register("8 R5", 5'd5, 32'd1);
    expect_register("8 R2", 5'd2, 32'd5);
    expect_register("8 R4", 5'd4, 32'd9);
    expect_pc("8 HALT", 32'd84);
    if (errors != 0) $fatal(1, "8: %0d fallo(s)", errors);
    $display("8. alias en la BTB: destino ajeno y prediccion sobre un no-salto");

    end
    $display("PASS: cpu_redirect");
    $finish;
  end

endmodule

`default_nettype wire
