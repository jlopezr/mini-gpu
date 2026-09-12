`timescale 1ns/1ps
`default_nettype none

/*
 * Banco de sistema del camino de rafagas.
 *
 * Monta lo mismo que top.v, sin el dominio de pixel: CPU, bufer de
 * instrucciones, adaptador de datos, adaptador de monitor, mux de MMIO,
 * memory_fabric_4, sdram_controller_128 y el modelo de SDRAM. Lo que NO monta
 * es el subsistema de video, porque su cadena ya la cubre video_burst_tb.v y
 * aqui estorbaria para medir el coste propio de la CPU.
 *
 * Hace dos cosas que ningun otro banco hace:
 *
 *   1. Comprueba el flujo completo del monitor: cargar un programa byte a byte
 *      con la CPU parada, arrancarla, dejar que escriba memoria, pararla y
 *      volver a leer lo que escribio. Es el camino que rompe una incoherencia
 *      de bufer, y el que se queda mudo si se pierde el pulso del monitor.
 *
 *   2. Mide el bucle interior real sobre el camino nuevo y lo compara con la
 *      cifra de la 16, que perf_probe_tb.v deja en 145,9 ciclos por palabra sin
 *      video. Sin esta medida, la integracion podria estar funcionando y siendo
 *      mas lenta, que es justo lo que no se quiere.
 */
