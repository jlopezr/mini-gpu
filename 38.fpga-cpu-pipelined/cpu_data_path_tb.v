`timescale 1ns / 1ps
`default_nettype none

/*
 * El camino de datos entero, como en la placa: cpu.v -> dcache.v ->
 * cpu_dmem_adapter.v -> un modelo del puerto del arbitro (el de
 * cpu_dmem_adapter_tb: cola de 4, ejecucion en orden, latencia de 16 ciclos).
 * Las instrucciones salen de un modelo que acierta siempre.
 *
 * Nacio para el primer adaptador con volcados sin esperar: su banco pasaba y
 * en placa se perdia la primera palabra de cada linea nueva. Aqui la CPU,
 * la D-cache y el adaptador reales se dan la mano como en la placa.
 *
 * Cada programa termina en HALT; despues se espera a `wb_dirty` (lo que hace el
 * monitor) y se compara la memoria del modelo.
 *
 * Tambien mide lo que cuesta un LOAD que acierta en la D-cache, en ciclos de
 * "EX con memoria" (perf_stall[0]) y por diferencia entre dos programas que
 * solo cambian en los LOAD medidos:
 *   aciertos   LOAD seguidos a una linea ya en la cache;
 *   tras STORE pares STORE (a otra linea, sale sin esperar) + LOAD que acierta.
 */
