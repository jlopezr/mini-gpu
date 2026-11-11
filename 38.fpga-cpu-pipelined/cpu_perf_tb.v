`timescale 1ns / 1ps
`default_nettype none

/*
 * Ciclos por instruccion de la CPU, sin placa.
 *
 * cpu_tb.v comprueba que los resultados son correctos; este banco mide cuanto
 * cuestan. Cada programa aisla un efecto:
 *
 *   straight  200 ADDI independientes en linea recta: solo la busqueda.
 *   chain     200 ADDI R1,R1,1 seguidos: la parada por dependencia.
 *   loop      bucle de 4 instrucciones con BNE hacia atras: el salto tomado.
 *   store     bucle de STORE a direcciones seguidas, como el de un framebuffer.
 *   load      bucle de LOAD a direcciones seguidas.
 *
 * La memoria imita un ACIERTO de instruction_buffer.v: acepta una peticion
 * por ciclo (`ready` siempre alto) y la responde al ciclo siguiente con
 * `rvalid`. Es lo que veria la CPU en la placa con un 100 % de aciertos; los
 * fallos no se modelan.
 *
 * La memoria de datos imita a cpu_dmem_adapter.v: un STORE a la linea de 16
 * bytes que guarda el bufer de combinacion se contesta al ciclo siguiente; uno
 * a otra linea espera el volcado (FLUSH_CYCLES); un LOAD espera la lectura
 * (READ_CYCLES). Despues de contestar espera a que baje `valid` (su ST_DONE).
 * Las latencias de la SDRAM son una estimacion: lo que se mide de verdad aqui
 * es lo que cuesta el protocolo.
 *
 * Los ciclos se cuentan con la CPU en marcha (!halted), como CYCLES en
 * cpu_perf_counters.v. De momento solo informa: cuando un cambio mejore el CPI
 * se le pondra un tope para que no vuelva a empeorar sin avisar.
 */