module cpu_burst_system_tb;
  localparam integer CLK_HZ = 100_000_000;
  localparam integer POWERUP_US = 2;
  localparam integer ITERATIONS = 160;
  // La linea base de la 16, medida por perf_probe_tb.v en el mismo bucle.
  localparam integer BASE_CYCLES_PER_WORD = 146;

  reg clk = 0;
  reg reset = 1;
  always #5 clk = ~clk;

  integer errors = 0;
  integer guard;
  integer i;

  // -- CPU ------------------------------------------------------------------
  reg run_request = 0, halt_request = 0;
  wire halted, cpu_error, instruction_retired;
  wire [7:0] cpu_error_code;
  wire imem_valid, imem_ready;
  wire [31:0] imem_address, imem_read_data;
  wire dmem_valid, dmem_ready, dmem_error;
  wire [31:0] dmem_address, dmem_write_data, dmem_read_data;
  wire [3:0] dmem_write_enable;
  reg [4:0] debug_register_address = 0;
  wire [31:0] debug_register_data, debug_pc;

  cpu cpu_i (
      .clk(clk), .reset(reset), .run_request(run_request),
      .halt_request(halt_request), .step_request(1'b0), .halted(halted),
      .error(cpu_error), .error_code(cpu_error_code),
      .instruction_retired(instruction_retired),
      .imem_valid(imem_valid), .imem_address(imem_address),
      .imem_read_data(imem_read_data), .imem_ready(imem_ready),
      .dmem_valid(dmem_valid), .dmem_address(dmem_address),
      .dmem_write_data(dmem_write_data), .dmem_write_enable(dmem_write_enable),
      .dmem_read_data(dmem_read_data), .dmem_ready(dmem_ready),
      .dmem_error(dmem_error),
      .debug_register_address(debug_register_address),
      .debug_register_data(debug_register_data), .debug_pc(debug_pc));

  // -- Monitor (lo emula el banco, byte a byte y con pulso de un ciclo) ------
  reg [31:0] mon_address = 0;
  reg [7:0] mon_write_data = 0;
  reg mon_write_enable = 0, mon_read_enable = 0;
  wire [7:0] mon_read_data;
  wire mon_ready, mon_error;

  // -- Puertos del arbitro --------------------------------------------------
  wire p0_valid, p0_ready, p0_write, p0_rsp_valid, p0_rsp_ready, p0_rsp_error;
  wire [31:0] p0_addr;
  wire [127:0] p0_wdata, p0_rsp_rdata;
  wire [15:0] p0_wmask;

  wire p1_valid, p1_ready, p1_write, p1_rsp_valid, p1_rsp_ready, p1_rsp_error;
  wire [31:0] p1_addr;
  wire [127:0] p1_wdata, p1_rsp_rdata;
  wire [15:0] p1_wmask;

  wire p3_valid, p3_ready, p3_write, p3_rsp_valid, p3_rsp_ready, p3_rsp_error;
  wire [31:0] p3_addr;
  wire [127:0] p3_wdata, p3_rsp_rdata;
  wire [15:0] p3_wmask;

  // -- MMIO -----------------------------------------------------------------
  wire mon_mmio_req, mon_mmio_ack, mon_mmio_write;
  wire [3:0] mon_mmio_mask, mon_mmio_addr;
  wire [31:0] mon_mmio_wdata;
  wire cpu_mmio_req, cpu_mmio_ack, cpu_mmio_write;
  wire [3:0] cpu_mmio_mask, cpu_mmio_addr;
  wire [31:0] cpu_mmio_wdata;
  wire mmio_select, mmio_write;
  wire [3:0] mmio_write_mask, mmio_address;
  wire [31:0] mmio_write_data;
  wire [31:0] ibuf_hits, ibuf_misses;

  // Registros de video reducidos a lo imprescindible: este banco solo necesita
  // que la ventana responda, no el swap sincronizado, que ya cubre
  // video_registers_tb.v.
  reg [31:0] mmio_regs[0:3];
  wire [31:0] mmio_read_data = mmio_regs[mmio_address[3:2]];
  always @(posedge clk) begin
    if (reset) begin
      mmio_regs[0] <= 32'h0100_0000;
      mmio_regs[1] <= 32'h0102_5800;
      mmio_regs[2] <= 32'd0;
      mmio_regs[3] <= 32'd0;
    end else if (mmio_select && mmio_write) begin
      for (i = 0; i < 4; i = i + 1)
        if (mmio_write_mask[i])
          mmio_regs[mmio_address[3:2]][i*8 +: 8] <= mmio_write_data[i*8 +: 8];
    end
  end

  // -- SDRAM ----------------------------------------------------------------
  wire s_req_valid, s_req_ready, s_req_write, s_done;
  wire [23:0] s_req_addr;
  wire [127:0] s_req_wdata, s_rdata;
  wire [15:0] s_req_wmask;
  wire init_done, ctrl_busy, fabric_busy, sdram_clk_unused;
  wire cke, csn, rasn, casn, wen;
  wire [12:0] sdram_a;
  wire [1:0] sdram_ba, sdram_dqm;
  wire [15:0] sdram_dq;

  cpu_dmem_adapter dmem_adapter_i (
      .clk(clk), .reset(reset), .init_done(init_done),
      .dmem_valid(dmem_valid), .dmem_address(dmem_address),
      .dmem_write_data(dmem_write_data),
      .dmem_write_enable(dmem_write_enable),
      .dmem_read_data(dmem_read_data), .dmem_ready(dmem_ready),
      .dmem_error(dmem_error),
      .mmio_req(cpu_mmio_req), .mmio_ack(cpu_mmio_ack),
      .mmio_write(cpu_mmio_write), .mmio_write_mask(cpu_mmio_mask),
      .mmio_address(cpu_mmio_addr), .mmio_write_data(cpu_mmio_wdata),
      .mmio_read_data(mmio_read_data),
      .req_valid(p0_valid), .req_ready(p0_ready), .req_write(p0_write),
      .req_addr(p0_addr), .req_wdata(p0_wdata), .req_wmask(p0_wmask),
      .rsp_valid(p0_rsp_valid), .rsp_ready(p0_rsp_ready),
      .rsp_rdata(p0_rsp_rdata), .rsp_error(p0_rsp_error));

  instruction_buffer #(.LINES(4), .INDEX_BITS(2)) ibuf_i (
      .clk(clk), .reset(reset), .init_done(init_done), .cpu_halted(halted),
      .cpu_imem_valid(imem_valid), .cpu_imem_address(imem_address),
      .cpu_imem_read_data(imem_read_data), .cpu_imem_ready(imem_ready),
      .req_valid(p1_valid), .req_ready(p1_ready), .req_write(p1_write),
      .req_addr(p1_addr), .req_wdata(p1_wdata), .req_wmask(p1_wmask),
      .rsp_valid(p1_rsp_valid), .rsp_ready(p1_rsp_ready),
      .rsp_rdata(p1_rsp_rdata), .rsp_error(p1_rsp_error),
      .hit_count(ibuf_hits), .miss_count(ibuf_misses));

  monitor_mem_adapter_128 monitor_adapter_i (
      .clk(clk), .reset(reset), .init_done(init_done), .cpu_halted(halted),
      .mem_address(mon_address), .mem_write_data(mon_write_data),
      .mem_write_enable(mon_write_enable), .mem_read_enable(mon_read_enable),
      .mem_read_data(mon_read_data), .mem_ready(mon_ready),
      .mem_error(mon_error),
      .mmio_req(mon_mmio_req), .mmio_ack(mon_mmio_ack),
      .mmio_write(mon_mmio_write), .mmio_write_mask(mon_mmio_mask),
      .mmio_address(mon_mmio_addr), .mmio_write_data(mon_mmio_wdata),
      .mmio_read_data(mmio_read_data),
      .req_valid(p3_valid), .req_ready(p3_ready), .req_write(p3_write),
      .req_addr(p3_addr), .req_wdata(p3_wdata), .req_wmask(p3_wmask),
      .rsp_valid(p3_rsp_valid), .rsp_ready(p3_rsp_ready),
      .rsp_rdata(p3_rsp_rdata), .rsp_error(p3_rsp_error));

  mmio_mux mmio_mux_i (
      .clk(clk), .reset(reset),
      .a_req(mon_mmio_req), .a_ack(mon_mmio_ack), .a_write(mon_mmio_write),
      .a_write_mask(mon_mmio_mask), .a_address(mon_mmio_addr),
      .a_write_data(mon_mmio_wdata),
      .b_req(cpu_mmio_req), .b_ack(cpu_mmio_ack), .b_write(cpu_mmio_write),
      .b_write_mask(cpu_mmio_mask), .b_address(cpu_mmio_addr),
      .b_write_data(cpu_mmio_wdata),
      .select(mmio_select), .write(mmio_write),
      .write_mask(mmio_write_mask), .address(mmio_address),
      .write_data(mmio_write_data));

  memory_fabric_4 fabric_i (
      .clk(clk), .reset(reset),
      .p0_req_valid(p0_valid), .p0_req_ready(p0_ready),
      .p0_req_write(p0_write), .p0_req_addr(p0_addr),
      .p0_req_wdata(p0_wdata), .p0_req_wmask(p0_wmask),
      .p0_rsp_valid(p0_rsp_valid), .p0_rsp_ready(p0_rsp_ready),
      .p0_rsp_rdata(p0_rsp_rdata), .p0_rsp_error(p0_rsp_error),

      .p1_req_valid(p1_valid), .p1_req_ready(p1_ready),
      .p1_req_write(p1_write), .p1_req_addr(p1_addr),
      .p1_req_wdata(p1_wdata), .p1_req_wmask(p1_wmask),
      .p1_rsp_valid(p1_rsp_valid), .p1_rsp_ready(p1_rsp_ready),
      .p1_rsp_rdata(p1_rsp_rdata), .p1_rsp_error(p1_rsp_error),

      .p2_req_valid(1'b0), .p2_req_ready(), .p2_req_write(1'b0),
      .p2_req_addr(32'd0), .p2_req_wdata(128'd0), .p2_req_wmask(16'd0),
      .p2_urgent(1'b0), .p2_rsp_valid(), .p2_rsp_ready(1'b1),
      .p2_rsp_rdata(), .p2_rsp_error(),

      .p3_req_valid(p3_valid), .p3_req_ready(p3_ready),
      .p3_req_write(p3_write), .p3_req_addr(p3_addr),
      .p3_req_wdata(p3_wdata), .p3_req_wmask(p3_wmask),
      .p3_rsp_valid(p3_rsp_valid), .p3_rsp_ready(p3_rsp_ready),
      .p3_rsp_rdata(p3_rsp_rdata), .p3_rsp_error(p3_rsp_error),

      .sdram_req_valid(s_req_valid), .sdram_req_ready(s_req_ready),
      .sdram_req_write(s_req_write), .sdram_req_addr(s_req_addr),
      .sdram_req_wdata(s_req_wdata), .sdram_req_wmask(s_req_wmask),
      .sdram_done(s_done), .sdram_rdata(s_rdata), .busy(fabric_busy));

  sdram_controller_128 #(
      .CLK_FREQ_HZ(CLK_HZ), .POWERUP_DELAY_US(POWERUP_US)
  ) ctrl (
      .clk(clk), .reset(reset),
      .req_valid(s_req_valid), .req_write(s_req_write), .req_addr(s_req_addr),
      .req_wdata(s_req_wdata), .req_wmask(s_req_wmask),
      .req_ready(s_req_ready), .done(s_done), .rdata(s_rdata),
      .init_done(init_done), .busy(ctrl_busy),
      .sdram_clk(sdram_clk_unused), .sdram_cke(cke), .sdram_csn(csn),
      .sdram_rasn(rasn), .sdram_casn(casn), .sdram_wen(wen),
      .sdram_a(sdram_a), .sdram_ba(sdram_ba), .sdram_dqm(sdram_dqm),
      .sdram_d(sdram_dq));

  sdram_model #(
      .POWERUP_DELAY_NS(POWERUP_US * 1000), .READ_DELAY_CYCLES(1)
  ) mem (
      .clk(clk), .cke(cke), .csn(csn), .rasn(rasn), .casn(casn), .wen(wen),
      .a(sdram_a), .ba(sdram_ba), .dqm(sdram_dqm), .dq(sdram_dq));

  // -- Contadores -----------------------------------------------------------
  integer ciclos;
  integer bursts;
  reg contando;
  always @(posedge clk) begin
    if (!reset) begin
      if (contando) ciclos <= ciclos + 1;
      if (contando && s_req_valid && s_req_ready) bursts <= bursts + 1;
    end
  end

  // -------------------------------------------------------------------------
  // El monitor emula el pulso de UN ciclo del de verdad: no mantiene el nivel
  // hasta `ready`. Si el adaptador no lo engancha, esto se cuelga, que es
  // exactamente el sintoma que dejo la placa muda una vez.
  // -------------------------------------------------------------------------
  task mon_write;
    input [31:0] address;
    input [7:0] value;
    begin
      @(negedge clk);
      mon_address = address;
      mon_write_data = value;
      mon_write_enable = 1'b1;
      @(negedge clk);
      mon_write_enable = 1'b0;
      guard = 0;
      while (!mon_ready && guard < 2000) begin
        @(negedge clk);
        guard = guard + 1;
      end
      if (!mon_ready) $fatal(1, "el monitor no recibio respuesta al escribir %08x", address);
      if (mon_error) $fatal(1, "error al escribir %08x desde el monitor", address);
      @(negedge clk);
    end
  endtask

  reg [7:0] leido;
  task mon_read;
    input [31:0] address;
    begin
      @(negedge clk);
      mon_address = address;
      mon_read_enable = 1'b1;
      @(negedge clk);
      mon_read_enable = 1'b0;
      guard = 0;
      while (!mon_ready && guard < 2000) begin
        @(negedge clk);
        guard = guard + 1;
      end
      if (!mon_ready) $fatal(1, "el monitor no recibio respuesta al leer %08x", address);
      if (mon_error) $fatal(1, "error al leer %08x desde el monitor", address);
      leido = mon_read_data;
      @(negedge clk);
    end
  endtask

  task mon_write_word;
    input [31:0] address;
    input [31:0] value;
    begin
      mon_write(address + 0, value[7:0]);
      mon_write(address + 1, value[15:8]);
      mon_write(address + 2, value[23:16]);
      mon_write(address + 3, value[31:24]);
    end
  endtask

  reg [31:0] programa[0:8];
  real por_palabra;

  initial begin
    // El bucle interior de swap_demo_fast aislado, el mismo de
    // examples/perf_loop.asm y el mismo que midio perf_probe_tb.v.
    programa[0] = 32'h5cc00001;   // MOVHI R6, 0x0001
    programa[1] = 32'h41a01234;   // MOVI  R13, 0x1234
    programa[2] = 32'h40600000;   // MOVI  R3, 0
    programa[3] = 32'h432000a0;   // MOVI  R25, 160
    programa[4] = 32'h59a60000;   // STORE R13, R6, 0
    programa[5] = 32'h44c60004;   // ADDI  R6, R6, 4
    programa[6] = 32'h44630001;   // ADDI  R3, R3, 1
    programa[7] = 32'h8879fffc;   // BLT   R3, R25, -4
    programa[8] = 32'hfc000000;   // HALT

    ciclos = 0;
    bursts = 0;
    contando = 1'b0;

    repeat (4) @(negedge clk);
    reset = 0;
    guard = 0;
    while (!init_done && guard < 200_000) begin
      @(negedge clk);
      guard = guard + 1;
    end
    if (!init_done) $fatal(1, "la inicializacion no termino");

    // ---------------------------------------------------------------------
    // 1. Cargar el programa por el monitor, byte a byte, con la CPU parada.
    // ---------------------------------------------------------------------
    for (i = 0; i < 9; i = i + 1)
      mon_write_word(i * 4, programa[i]);

    // Y releerlo, que es la unica forma de saber que la mascara de byte del
    // controlador no ha destruido los vecinos al escribir de uno en uno.
    for (i = 0; i < 9; i = i + 1) begin
      mon_read(i * 4);
      if (leido !== programa[i][7:0]) begin
        $display("FALLO: en %08x se leyo %02x, esperado %02x",
                 i * 4, leido, programa[i][7:0]);
        errors = errors + 1;
      end
      mon_read(i * 4 + 3);
      if (leido !== programa[i][31:24]) begin
        $display("FALLO: en %08x se leyo %02x, esperado %02x",
                 i * 4 + 3, leido, programa[i][31:24]);
        errors = errors + 1;
      end
    end

    // ---------------------------------------------------------------------
    // 2. Con la CPU en marcha el monitor NO posee la memoria.
    // ---------------------------------------------------------------------
    @(negedge clk); run_request = 1;
    @(negedge clk); run_request = 0;
    contando = 1'b1;

    // ---------------------------------------------------------------------
    // 3. Dejar correr el bucle entero y medir.
    // ---------------------------------------------------------------------
    guard = 0;
    while (!halted && guard < 500_000) begin
      @(negedge clk);
      guard = guard + 1;
    end
    contando = 1'b0;
    if (!halted) $fatal(1, "la CPU no llego a HALT");
    if (cpu_error)
      $fatal(1, "la CPU paro con error %02x en pc=%08x", cpu_error_code, debug_pc);

    por_palabra = ciclos * 1.0 / ITERATIONS;
    $display("");
    $display("Bucle interior sobre el camino de rafagas:");
    $display("  %0d ciclos, %.1f por palabra   (la 16 daba %0d)",
             ciclos, por_palabra, BASE_CYCLES_PER_WORD);
    $display("  %0d rafagas BL8 en total", bursts);
    $display("  bufer de instrucciones: %0d aciertos, %0d fallos",
             ibuf_hits, ibuf_misses);
    $display("  mejora sobre la 16: %.2fx", BASE_CYCLES_PER_WORD / por_palabra);

    // El programa entero son 36 bytes: tres lineas de 16. Ninguna se relee.
    if (ibuf_misses !== 32'd3) begin
      $display("FALLO: %0d fallos de bufer, esperados 3", ibuf_misses);
      errors = errors + 1;
    end
    // Y la integracion tiene que ser MAS RAPIDA que la 16, no solo funcionar.
    if (por_palabra >= BASE_CYCLES_PER_WORD) begin
      $display("FALLO: %.1f ciclos por palabra, la 16 daba %0d",
               por_palabra, BASE_CYCLES_PER_WORD);
      errors = errors + 1;
    end

    // ---------------------------------------------------------------------
    // 4. Parar la CPU y comprobar que el monitor ve lo que escribio el
    //    programa. Es el camino que rompe una incoherencia de bufer.
    // ---------------------------------------------------------------------
    mon_read(32'h0001_0000);
    if (leido !== 8'h34) begin
      $display("FALLO: el framebuffer tiene %02x en 0x00010000, esperado 34",
               leido);
      errors = errors + 1;
    end
    mon_read(32'h0001_0001);
    if (leido !== 8'h12) begin
      $display("FALLO: el framebuffer tiene %02x en 0x00010001, esperado 12",
               leido);
      errors = errors + 1;
    end
    // La ultima palabra que escribio el bucle, en 0x10000 + 159*4.
    mon_read(32'h0001_0000 + 159 * 4);
    if (leido !== 8'h34) begin
      $display("FALLO: la ultima palabra del bucle no llego a memoria");
      errors = errors + 1;
    end

    // ---------------------------------------------------------------------
    // 5. La ventana de registros de video responde a los dos clientes.
    // ---------------------------------------------------------------------
    mon_read(32'h8000_0000);
    if (leido !== 8'h00) begin
      $display("FALLO: FB_FRONT[7:0] = %02x, esperado 00", leido);
      errors = errors + 1;
    end
    mon_write(32'h8000_0008, 8'h01);
    mon_read(32'h8000_0008);
    if (leido !== 8'h01) begin
      $display("FALLO: SWAP no conservo el valor escrito: %02x", leido);
      errors = errors + 1;
    end

    // ---------------------------------------------------------------------
    // 6. Fuera de rango, error y no cuelgue.
    // ---------------------------------------------------------------------
    @(negedge clk);
    mon_address = 32'h0400_0000;
    mon_read_enable = 1'b1;
    @(negedge clk);
    mon_read_enable = 1'b0;
    guard = 0;
    while (!mon_ready && guard < 2000) begin
      @(negedge clk);
      guard = guard + 1;
    end
    if (!mon_ready) $fatal(1, "una lectura fuera de rango dejo al monitor colgado");
    if (!mon_error) begin
      $display("FALLO: una lectura fuera de rango no dio error");
      errors = errors + 1;
    end

    if (mem.errors != 0) begin
      $display("FALLO: el modelo de SDRAM conto %0d violaciones JEDEC",
               mem.errors);
      errors = errors + 1;
    end

    if (errors != 0) $fatal(1, "%0d comprobaciones fallaron", errors);
    $display("");
    $display("PASS: cpu_burst_system");
    $finish;
  end
endmodule

`default_nettype wire
