`timescale 1ns/1ps
`default_nettype none

/*
 * Integracion del hito D: la CPU real manejando los registros de video, sobre
 * el camino de memoria de VERDAD.
 *
 * Este banco montaba `sdram_system_adapter`, que es el bloque unico de la 16 y
 * ya no esta en `top.v`. Eso tenia una consecuencia que no se veia: su ventana
 * MMIO es de 16 bytes (`address[31:4]`) y la del hardware es de 32
 * (`address[31:5]`), asi que `SWAP_COUNT` (+0x10) y `HALT_AT` (+0x14) caian
 * FUERA de la ventana y ningun banco de RTL podia tocarlos. Los dos registros
 * que sostienen la captura determinista de frames --y con ella la capacidad
 * `frame_capture` de x.cpu-tests-- solo estaban probados en placa y en el
 * simulador funcional.
 *
 * Ahora monta lo mismo que `top.v` sin el dominio de pixel: bufer de
 * instrucciones, `cpu_dmem_adapter`, `monitor_mem_adapter_128`, `mmio_mux`,
 * `memory_fabric_4`, `sdram_controller_128` y el modelo de SDRAM. El mapa de
 * direcciones que se prueba aqui es el que se sintetiza.
 *
 * El programa hace dos cosas seguidas, en una sola ejecucion:
 *
 *   1. Lee FB_FRONT y FB_BACK, pide un intercambio, gira esperando a que el
 *      hardware lo aplique, y vuelve a leerlos. Eso es swap_smoke.asm, y cubre
 *      que LOAD y STORE sobre 0x80000000 funcionan desde la CPU.
 *   2. Se queda pidiendo intercambios sin parar. Asi el banco puede armar
 *      HALT_AT y comprobar que la CPU se para SOLA en el intercambio que toca,
 *      que es lo que hace `capture-frames.ps1` en la placa.
 *
 * Los intercambios los dispara este banco pulsando `fill_start`/`fill_first`,
 * que es lo que hace el scanout al empezar cada frame.
 */
