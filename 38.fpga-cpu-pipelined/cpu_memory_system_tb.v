`timescale 1ns / 1ps
`default_nettype none

/*
 * El camino de datos de la placa entero, sin modelos de por medio:
 *
 *   cpu.v -> dcache.v -> cpu_dmem_adapter.v -> fabric_fifo_bridge (25 -> 100 MHz)
 *         -> memory_fabric_fifo_6 -> sdram_controller_128 -> sdram_model
 *
 * Solo las instrucciones salen de un modelo que acierta siempre, y los puertos
 * 1-5 del fabric estan vacios. Para comprobar no se mira el modelo de SDRAM:
 * un segundo programa, tras parar (lo que invalida la D-cache), vuelve a leer
 * las palabras con la CPU y se miran los registros.
 *
 * Nacio porque el adaptador con volcados sin esperar pasaba su banco (con un
 * modelo del puerto) y en placa perdia la primera palabra de cada linea nueva.
 */
module cpu_memory_system_tb;
  reg clk = 1'b0;       // CPU, 25 MHz
  reg clk_mem = 1'b0;   // SDRAM, 100 MHz
  always #20 clk = ~clk;
  always #5 clk_mem = ~clk_mem;
  reg reset = 1'b1;
  reg reset_mem = 1'b1;
  reg run_request = 1'b0;
  // Como en top.v: la CPU recibe ademas `cpu_reset_request` (el RESET del
  // monitor entre programas); D-cache, adaptador y puente solo el del sistema.
  // Resetear el lado CPU del puente asincrono sin el de memoria descuadra sus
  // punteros.
  reg cpu_reset_request = 1'b0;

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
  reg [4:0] debug_register_address = 5'd0;

  wire c_valid, c_ready, c_rvalid, c_error;
  wire [31:0] c_address, c_wdata, c_rdata;
  wire [3:0] c_wen;

  cpu cpu_i(
      .clk(clk), .reset(reset), .soft_reset(cpu_reset_request), .run_request(run_request), .halt_request(1'b0),
      .step_request(1'b0), .halted(halted), .error(error), .error_code(error_code),
      .instruction_retired(instruction_retired),
      .imem_valid(imem_valid), .imem_address(imem_address),
      .imem_read_data(imem_read_data), .imem_ready(1'b1), .imem_rvalid(imem_rvalid),
      .dmem_valid(c_valid), .dmem_address(c_address), .dmem_write_data(c_wdata),
      .dmem_write_enable(c_wen), .dmem_read_data(c_rdata), .dmem_ready(c_ready),
      .dmem_rvalid(c_rvalid), .dmem_error(c_error), .dmem_waiting(dmem_waiting),
      .debug_register_address(debug_register_address),
      .debug_register_data(debug_register_data), .debug_pc(debug_pc),
      .perf_stall());

  // Memoria de instrucciones: contesta al ciclo siguiente o, con imem_slow,
  // cuatro despues, como un fallo corto de la I-cache. Tampoco ve el RESET de
  // la CPU: lo que acepto antes lo contesta despues.
  reg [31:0] instruction_memory[0:WORDS-1];
  reg imem_slow = 1'b0;
  reg [2:0] imem_delay_valid = 3'b000;
  reg [31:0] imem_delay_data[0:2];
  always @(posedge clk) begin
    imem_delay_valid <= {imem_delay_valid[1:0], imem_valid};
    imem_delay_data[0] <= instruction_memory[imem_address[9:2]];
    imem_delay_data[1] <= imem_delay_data[0];
    imem_delay_data[2] <= imem_delay_data[1];
    imem_rvalid <= imem_slow ? imem_delay_valid[2] : imem_valid;
    imem_read_data <= imem_slow ? imem_delay_data[2] : instruction_memory[imem_address[9:2]];
  end

  // -- D-cache y adaptador -------------------------------------------------------
  wire a_valid, a_ready, a_rvalid, a_error;
  wire [31:0] a_address, a_wdata, a_rdata;
  wire [3:0] a_wen;
  wire [127:0] a_line;
  wire init_done_mem;
  reg init_done_s1 = 1'b0, init_done = 1'b0;
  always @(posedge clk) begin init_done_s1 <= init_done_mem; init_done <= init_done_s1; end

  dcache #(.LINES(16), .INDEX_BITS(4)) dcache_i(
      .clk(clk), .reset(reset), .invalidate(halted),
      .cpu_valid(c_valid), .cpu_address(c_address), .cpu_write_data(c_wdata),
      .cpu_write_enable(c_wen), .cpu_ready(c_ready), .cpu_read_data(c_rdata),
      .cpu_rvalid(c_rvalid), .cpu_error(c_error),
      .mem_valid(a_valid), .mem_address(a_address), .mem_write_data(a_wdata),
      .mem_write_enable(a_wen), .mem_ready(a_ready), .mem_read_data(a_rdata),
      .mem_read_line(a_line), .mem_rvalid(a_rvalid), .mem_error(a_error),
      .hit_event(), .miss_event());

  wire p_valid, p_ready, p_write, p_rsp_valid, p_rsp_ready, p_rsp_error, wb_dirty;
  wire [31:0] p_addr;
  wire [127:0] p_wdata, p_rsp_rdata;
  wire [15:0] p_wmask;

  cpu_dmem_adapter adapter_i(
      .clk(clk), .reset(reset), .init_done(init_done), .cpu_halted(halted),
      .dmem_valid(a_valid), .dmem_address(a_address), .dmem_write_data(a_wdata),
      .dmem_write_enable(a_wen), .dmem_ready(a_ready), .dmem_read_data(a_rdata),
      .dmem_read_line(a_line), .dmem_rvalid(a_rvalid), .dmem_error(a_error),
      .wb_dirty(wb_dirty),
      .mmio_req(), .mmio_ack(1'b0), .mmio_write(), .mmio_write_mask(),
      .mmio_address(), .mmio_write_data(), .mmio_read_data(32'd0), .mmio_error(1'b0),
      .req_valid(p_valid), .req_ready(p_ready), .req_write(p_write),
      .req_addr(p_addr), .req_wdata(p_wdata), .req_wmask(p_wmask),
      .rsp_valid(p_rsp_valid), .rsp_ready(p_rsp_ready), .rsp_rdata(p_rsp_rdata),
      .rsp_error(p_rsp_error), .merge_count(), .flush_count());

  // -- Puente, fabric, controlador y SDRAM, como en top.v ----------------------
  wire req_empty0, req_rd_en0, req_rd_valid0, rsp_full0, rsp_wr_en0;
  wire [177:0] req_data0;
  wire [128:0] rsp_data0;

  fabric_fifo_bridge #(.FIFO_ADDR_WIDTH(2)) bridge_i(
      .master_clk(clk), .master_reset(reset),
      .req_valid(p_valid), .req_ready(p_ready), .req_urgent(1'b0),
      .req_write(p_write), .req_addr(p_addr), .req_wdata(p_wdata), .req_wmask(p_wmask),
      .rsp_valid(p_rsp_valid), .rsp_ready(p_rsp_ready), .rsp_rdata(p_rsp_rdata),
      .rsp_error(p_rsp_error),
      .mem_clk(clk_mem), .mem_reset(reset_mem),
      .mem_req_empty(req_empty0), .mem_req_rd_en(req_rd_en0),
      .mem_req_rd_valid(req_rd_valid0), .mem_req_data(req_data0),
      .mem_rsp_full(rsp_full0), .mem_rsp_wr_en(rsp_wr_en0), .mem_rsp_data(rsp_data0),
      .dbg_req_ptrs());

  // -- Trafico de fondo: los dos memory_traffic_gen de top.v (puertos 4 y 5),
  // siempre activos, en regiones bajas porque el modelo de SDRAM solo tiene 32
  // filas. Con ellos la latencia del puerto 0 sube y el adaptador llega a
  // tener varias peticiones dentro, como en la placa.
  reg traffic_enable = 1'b0;
  wire [1:0] g_valid, g_ready, g_urgent, g_write, g_rsp_valid, g_rsp_ready, g_rsp_error;
  wire [1:0] g_mismatch;
  wire [31:0] g_addr[0:1];
  wire [127:0] g_wdata[0:1], g_rsp_rdata[0:1];
  wire [15:0] g_wmask[0:1];
  wire [1:0] g_req_empty, g_req_rd_en, g_req_rd_valid, g_rsp_full, g_rsp_wr_en;
  wire [177:0] g_req_data[0:1];
  wire [128:0] g_rsp_data[0:1];
  genvar gi;
  generate
    for (gi = 0; gi < 2; gi = gi + 1) begin : g_traffic
      memory_traffic_gen #(.BASE_ADDR(32'h0001_0000 + gi * 32'h0000_4000),
                           .REGION_SIZE(32'h0000_4000),
                           .SEED(32'h1111_1111 + gi * 32'h1111_1111)) gen_i(
          .clk(clk), .reset(reset), .enable(traffic_enable), .urgent_enable(1'b0),
          .clear_stats(1'b0),
          .req_valid(g_valid[gi]), .req_ready(g_ready[gi]), .req_urgent(g_urgent[gi]),
          .req_write(g_write[gi]), .req_addr(g_addr[gi]), .req_wdata(g_wdata[gi]),
          .req_wmask(g_wmask[gi]), .rsp_valid(g_rsp_valid[gi]), .rsp_ready(g_rsp_ready[gi]),
          .rsp_rdata(g_rsp_rdata[gi]), .rsp_error(g_rsp_error[gi]),
          .active(), .request_count(), .write_count(), .read_count(),
          .response_error_count(), .mismatch_count(), .response_error_seen(),
          .mismatch_seen(g_mismatch[gi]), .current_addr(), .loop_count(),
          .last_error_addr(), .last_expected(), .last_received());
      fabric_fifo_bridge #(.FIFO_ADDR_WIDTH(2)) gbridge_i(
          .master_clk(clk), .master_reset(reset),
          .req_valid(g_valid[gi]), .req_ready(g_ready[gi]), .req_urgent(g_urgent[gi]),
          .req_write(g_write[gi]), .req_addr(g_addr[gi]), .req_wdata(g_wdata[gi]),
          .req_wmask(g_wmask[gi]),
          .rsp_valid(g_rsp_valid[gi]), .rsp_ready(g_rsp_ready[gi]),
          .rsp_rdata(g_rsp_rdata[gi]), .rsp_error(g_rsp_error[gi]),
          .mem_clk(clk_mem), .mem_reset(reset_mem),
          .mem_req_empty(g_req_empty[gi]), .mem_req_rd_en(g_req_rd_en[gi]),
          .mem_req_rd_valid(g_req_rd_valid[gi]), .mem_req_data(g_req_data[gi]),
          .mem_rsp_full(g_rsp_full[gi]), .mem_rsp_wr_en(g_rsp_wr_en[gi]),
          .mem_rsp_data(g_rsp_data[gi]), .dbg_req_ptrs());
    end
  endgenerate

  wire fab_req_valid, fab_req_ready, fab_req_write, fab_done, fabric_busy;
  wire [23:0] fab_req_addr;
  wire [127:0] fab_req_wdata, fab_rdata;
  wire [15:0] fab_req_wmask;

  memory_fabric_fifo_6 fabric_i(
      .clk(clk_mem), .reset(reset_mem),
      .p0_req_empty(req_empty0), .p0_req_rd_en(req_rd_en0), .p0_req_rd_valid(req_rd_valid0),
      .p0_req_data(req_data0), .p0_rsp_full(rsp_full0), .p0_rsp_wr_en(rsp_wr_en0),
      .p0_rsp_data(rsp_data0),
      .p1_req_empty(1'b1), .p1_req_rd_en(), .p1_req_rd_valid(1'b0), .p1_req_data(178'd0),
      .p1_rsp_full(1'b0), .p1_rsp_wr_en(), .p1_rsp_data(),
      .p2_req_empty(1'b1), .p2_req_rd_en(), .p2_req_rd_valid(1'b0), .p2_req_data(178'd0),
      .p2_rsp_full(1'b0), .p2_rsp_wr_en(), .p2_rsp_data(),
      .p3_req_empty(1'b1), .p3_req_rd_en(), .p3_req_rd_valid(1'b0), .p3_req_data(178'd0),
      .p3_rsp_full(1'b0), .p3_rsp_wr_en(), .p3_rsp_data(),
      .p4_req_empty(g_req_empty[0]), .p4_req_rd_en(g_req_rd_en[0]),
      .p4_req_rd_valid(g_req_rd_valid[0]), .p4_req_data(g_req_data[0]),
      .p4_rsp_full(g_rsp_full[0]), .p4_rsp_wr_en(g_rsp_wr_en[0]), .p4_rsp_data(g_rsp_data[0]),
      .p5_req_empty(g_req_empty[1]), .p5_req_rd_en(g_req_rd_en[1]),
      .p5_req_rd_valid(g_req_rd_valid[1]), .p5_req_data(g_req_data[1]),
      .p5_rsp_full(g_rsp_full[1]), .p5_rsp_wr_en(g_rsp_wr_en[1]), .p5_rsp_data(g_rsp_data[1]),
      .sdram_req_valid(fab_req_valid), .sdram_req_ready(fab_req_ready),
      .sdram_req_write(fab_req_write), .sdram_req_addr(fab_req_addr),
      .sdram_req_wdata(fab_req_wdata), .sdram_req_wmask(fab_req_wmask),
      .sdram_done(fab_done), .sdram_rdata(fab_rdata), .busy(fabric_busy),
      .dbg_trace_idx(5'd0));

  wire cke, csn, rasn, casn, wen, sdram_busy;
  wire [12:0] sa;
  wire [1:0] sba, dqm;
  wire [15:0] dq;

  sdram_controller_128 #(.CLK_FREQ_HZ(100_000_000), .POWERUP_DELAY_US(2),
                         .READ_DELAY_CYCLES(2)) controller_i(
      .clk(clk_mem), .reset(reset_mem),
      .req_valid(fab_req_valid), .req_write(fab_req_write), .req_addr(fab_req_addr),
      .req_wdata(fab_req_wdata), .req_wmask(fab_req_wmask), .req_ready(fab_req_ready),
      .done(fab_done), .rdata(fab_rdata), .init_done(init_done_mem), .busy(sdram_busy),
      .sdram_clk(), .sdram_cke(cke), .sdram_csn(csn), .sdram_rasn(rasn),
      .sdram_casn(casn), .sdram_wen(wen), .sdram_a(sa), .sdram_ba(sba),
      .sdram_dqm(dqm), .sdram_d(dq));

  sdram_model #(.POWERUP_DELAY_NS(2000), .READ_DELAY_CYCLES(0)) sdram_i(
      .clk(clk_mem), .cke(cke), .csn(csn), .rasn(rasn), .casn(casn),
      .wen(wen), .a(sa), .ba(sba), .dqm(dqm), .dq(dq));

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
  integer k, t, round;

  task run_program(input [8*12-1:0] name);
    begin
      @(negedge clk); run_request = 1'b1;
      @(negedge clk); run_request = 1'b0;
      wait (!halted);
      wait (halted);
      t = 0;
      @(negedge clk);
      while (wb_dirty && t < 2000) begin @(negedge clk); t = t + 1; end
      if (wb_dirty) begin errors = errors + 1; $display("FALLO %0s: wb_dirty no baja", name); end
      if (error) begin errors = errors + 1; $display("FALLO %0s: error %02x en %08x", name, error_code, debug_pc); end
    end
  endtask

  // Un reset de CPU entre programas, como el arnes de la placa.
  task cpu_reset;
    begin
      @(negedge clk); cpu_reset_request = 1'b1;
      repeat (2) @(negedge clk); cpu_reset_request = 1'b0;
      repeat (2) @(negedge clk);
    end
  endtask

  task expect_register(input [4:0] r, input [31:0] expected, input [8*12-1:0] name);
    begin
      debug_register_address = r;
      repeat (2) @(posedge clk); #1;
      if (debug_register_data !== expected) begin
        errors = errors + 1;
        $display("FALLO %0s: R%0d = %h, esperaba %h", name, r, debug_register_data, expected);
      end
    end
  endtask

  // Lee 10 palabras desde `base` en R10..R19 y para.
  task readback(input [15:0] base);
    begin
      for (k = 0; k < WORDS; k = k + 1) instruction_memory[k] = HALT;
      instruction_memory[0] = movi(5'd1, base);
      for (k = 0; k < 10; k = k + 1)
        instruction_memory[1 + k] = load(5'd10 + k, 5'd1, 4 * k);
      cpu_reset;
      run_program("lectura");
    end
  endtask

  initial begin
    #400_000;
    $display("FAIL: cpu_memory_system (timeout)");
    $finish;
  end

  initial begin
    repeat (4) @(posedge clk);
    reset_mem = 1'b0;
    reset = 1'b0;
    wait (init_done);
    traffic_enable = 1'b1;
    repeat (4) @(posedge clk);

    // 1) Como program-fibonacci: un STORE por vuelta, valor vuelta + 1.
    for (k = 0; k < WORDS; k = k + 1) instruction_memory[k] = HALT;
    instruction_memory[0] = movi(5'd1, 16'd1);
    instruction_memory[1] = movi(5'd3, 16'h0200);
    instruction_memory[2] = movi(5'd4, 16'd10);
    instruction_memory[3] = store(5'd1, 5'd3, 16'd0);
    instruction_memory[4] = addi(5'd1, 5'd1, 16'd1);
    instruction_memory[5] = addi(5'd3, 5'd3, 16'd4);
    instruction_memory[6] = addi(5'd4, 5'd4, 16'hffff);
    instruction_memory[7] = bne(5'd4, 5'd0, 16'hfffb);   // a la palabra 3
    cpu_reset;
    run_program("stores");
    readback(16'h0200);
    for (k = 0; k < 10; k = k + 1) expect_register(5'd10 + k, k + 1, "stores");

    // 2) Como wc-stride16: un STORE por linea de 16 bytes, cada uno crea
    //    linea y vuelca la anterior. En placa se perdia uno de cada dos.
    for (k = 0; k < WORDS; k = k + 1) instruction_memory[k] = HALT;
    instruction_memory[0] = movi(5'd1, 16'd1);
    instruction_memory[1] = movi(5'd3, 16'h0500);
    instruction_memory[2] = movi(5'd4, 16'd8);
    instruction_memory[3] = store(5'd1, 5'd3, 16'd0);
    instruction_memory[4] = addi(5'd1, 5'd1, 16'd1);
    instruction_memory[5] = addi(5'd3, 5'd3, 16'd16);
    instruction_memory[6] = addi(5'd4, 5'd4, 16'hffff);
    instruction_memory[7] = bne(5'd4, 5'd0, 16'hfffb);   // a la palabra 3
    cpu_reset;
    run_program("stride16");
    for (k = 0; k < WORDS; k = k + 1) instruction_memory[k] = HALT;
    instruction_memory[0] = movi(5'd1, 16'h0500);
    for (k = 0; k < 8; k = k + 1)
      instruction_memory[1 + k] = load(5'd10 + k, 5'd1, 16 * k);
    cpu_reset;
    run_program("lectura16");
    for (k = 0; k < 8; k = k + 1) expect_register(5'd10 + k, k + 1, "stride16");

    // 3) RESET de la CPU con un programa corriendo, como board-load: la
    //    I-cache (lenta aqui) y la D-cache (LOADs que fallan) aun deben
    //    respuestas, que la CPU tiene que descartar. Antes se las tomaba por
    //    nuevas y se quedaba sin pedir instrucciones (0 retiradas en placa).
    //    Despues relee lo que escribio el caso 1.
    imem_slow = 1'b1;
    for (round = 0; round < 8; round = round + 1) begin
      for (k = 0; k < WORDS; k = k + 1) instruction_memory[k] = HALT;
      instruction_memory[0] = movi(5'd1, 16'h0800);
      instruction_memory[1] = load(5'd5, 5'd1, 16'd0);
      instruction_memory[2] = addi(5'd1, 5'd1, 16'd16);
      instruction_memory[3] = bne(5'd1, 5'd0, 16'hfffd);   // a la palabra 1
      cpu_reset;
      @(negedge clk); run_request = 1'b1;
      @(negedge clk); run_request = 1'b0;
      repeat (60 + 7 * round) @(negedge clk);
      readback(16'h0200);
      for (k = 0; k < 10; k = k + 1) expect_register(5'd10 + k, k + 1, "reset vivo");
    end
    imem_slow = 1'b0;

    if (g_mismatch != 2'b00) begin
      errors = errors + 1; $display("FALLO: los generadores de trafico vieron datos malos (%b)", g_mismatch);
    end
    if (errors == 0) $display("PASS: cpu_memory_system");
    else             $display("FAIL: cpu_memory_system (%0d errores)", errors);
    $finish;
  end
endmodule

`default_nettype wire