module cpu_perf_tb;

  reg clk = 1'b0;
  reg reset = 1'b1;
  reg run_request = 1'b0;
  reg [4:0] debug_register_address = 5'd0;
  reg [31:0] imem_read_data = 32'h0000_0000;
  reg imem_rvalid = 1'b0;

  wire dmem_valid;
  wire [31:0] dmem_address, dmem_write_data;
  wire [3:0] dmem_write_enable;
  reg [31:0] dmem_read_data = 32'h0000_0000;
  reg dmem_ready = 1'b0;

  wire halted;
  wire error;
  wire [7:0] error_code;
  wire instruction_retired;
  wire imem_valid;
  wire [31:0] imem_address;
  wire [31:0] debug_register_data;
  wire [31:0] debug_pc;
  wire [3:0] perf_stall;

  localparam integer WORDS = 256;
  localparam [31:0] HALT = 32'hfc00_0000;

  reg [31:0] instruction_memory[0:WORDS-1];
  integer cycles = 0;
  integer retired = 0;
  integer k;

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
      .imem_ready(1'b1),
      .imem_rvalid(imem_rvalid),
      .dmem_valid(dmem_valid),
      .dmem_address(dmem_address),
      .dmem_write_data(dmem_write_data),
      .dmem_write_enable(dmem_write_enable),
      .dmem_read_data(dmem_read_data),
      .dmem_ready(dmem_ready),
      .dmem_error(1'b0),
      .debug_register_address(debug_register_address),
      .debug_register_data(debug_register_data),
      .debug_pc(debug_pc),
      .perf_stall(perf_stall)
  );

  // Los contadores de la placa, con las ranuras del pipeline. Se leen por
  // jerarquia: aqui no hay bus MMIO.
  cpu_perf_counters #(.PIPELINE(1)) perf (
      .clk(clk), .reset(reset),
      .select(1'b0), .write(1'b0), .write_mask(4'd0), .address(16'd0),
      .write_data(32'd0), .read_data(),
      .running(!halted), .retired(instruction_retired), .restart(run_request),
      .imem_valid(imem_valid), .imem_ready(1'b1),
      .dmem_valid(dmem_valid), .dmem_ready(dmem_ready), .dmem_is_mmio(1'b0),
      .imem_hit(1'b0), .imem_miss(1'b0), .mem_req0(1'b0), .mem_req1(1'b0),
      .pipe_stall(perf_stall));

  // Acierto del bufer de instrucciones: una peticion por ciclo, respuesta al
  // ciclo siguiente.
  always @(posedge clk) begin
    imem_rvalid <= imem_valid;
    if (imem_valid) imem_read_data <= instruction_memory[imem_address[9:2]];
  end

  // Memoria de datos: 1024 palabras, con el comportamiento de cpu_dmem_adapter.
  localparam integer FLUSH_CYCLES = 8;
  localparam integer READ_CYCLES = 8;
  localparam [1:0] D_IDLE = 2'd0, D_BUSY = 2'd1, D_DONE = 2'd2;
  reg [31:0] data_memory[0:1023];
  reg [1:0] d_state = D_IDLE;
  integer d_wait = 0;
  reg d_line_valid = 1'b0;
  reg [27:0] d_line = 28'd0;
  reg [31:0] stores = 0, loads = 0;

  always @(posedge clk) begin
    dmem_ready <= 1'b0;
    if (reset) begin
      d_state <= D_IDLE;
      d_line_valid <= 1'b0;
    end else case (d_state)
      D_IDLE:
        if (dmem_valid) begin
          if (dmem_write_enable != 4'd0) begin
            stores <= stores + 1;
            if (dmem_write_enable[0]) data_memory[dmem_address[11:2]][7:0] <= dmem_write_data[7:0];
            if (dmem_write_enable[1]) data_memory[dmem_address[11:2]][15:8] <= dmem_write_data[15:8];
            if (dmem_write_enable[2]) data_memory[dmem_address[11:2]][23:16] <= dmem_write_data[23:16];
            if (dmem_write_enable[3]) data_memory[dmem_address[11:2]][31:24] <= dmem_write_data[31:24];
            if (!d_line_valid || d_line == dmem_address[31:4]) begin
              dmem_ready <= 1'b1;
              d_state <= D_DONE;
            end else begin
              d_wait <= FLUSH_CYCLES;
              d_state <= D_BUSY;
            end
            d_line_valid <= 1'b1;
            d_line <= dmem_address[31:4];
          end else begin
            loads <= loads + 1;
            dmem_read_data <= data_memory[dmem_address[11:2]];
            d_wait <= READ_CYCLES;
            d_state <= D_BUSY;
          end
        end
      D_BUSY:
        if (d_wait <= 1) begin
          dmem_ready <= 1'b1;
          d_state <= D_DONE;
        end else begin
          d_wait <= d_wait - 1;
        end
      D_DONE:
        if (!dmem_valid) d_state <= D_IDLE;
      default: d_state <= D_IDLE;
    endcase
  end

  always @(posedge clk) begin
    if (reset) begin
      cycles <= 0;
      retired <= 0;
    end else begin
      if (!halted) cycles <= cycles + 1;
      if (instruction_retired) retired <= retired + 1;
    end
  end

  // Codificaciones (1.isa): opcode en [31:26], rd en [25:21], ra en [20:16].
  function [31:0] addi(input [4:0] rd, input [4:0] ra, input [15:0] imm);
    addi = 32'h4400_0000 | (rd << 21) | (ra << 16) | imm;
  endfunction

  function [31:0] movi(input [4:0] rd, input [15:0] imm);
    movi = 32'h4000_0000 | (rd << 21) | imm;
  endfunction

  // STORE guarda rd en [ra + imm]; LOAD carga rd de [ra + imm].
  function [31:0] store(input [4:0] rd, input [4:0] ra, input [15:0] imm);
    store = 32'h5800_0000 | (rd << 21) | (ra << 16) | imm;
  endfunction

  function [31:0] load(input [4:0] rd, input [4:0] ra, input [15:0] imm);
    load = 32'h5400_0000 | (rd << 21) | (ra << 16) | imm;
  endfunction

  // BNE compara rd con ra; el destino es PC + 4 + 4 * offset.
  function [31:0] bne(input [4:0] a, input [4:0] b, input [15:0] offset);
    bne = 32'h8400_0000 | (a << 21) | (b << 16) | offset;
  endfunction

  task clear_memory;
    begin
      for (k = 0; k < WORDS; k = k + 1) instruction_memory[k] = HALT;
    end
  endtask

  task expect_register;
    input [4:0] address;
    input [31:0] expected;
    begin
      debug_register_address = address;
      repeat (2) @(posedge clk);
      #1;
      if (debug_register_data !== expected)
        $fatal(1, "R%0d mismatch: expected %08x, got %08x", address, expected,
               debug_register_data);
    end
  endtask

  // Reset, RUN, esperar a que pare, y comprobar que retiro lo esperado sin error.
  task run_program;
    input [8*10-1:0] name;
    input integer expected_retired;
    begin
      @(negedge clk);
      reset = 1'b1;
      repeat (2) @(negedge clk);
      reset = 1'b0;
      @(negedge clk);
      run_request = 1'b1;
      @(negedge clk);
      run_request = 1'b0;
      wait (!halted);
      wait (halted);
      @(posedge clk);
      #1;
      if (error) $fatal(1, "%0s: error %02x en pc %08x", name, error_code, debug_pc);
      if (retired !== expected_retired)
        $fatal(1, "%0s: retiro %0d, se esperaban %0d", name, retired, expected_retired);
      $display("PERF %-8s cycles=%0d retired=%0d CPI=%0.2f", name, cycles, retired,
               cycles * 1.0 / retired);
      // Ciclos por instruccion de cada motivo; `otros` es lo que no cuentan
      // los cuatro (arranque, parada, HALT).
      $display("PIPE %-8s ex_mem=%0.2f raw=%0.2f branch=%0.2f id_empty=%0.2f otros=%0.2f",
               name, perf.stall_ex_mem * 1.0 / retired, perf.stall_raw * 1.0 / retired,
               perf.stall_branch * 1.0 / retired, perf.stall_id_empty * 1.0 / retired,
               (perf.cycles - perf.retired_count - perf.stall_ex_mem - perf.stall_raw -
                perf.stall_branch - perf.stall_id_empty) * 1.0 / retired);
    end
  endtask

  initial begin
    #5_000_000;
    $fatal(1, "cpu_perf_tb: timeout");
  end

  initial begin
    // straight: ADDI Rk, R0, k, rotando de R1 a R8, y HALT.
    clear_memory();
    for (k = 0; k < 200; k = k + 1) instruction_memory[k] = addi(5'd1 + (k % 8), 5'd0, k);
    run_program("straight", 201);
    expect_register(5'd1, 32'd192);
    expect_register(5'd8, 32'd199);

    // chain: cada ADDI necesita el resultado del anterior.
    clear_memory();
    for (k = 0; k < 200; k = k + 1) instruction_memory[k] = addi(5'd1, 5'd1, 16'd1);
    run_program("chain", 201);
    expect_register(5'd1, 32'd200);

    // loop: 50 vueltas de un cuerpo de 4. La resta va primero para que BNE
    // no espere a R2: aqui solo se mide el salto.
    clear_memory();
    instruction_memory[0] = movi(5'd2, 16'd50);
    instruction_memory[1] = addi(5'd2, 5'd2, 16'hffff);  // R2 -= 1
    instruction_memory[2] = addi(5'd4, 5'd0, 16'd1);
    instruction_memory[3] = addi(5'd5, 5'd0, 16'd2);
    instruction_memory[4] = bne(5'd2, 5'd0, 16'hfffc);    // a la palabra 1
    run_program("loop", 1 + 50 * 4 + 1);
    expect_register(5'd2, 32'd0);

    // store: 64 STORE a palabras seguidas desde 0x400, cuatro por linea de 16
    // bytes, con el contador y el puntero en medio como en un bucle de pixeles.
    clear_memory();
    instruction_memory[0] = movi(5'd1, 16'h0400);       // puntero
    instruction_memory[1] = movi(5'd2, 16'd64);         // vueltas
    instruction_memory[2] = movi(5'd3, 16'h1234);       // dato
    instruction_memory[3] = store(5'd3, 5'd1, 16'd0);   // [R1] = R3
    instruction_memory[4] = addi(5'd1, 5'd1, 16'd4);
    instruction_memory[5] = addi(5'd2, 5'd2, 16'hffff);
    instruction_memory[6] = bne(5'd2, 5'd0, 16'hfffc);  // a la palabra 3
    run_program("store", 3 + 64 * 4 + 1);
    if (data_memory[(16'h0400 >> 2) + 63] !== 32'h0000_1234)
      $fatal(1, "store: el ultimo STORE no llego a memoria");

    // load: 64 LOAD de palabras seguidas.
    clear_memory();
    for (k = 0; k < 64; k = k + 1) data_memory[(16'h0400 >> 2) + k] = k;
    instruction_memory[0] = movi(5'd1, 16'h0400);
    instruction_memory[1] = movi(5'd2, 16'd64);
    instruction_memory[2] = load(5'd4, 5'd1, 16'd0);    // R4 = [R1]
    instruction_memory[3] = addi(5'd1, 5'd1, 16'd4);
    instruction_memory[4] = addi(5'd2, 5'd2, 16'hffff);
    instruction_memory[5] = bne(5'd2, 5'd0, 16'hfffc);  // a la palabra 2
    run_program("load", 2 + 64 * 4 + 1);
    expect_register(5'd4, 32'd63);

    $display("PASS: cpu_perf");
    $finish;
  end

endmodule

`default_nettype wire