module cpu_data_path_tb;
  reg clk = 1'b0;
  always #5 clk = ~clk;
  reg reset = 1'b1;
  reg run_request = 1'b0;
  reg cpu_halted_force = 1'b0;

  localparam integer PORT_DEPTH = 4;
  localparam integer LATENCY = 16;
  localparam integer SERVICE_CYCLES = 3;
  localparam integer WORDS = 256;
  localparam [31:0] HALT = 32'hfc00_0000;

  // -- CPU --------------------------------------------------------------------
  reg [31:0] imem_read_data = 32'h0000_0000;
  reg imem_rvalid = 1'b0;
  wire imem_valid;
  wire [31:0] imem_address;
  wire halted, error, instruction_retired, dmem_waiting;
  wire [7:0] error_code;
  wire [31:0] debug_register_data, debug_pc;
  wire [4:0] perf_stall;
  reg [4:0] debug_register_address = 5'd0;

  wire c_valid, c_ready, c_rvalid, c_error;
  wire [31:0] c_address, c_wdata, c_rdata;
  wire [3:0] c_wen;

  cpu cpu_i(
      .clk(clk), .reset(reset), .soft_reset(1'b0), .run_request(run_request), .halt_request(1'b0),
      .step_request(1'b0), .halted(halted), .error(error), .error_code(error_code),
      .instruction_retired(instruction_retired),
      .imem_valid(imem_valid), .imem_address(imem_address),
      .imem_read_data(imem_read_data), .imem_ready(1'b1), .imem_rvalid(imem_rvalid),
      .dmem_valid(c_valid), .dmem_address(c_address), .dmem_write_data(c_wdata),
      .dmem_write_enable(c_wen), .dmem_read_data(c_rdata), .dmem_ready(c_ready),
      .dmem_rvalid(c_rvalid), .dmem_error(c_error), .dmem_waiting(dmem_waiting),
      .debug_register_address(debug_register_address),
      .debug_register_data(debug_register_data), .debug_pc(debug_pc),
      .perf_stall(perf_stall));

  reg [31:0] instruction_memory[0:WORDS-1];
  always @(posedge clk) begin
    imem_rvalid <= imem_valid;
    if (imem_valid) imem_read_data <= instruction_memory[imem_address[9:2]];
  end

  // -- D-cache y adaptador -------------------------------------------------------
  wire a_valid, a_ready, a_rvalid, a_error;
  wire [31:0] a_address, a_wdata, a_rdata;
  wire [3:0] a_wen;
  wire [127:0] a_line;
  wire cpu_halted = halted || cpu_halted_force;

  dcache #(.LINES(16), .INDEX_BITS(4)) dcache_i(
      .clk(clk), .reset(reset), .invalidate(cpu_halted),
      .cpu_valid(c_valid), .cpu_address(c_address), .cpu_write_data(c_wdata),
      .cpu_write_enable(c_wen), .cpu_ready(c_ready), .cpu_read_data(c_rdata),
      .cpu_rvalid(c_rvalid), .cpu_error(c_error),
      .mem_valid(a_valid), .mem_address(a_address), .mem_write_data(a_wdata),
      .mem_write_enable(a_wen), .mem_ready(a_ready), .mem_read_data(a_rdata),
      .mem_read_line(a_line), .mem_rvalid(a_rvalid), .mem_error(a_error),
      .hit_event(), .miss_event());

  wire req_valid, req_write, rsp_ready, wb_dirty;
  reg req_ready = 1'b1;
  wire [31:0] req_addr;
  wire [127:0] req_wdata;
  wire [15:0] req_wmask;
  reg rsp_valid = 1'b0;
  reg [127:0] rsp_rdata = 128'd0;

  cpu_dmem_adapter adapter_i(
      .clk(clk), .reset(reset), .init_done(1'b1), .cpu_halted(cpu_halted),
      .dmem_valid(a_valid), .dmem_address(a_address), .dmem_write_data(a_wdata),
      .dmem_write_enable(a_wen), .dmem_ready(a_ready), .dmem_read_data(a_rdata),
      .dmem_read_line(a_line), .dmem_rvalid(a_rvalid), .dmem_error(a_error),
      .wb_dirty(wb_dirty),
      .mmio_req(), .mmio_ack(1'b0), .mmio_write(), .mmio_write_mask(),
      .mmio_address(), .mmio_write_data(), .mmio_read_data(32'd0), .mmio_error(1'b0),
      .req_valid(req_valid), .req_ready(req_ready), .req_write(req_write),
      .req_addr(req_addr), .req_wdata(req_wdata), .req_wmask(req_wmask),
      .rsp_valid(rsp_valid), .rsp_ready(rsp_ready), .rsp_rdata(rsp_rdata),
      .rsp_error(1'b0), .merge_count(), .flush_count());

  // -- Modelo del puerto (ver cpu_dmem_adapter_tb) -------------------------------
  reg [7:0] memory[0:4095];
  reg q_write[0:63];
  reg [31:0] q_addr[0:63];
  reg [127:0] q_wdata[0:63];
  reg [15:0] q_wmask[0:63];
  reg [127:0] q_rdata[0:63];
  integer q_ready_at[0:63];
  integer q_head = 0, q_exec = 0, q_tail = 0;
  integer cycle = 0, next_exec_at = 0;
  integer i;

  always @(posedge clk) begin
    cycle <= cycle + 1;
    rsp_valid <= 1'b0;
    if (q_exec < q_tail && cycle >= next_exec_at) begin
      if (q_write[q_exec % 64]) begin
        for (i = 0; i < 16; i = i + 1)
          if (q_wmask[q_exec % 64][i]) memory[{q_addr[q_exec % 64][11:4], 4'b0} + i] = q_wdata[q_exec % 64][i*8 +: 8];
      end else begin
        for (i = 0; i < 16; i = i + 1)
          q_rdata[q_exec % 64][i*8 +: 8] = memory[{q_addr[q_exec % 64][11:4], 4'b0} + i];
      end
      q_exec = q_exec + 1;
      next_exec_at = cycle + SERVICE_CYCLES;
    end
    if (q_head < q_exec && cycle >= q_ready_at[q_head % 64] && rsp_ready) begin
      rsp_valid <= 1'b1;
      rsp_rdata <= q_write[q_head % 64] ? 128'd0 : q_rdata[q_head % 64];
      q_head = q_head + 1;
    end
    if (req_valid && req_ready) begin
      q_write[q_tail % 64] = req_write;
      q_addr[q_tail % 64] = req_addr;
      q_wdata[q_tail % 64] = req_wdata;
      q_wmask[q_tail % 64] = req_wmask;
      q_ready_at[q_tail % 64] = cycle + LATENCY;
      q_tail = q_tail + 1;
    end
    req_ready <= (q_tail - q_head) < PORT_DEPTH;
  end

  function [31:0] mem_word(input [31:0] a);
    mem_word = {memory[{a[11:2], 2'd3}], memory[{a[11:2], 2'd2}],
                memory[{a[11:2], 2'd1}], memory[{a[11:2], 2'd0}]};
  endfunction

  // -- Programas -------------------------------------------------------------------
  function [31:0] addi(input [4:0] rd, input [4:0] ra, input [15:0] imm);
    addi = 32'h4400_0000 | (rd << 21) | (ra << 16) | imm;
  endfunction
  function [31:0] movi(input [4:0] rd, input [15:0] imm);
    movi = 32'h4000_0000 | (rd << 21) | imm;
  endfunction
  function [31:0] store(input [4:0] rd, input [4:0] ra, input [15:0] imm);
    store = 32'h5800_0000 | (rd << 21) | (ra << 16) | imm;
  endfunction
  function [31:0] load(input [4:0] rd, input [4:0] ra, input [15:0] imm);
    load = 32'h5400_0000 | (rd << 21) | (ra << 16) | imm;
  endfunction
  function [31:0] bne(input [4:0] a, input [4:0] b, input [15:0] offset);
    bne = 32'h8400_0000 | (a << 21) | (b << 16) | offset;
  endfunction

  integer errors = 0;
  integer k, t;
  integer base_ex_mem, base_cycles;

  task measure_hits(input integer n);
    begin
      for (k = 0; k < WORDS; k = k + 1) instruction_memory[k] = HALT;
      instruction_memory[0] = movi(5'd1, 16'h0300);
      instruction_memory[1] = addi(5'd0, 5'd0, 16'd0);   // NOP: R1 listo
      instruction_memory[2] = addi(5'd0, 5'd0, 16'd0);
      instruction_memory[3] = load(5'd4, 5'd1, 16'd0);   // falla: trae la linea
      for (k = 0; k < n; k = k + 1)
        instruction_memory[4 + k] = load(5'd5 + (k % 8), 5'd1, 4 * (k % 4));
      run_program("aciertos");
    end
  endtask

  // 16 pares STORE (a 0x500 + 16k: una linea nueva cada vez, asi que cada uno
  // sale al puerto) y, con `with_load`, un LOAD que acierta en 0x300.
  task measure_store_load(input integer with_load);
    begin
      for (k = 0; k < WORDS; k = k + 1) instruction_memory[k] = HALT;
      instruction_memory[0] = movi(5'd1, 16'h0300);
      instruction_memory[1] = movi(5'd2, 16'h0500);
      instruction_memory[2] = addi(5'd0, 5'd0, 16'd0);
      instruction_memory[3] = load(5'd4, 5'd1, 16'd0);   // falla: trae la linea
      for (k = 0; k < 16; k = k + 1) begin
        instruction_memory[4 + 2 * k] = store(5'd1, 5'd2, 16 * k);
        instruction_memory[5 + 2 * k] = with_load ? load(5'd5 + (k % 8), 5'd1, 4 * (k % 4))
                                                  : addi(5'd0, 5'd0, 16'd0);
      end
      run_program("tras store");
    end
  endtask

  // Ciclos con la CPU en marcha y de ellos, los de EX ocupado con memoria.
  integer run_cycles = 0, ex_mem_cycles = 0;
  always @(posedge clk) begin
    if (reset) begin
      run_cycles <= 0;
      ex_mem_cycles <= 0;
    end else begin
      if (!halted) run_cycles <= run_cycles + 1;
      if (perf_stall[0]) ex_mem_cycles <= ex_mem_cycles + 1;
    end
  end

  task run_program(input [8*12-1:0] name);
    begin
      @(negedge clk); reset = 1'b1;
      repeat (2) @(negedge clk); reset = 1'b0;
      @(negedge clk); run_request = 1'b1;
      @(negedge clk); run_request = 1'b0;
      wait (!halted);
      wait (halted);
      // Lo que hace el monitor antes de leer: esperar a `wb_dirty`.
      t = 0;
      @(negedge clk);
      while (wb_dirty && t < 2000) begin @(negedge clk); t = t + 1; end
      if (wb_dirty) begin errors = errors + 1; $display("FALLO %0s: wb_dirty no baja", name); end
      if (error) begin errors = errors + 1; $display("FALLO %0s: error %02x en %08x", name, error_code, debug_pc); end
    end
  endtask

  initial begin
    #10_000_000;
    $display("FAIL: cpu_data_path (timeout)");
    $finish;
  end

  initial begin
    for (i = 0; i < 4096; i = i + 1) memory[i] = 8'h00;

    // 1) Como program-fibonacci: un STORE por vuelta de siete instrucciones.
    //    R1 = valor (vuelta + 1), R3 = puntero 0x200, R4 = vueltas.
    for (k = 0; k < WORDS; k = k + 1) instruction_memory[k] = HALT;
    instruction_memory[0] = movi(5'd1, 16'd1);
    instruction_memory[1] = movi(5'd3, 16'h0200);
    instruction_memory[2] = movi(5'd4, 16'd10);
    instruction_memory[3] = store(5'd1, 5'd3, 16'd0);
    instruction_memory[4] = addi(5'd1, 5'd1, 16'd1);
    instruction_memory[5] = addi(5'd3, 5'd3, 16'd4);
    instruction_memory[6] = addi(5'd4, 5'd4, 16'hffff);
    instruction_memory[7] = bne(5'd4, 5'd0, 16'hfffb);   // a la palabra 3
    run_program("stores");
    for (k = 0; k < 10; k = k + 1)
      if (mem_word(32'h200 + 4 * k) !== k + 1) begin
        errors = errors + 1;
        $display("FALLO stores: memoria[%h] = %0d, esperaba %0d", 32'h200 + 4 * k,
                 mem_word(32'h200 + 4 * k), k + 1);
      end

    // 2) Copia: LOAD de 0x300 y STORE a 0x400, palabra a palabra.
    for (k = 0; k < 16; k = k + 1) begin
      {memory[32'h300 + 4*k + 3], memory[32'h300 + 4*k + 2],
       memory[32'h300 + 4*k + 1], memory[32'h300 + 4*k]} = 32'hC0DE_0000 + k;
    end
    for (k = 0; k < WORDS; k = k + 1) instruction_memory[k] = HALT;
    instruction_memory[0] = movi(5'd1, 16'h0300);
    instruction_memory[1] = movi(5'd2, 16'h0400);
    instruction_memory[2] = movi(5'd4, 16'd16);
    instruction_memory[3] = load(5'd5, 5'd1, 16'd0);
    instruction_memory[4] = store(5'd5, 5'd2, 16'd0);
    instruction_memory[5] = addi(5'd1, 5'd1, 16'd4);
    instruction_memory[6] = addi(5'd2, 5'd2, 16'd4);
    instruction_memory[7] = addi(5'd4, 5'd4, 16'hffff);
    instruction_memory[8] = bne(5'd4, 5'd0, 16'hfffa);   // a la palabra 3
    run_program("copia");
    for (k = 0; k < 16; k = k + 1)
      if (mem_word(32'h400 + 4 * k) !== 32'hC0DE_0000 + k) begin
        errors = errors + 1;
        $display("FALLO copia: memoria[%h] = %h, esperaba %h", 32'h400 + 4 * k,
                 mem_word(32'h400 + 4 * k), 32'hC0DE_0000 + k);
      end

    // 3) Coste de un acierto. Un LOAD frio a 0x300 (falla y trae la linea) y
    //    despues `n` LOAD a la misma linea, a registros distintos que nadie
    //    lee: sin dependencias, solo la D-cache.
    measure_hits(0);
    base_ex_mem = ex_mem_cycles; base_cycles = run_cycles;
    measure_hits(32);
    $display("PERF acierto: %0.2f ciclos de EX con memoria por LOAD (%0.2f de CPU)",
             (ex_mem_cycles - base_ex_mem) / 32.0, (run_cycles - base_cycles) / 32.0);

    // 4) Un LOAD que acierta justo detras de un STORE que sale sin esperar.
    measure_store_load(0);
    base_ex_mem = ex_mem_cycles; base_cycles = run_cycles;
    measure_store_load(1);
    $display("PERF acierto tras STORE: %0.2f ciclos de EX con memoria por LOAD (%0.2f de CPU)",
             (ex_mem_cycles - base_ex_mem) / 16.0, (run_cycles - base_cycles) / 16.0);

    if (errors == 0) $display("PASS: cpu_data_path");
    else             $display("FAIL: cpu_data_path (%0d errores)", errors);
    $finish;
  end
endmodule

`default_nettype wire