module cpu_video_tb;
  localparam integer CLK_HZ = 100_000_000;
  localparam integer POWERUP_US = 2;

  localparam [31:0] FRONT_RESET = 32'h0100_0000;
  localparam [31:0] BACK_RESET  = 32'h0102_5800;
  // Cuantos intercambios se dejan pasar antes de que HALT_AT pare la CPU.
  localparam integer PARAR_EN = 3;

  // Los dos buffers se alternan en cada intercambio, asi que donde acaban
  // depende de la PARIDAD de PARAR_EN. Derivarlo en vez de escribirlo a mano
  // es lo que permite cambiar PARAR_EN sin que fallen comprobaciones que no
  // tienen nada que ver: la primera version fijaba el caso impar y subir a 4
  // daba dos fallos que parecian del intercambio y eran del banco.
  localparam [31:0] FRONT_FINAL = (PARAR_EN % 2) ? BACK_RESET : FRONT_RESET;
  localparam [31:0] BACK_FINAL  = (PARAR_EN % 2) ? FRONT_RESET : BACK_RESET;

  reg clk = 0;
  reg reset = 1;
  always #5 clk = ~clk;

  integer errors = 0;
  integer guard;
  integer i;

  // -- CPU --------------------------------------------------------------------
  reg run_request = 0;
  wire halted, cpu_error, instruction_retired;
  wire [7:0] cpu_error_code;
  wire imem_valid, imem_ready;
  wire [31:0] imem_address, imem_read_data;
  wire dmem_valid, dmem_ready, dmem_error;
  wire [31:0] dmem_address, dmem_write_data, dmem_read_data;
  wire [3:0] dmem_write_enable;
  reg [4:0] debug_register_address = 0;
  wire [31:0] debug_register_data, debug_pc;

  wire video_halt_request;

  cpu cpu_i (
      .clk(clk), .reset(reset), .run_request(run_request),
      // La misma union de fuentes que top.v: el monitor y el HALT_AT del video.
      .halt_request(video_halt_request), .step_request(1'b0), .halted(halted),
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

  // -- Monitor emulado, byte a byte y con pulso de un ciclo -------------------
  reg [31:0] mon_address = 0;
  reg [7:0] mon_write_data = 0;
  reg mon_write_enable = 0, mon_read_enable = 0;
  wire [7:0] mon_read_data;
  wire [31:0] mon_bus_word;   // la misma lectura sin trocear
  wire mon_ready, mon_error;

  // -- Puertos del arbitro ----------------------------------------------------
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

  // -- MMIO -------------------------------------------------------------------
  wire mon_mmio_req, mon_mmio_ack, mon_mmio_write;
  wire [3:0] mon_mmio_mask;
  wire [11:0] mon_mmio_addr;
  wire [31:0] mon_mmio_wdata;
  wire cpu_mmio_req, cpu_mmio_ack, cpu_mmio_write;
  wire [3:0] cpu_mmio_mask;
  wire [11:0] cpu_mmio_addr;
  wire [31:0] cpu_mmio_wdata;
  wire mmio_select, mmio_write;
  wire [3:0] mmio_write_mask;
  wire [11:0] mmio_address;
  wire [31:0] mmio_write_data, mmio_read_data;
  wire mmio_error;
  wire mmio_video_select, mmio_serial_select;
  wire [31:0] mmio_video_read_data, mmio_serial_read_data;
  wire [31:0] ibuf_hits, ibuf_misses;
  wire wb_dirty;
  wire [31:0] wb_merges, wb_flushes;

  reg fill_start = 0, fill_first = 0;
  wire [23:0] fb_base;
  wire underflow_clear;
  wire [31:0] debug_front, debug_back;

  // -- SDRAM ------------------------------------------------------------------
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
      .dmem_error(dmem_error), .cpu_halted(halted),
      .wb_dirty(wb_dirty), .merge_count(wb_merges), .flush_count(wb_flushes),
      .mmio_req(cpu_mmio_req), .mmio_ack(cpu_mmio_ack),
      .mmio_write(cpu_mmio_write), .mmio_write_mask(cpu_mmio_mask),
      .mmio_address(cpu_mmio_addr), .mmio_write_data(cpu_mmio_wdata),
      .mmio_read_data(mmio_read_data), .mmio_error(mmio_error),
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
      .wb_dirty(wb_dirty),
      .mem_address(mon_address), .mem_write_data(mon_write_data),
      .mem_write_enable(mon_write_enable),
      // Sin WRITE_WORD aqui: atadas, que al aire valen `x`.
      .mem_write_word(32'd0), .mem_write_word_enable(1'b0),
      .mem_read_enable(mon_read_enable),
      .mem_read_data(mon_read_data), .mem_read_word(mon_bus_word), .mem_ready(mon_ready),
      .mem_error(mon_error),
      .mmio_req(mon_mmio_req), .mmio_ack(mon_mmio_ack),
      .mmio_write(mon_mmio_write), .mmio_write_mask(mon_mmio_mask),
      .mmio_address(mon_mmio_addr), .mmio_write_data(mon_mmio_wdata),
      .mmio_read_data(mmio_read_data), .mmio_error(mmio_error),
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

  // El mismo reparto de ventana que top.v, con el dispositivo serie incluido
  // aunque este banco no lo use: lo que se prueba aqui es el mapa que se
  // sintetiza, y eso incluye que anadir un dispositivo no mueva el video.
  mmio_decoder mmio_decoder_i (
      .select(mmio_select), .write(mmio_write), .address(mmio_address),
      .video_select(mmio_video_select), .video_read_data(mmio_video_read_data),
      .serial_select(mmio_serial_select),
      .serial_read_data(mmio_serial_read_data),
      .read_data(mmio_read_data), .error(mmio_error));

  video_registers #(
      .FB_FRONT_RESET(FRONT_RESET), .FB_BACK_RESET(BACK_RESET)
  ) registers_i (
      .clk(clk), .reset(reset),
      .select(mmio_video_select), .write(mmio_write),
      .write_mask(mmio_write_mask), .address(mmio_address[7:0]),
      .write_data(mmio_write_data), .read_data(mmio_video_read_data),
      .fill_start(fill_start), .fill_first(fill_first), .fb_base(fb_base),
      .underflow_pix(1'b0), .underflow_clear(underflow_clear),
      .halt_request(video_halt_request),
      .debug_front(debug_front), .debug_back(debug_back));

  serial_port serial_i (
      .clk(clk), .reset(reset),
      .select(mmio_serial_select), .write(mmio_write),
      .write_mask(mmio_write_mask), .address(mmio_address[7:0]),
      .write_data(mmio_write_data), .read_data(mmio_serial_read_data),
      .host_push(1'b0), .host_push_data(8'h00), .host_rx_free(),
      .host_pop(1'b0), .host_tx_data(), .host_tx_count());

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

  // ---------------------------------------------------------------------------
  // Tareas del monitor. Pulso de UN ciclo, como el de verdad: si el adaptador
  // no lo engancha, esto se cuelga.
  // ---------------------------------------------------------------------------
  reg [7:0] leido;

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
      if (!mon_ready) $fatal(1, "sin respuesta al escribir %08x", address);
      if (mon_error) $fatal(1, "error al escribir %08x", address);
      @(negedge clk);
    end
  endtask

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
      if (!mon_ready) $fatal(1, "sin respuesta al leer %08x", address);
      if (mon_error) $fatal(1, "error al leer %08x", address);
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

  reg [31:0] palabra;
  task mon_read_word;
    input [31:0] address;
    begin
      mon_read(address + 0); palabra[7:0]   = leido;
      mon_read(address + 1); palabra[15:8]  = leido;
      mon_read(address + 2); palabra[23:16] = leido;
      mon_read(address + 3); palabra[31:24] = leido;
    end
  endtask

  task expect_register;
    input [4:0] number;
    input [31:0] expected;
    input [255:0] name;
    begin
      debug_register_address = number;
      repeat (3) @(negedge clk);
      if (debug_register_data !== expected) begin
        $display("FALLO %0s: R%0d = %08x, esperado %08x",
                 name, number, debug_register_data, expected);
        errors = errors + 1;
      end
    end
  endtask

  // Un frame del scanout: la primera peticion de linea, que es donde viaja el
  // intercambio. Despues se deja correr a la CPU para que vuelva a pedir otro.
  task un_frame;
    begin
      @(negedge clk); fill_start = 1; fill_first = 1;
      @(negedge clk); fill_start = 0; fill_first = 0;
      repeat (400) @(negedge clk);
    end
  endtask

  initial begin
    $dumpvars(0, cpu_video_tb);

    repeat (4) @(negedge clk);
    reset = 0;
    wait (init_done);
    repeat (10) @(negedge clk);

    // -----------------------------------------------------------------------
    // Programa. Las diez primeras instrucciones son swap_smoke.asm; a partir de
    // 0x28 se queda pidiendo intercambios para que HALT_AT tenga algo que
    // contar.
    // -----------------------------------------------------------------------
    mon_write_word(32'h0000_0000, 32'h5E80_8000); // MOVHI R20,0x8000
    mon_write_word(32'h0000_0004, 32'h5434_0000); // LOAD  R1,R20,0
    mon_write_word(32'h0000_0008, 32'h5454_0004); // LOAD  R2,R20,4
    mon_write_word(32'h0000_000c, 32'h40E0_0001); // MOVI  R7,1
    mon_write_word(32'h0000_0010, 32'h4120_0000); // MOVI  R9,0
    mon_write_word(32'h0000_0014, 32'h58F4_0008); // STORE R7,R20,8
    mon_write_word(32'h0000_0018, 32'h5514_0008); // LOAD  R8,R20,8
    mon_write_word(32'h0000_001c, 32'h8509_FFFE); // BNE   R8,R9,-2
    mon_write_word(32'h0000_0020, 32'h5474_0000); // LOAD  R3,R20,0
    mon_write_word(32'h0000_0024, 32'h5494_0004); // LOAD  R4,R20,4
    mon_write_word(32'h0000_0028, 32'h58F4_0008); // STORE R7,R20,8
    mon_write_word(32'h0000_002c, 32'h5514_0008); // LOAD  R8,R20,8
    mon_write_word(32'h0000_0030, 32'h8509_FFFE); // BNE   R8,R9,-2
    mon_write_word(32'h0000_0034, 32'hBFFF_FFFC); // BRA   -4

    // -----------------------------------------------------------------------
    // Armar HALT_AT. Esto es lo que ningun banco de RTL podia hacer antes: con
    // la ventana de 16 bytes del adaptador de la 16, 0x80000014 no decodificaba
    // como MMIO y el acceso se iba por el camino de SDRAM.
    // -----------------------------------------------------------------------
    mon_write_word(32'h8000_0014, PARAR_EN);
    mon_read_word(32'h8000_0014);
    if (palabra !== PARAR_EN) begin
      $display("FALLO: HALT_AT leyo %08x, esperado %08x", palabra, PARAR_EN);
      errors = errors + 1;
    end
    // Armar reinicia la cuenta: es "para dentro de N", no "para en el N-esimo
    // desde el encendido".
    mon_read_word(32'h8000_0010);
    if (palabra !== 32'd0) begin
      $display("FALLO: armar HALT_AT no puso SWAP_COUNT a cero: %08x", palabra);
      errors = errors + 1;
    end

    @(negedge clk); run_request = 1; @(negedge clk); run_request = 0;

    // El programa gira en su bucle de espera hasta que llega un frame. Se le
    // deja girar a proposito: si saliera sin que el hardware haya intercambiado
    // nada, las comprobaciones de abajo lo cazarian.
    guard = 0;
    while (!halted && guard < 600) begin @(negedge clk); guard = guard + 1; end
    if (halted) $fatal(1, "el programa salio del bucle de espera sin ningun frame");

    // -----------------------------------------------------------------------
    // PARAR_EN frames. El ultimo tiene que parar la CPU por si solo.
    // -----------------------------------------------------------------------
    for (i = 0; i < PARAR_EN; i = i + 1) begin
      if (halted && i < PARAR_EN - 1) begin
        $display("FALLO: la CPU paro en el intercambio %0d, antes de HALT_AT=%0d",
                 i, PARAR_EN);
        errors = errors + 1;
      end
      un_frame();
    end

    if (!halted) begin
      $display("FALLO: HALT_AT=%0d no paro la CPU", PARAR_EN);
      errors = errors + 1;
    end
    if (cpu_error) begin
      $display("FALLO: la CPU paro con error %02x en pc=%08x",
               cpu_error_code, debug_pc);
      errors = errors + 1;
    end

    // -----------------------------------------------------------------------
    // Lo que vio el programa en el primer intercambio.
    // -----------------------------------------------------------------------
    expect_register(5'd1, FRONT_RESET, "FB_FRONT antes");
    expect_register(5'd2, BACK_RESET,  "FB_BACK antes");
    expect_register(5'd3, BACK_RESET,  "FB_FRONT despues del swap");
    expect_register(5'd4, FRONT_RESET, "FB_BACK despues del swap");

    // -----------------------------------------------------------------------
    // Y lo que ve el monitor con la CPU ya parada.
    // -----------------------------------------------------------------------
    mon_read_word(32'h8000_0010);
    if (palabra !== PARAR_EN) begin
      $display("FALLO: SWAP_COUNT = %08x, esperado %0d", palabra, PARAR_EN);
      errors = errors + 1;
    end

    mon_read_word(32'h8000_0000);
    if (palabra !== FRONT_FINAL) begin
      $display("FALLO: FB_FRONT = %08x, esperado %08x tras %0d intercambios",
               palabra, FRONT_FINAL, PARAR_EN);
      errors = errors + 1;
    end

    if (debug_front !== FRONT_FINAL || debug_back !== BACK_FINAL) begin
      $display("FALLO: los buffers no quedaron donde toca: front=%08x back=%08x",
               debug_front, debug_back);
      errors = errors + 1;
    end

    // La alarma es de un disparo: se consume al dispararse.
    un_frame();
    mon_read_word(32'h8000_0010);
    if (palabra !== PARAR_EN) begin
      $display("FALLO: SWAP_COUNT avanzo con la CPU parada: %08x", palabra);
      errors = errors + 1;
    end

    if (mem.errors != 0) begin
      $display("FALLO: el modelo de SDRAM conto %0d violaciones JEDEC", mem.errors);
      errors = errors + 1;
    end

    if (errors != 0) $fatal(1, "%0d comprobaciones fallaron", errors);
    $display("OK: la CPU pidio el swap sobre el MMIO real, vio los buffers");
    $display("    intercambiados, y HALT_AT la paro en el intercambio %0d", PARAR_EN);
    $finish;
  end

  initial begin
    #2_000_000;
    $fatal(1, "timeout");
  end
endmodule

`default_nettype wire
