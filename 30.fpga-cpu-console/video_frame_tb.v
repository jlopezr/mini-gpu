`timescale 1ns/1ps
`default_nettype none

/*
 * Captura de frames completos en simulacion, a resolucion reducida.
 *
 * Es la unica prueba grafica de extremo a extremo que se puede hacer sin
 * placa. Monta la cadena entera del lado de sistema —framebuffer en SDRAM,
 * lector de rafagas, arbitro, controlador BL8, modelo de memoria— junto con el
 * scanout y su cruce de dominios, y **vuelca cada frame a un fichero PPM**.
 *
 * Por que a resolucion reducida
 * -----------------------------
 *
 * Un frame de 640x480 son 420 000 ciclos de pixel y la simulacion no termina en
 * un tiempo razonable. Aqui la pantalla es de 32x16 con fuente de 16x8, que es
 * el mismo truco que ya usaba video_scanout_tb.v: la logica ejercitada es
 * identica —prellenado, cambio de banco, duplicado 2x, handshake, aritmetica de
 * linea, rafagas— y un frame baja a 960 ciclos.
 *
 * Lo que NO cubre, y conviene tenerlo claro: nada del dominio de pixel hacia
 * fuera. La codificacion TMDS, los serializadores y los PLL solo se verifican
 * enchufando un monitor, como ya dice el README de la 16.
 *
 * Como se comprueba
 * -----------------
 *
 * Dos niveles, y el segundo es el que convierte esto en una prueba:
 *
 *   1. Aqui dentro, contra el patron que el propio banco escribio en la SDRAM.
 *      Cada pixel que sale por RGB se compara con el que deberia ser, y un
 *      fallo dice en que coordenada.
 *   2. Fuera, con tools/compare-frames.py, que compara los PPM volcados contra
 *      los que genera un modelo en Python. Eso es lo que permite validar un
 *      PROGRAMA, y no solo el camino de datos.
 *
 * Los ficheros salen como frame_NNN.ppm en el directorio de trabajo.
 */
module video_frame_tb;
  localparam integer SRC_W     = 16;
  localparam integer SRC_H     = 8;
  localparam integer H_ACTIVE  = 32;
  localparam integer V_ACTIVE  = 16;
  localparam integer LINE_END  = 39;
  localparam integer SCREEN    = 23;
  localparam integer ADDR_BITS = 5;
  localparam integer LINE_BITS = 6;

  localparam integer CLK_HZ = 80_000_000;
  localparam integer POWERUP_US = 2;
  // Framebuffer en direccion de byte. Alineado a 16 para que cada linea fuente
  // —16 pixeles, 32 bytes— sean exactamente dos rafagas.
  localparam [31:0] FB_BASE = 32'h0000_1000;

  localparam integer FRAMES_TO_DUMP = 3;

  reg clk_sys = 1'b0;
  reg clk_pix = 1'b0;
  reg reset = 1'b1;
  always #6.25 clk_sys = ~clk_sys;   // 80 MHz
  always #20.0 clk_pix = ~clk_pix;   // 25 MHz

  integer errors = 0;
  integer guard;
  integer i;

  // -- Barrido --------------------------------------------------------------
  wire [11:0] sx, sy;
  wire hsync, vsync, de;
  simple_480p #(
      .HA_END(H_ACTIVE - 1), .HS_STA(H_ACTIVE + 1), .HS_END(H_ACTIVE + 2),
      .LINE(LINE_END),
      .VA_END(V_ACTIVE - 1), .VS_STA(V_ACTIVE + 1), .VS_END(V_ACTIVE + 2),
      .SCREEN(SCREEN)
  ) display_i(
      .clk_pix(clk_pix), .rst_pix(reset), .sx(sx), .sy(sy),
      .hsync(hsync), .vsync(vsync), .de(de));

  // -- Scanout --------------------------------------------------------------
  wire [7:0] pix_r, pix_g, pix_b;
  wire pix_de, underflow;
  wire fill_start, fill_first, fill_we, fill_done;
  wire [LINE_BITS-1:0] fill_line;
  wire [ADDR_BITS-1:0] fill_addr;
  wire [15:0] fill_data;

  video_scanout #(
      .SRC_W(SRC_W), .SRC_H(SRC_H), .H_ACTIVE(H_ACTIVE), .V_ACTIVE(V_ACTIVE),
      .LINE_END(LINE_END), .ADDR_BITS(ADDR_BITS), .LINE_BITS(LINE_BITS)
  ) scanout_i(
      .clk_pix(clk_pix), .rst_pix(reset), .sx(sx), .sy(sy),
      .de_in(de), .hsync_in(hsync), .vsync_in(vsync),
      .r(pix_r), .g(pix_g), .b(pix_b),
      .de_out(pix_de), .hsync_out(), .vsync_out(),
      .underflow(underflow),
      .clk_sys(clk_sys), .rst_sys(reset), .underflow_clear(1'b0),
      .fill_start(fill_start), .fill_line(fill_line), .fill_first(fill_first),
      .fill_we(fill_we), .fill_addr(fill_addr), .fill_data(fill_data),
      .fill_done(fill_done));

  // -- Lector de rafagas ----------------------------------------------------
  wire v_req_valid, v_req_ready, v_req_write, v_urgent;
  wire [31:0] v_req_addr;
  wire [127:0] v_req_wdata;
  wire [15:0] v_req_wmask;
  wire v_rsp_valid, v_rsp_ready, v_rsp_error;
  wire [127:0] v_rsp_rdata;

  video_line_source_burst #(
      .SRC_W(SRC_W), .ADDR_BITS(ADDR_BITS), .LINE_BITS(LINE_BITS)
  ) reader_i(
      .clk(clk_sys), .reset(reset), .fb_base(FB_BASE[24:1]),
      .fill_start(fill_start), .fill_line(fill_line),
      .fill_we(fill_we), .fill_addr(fill_addr), .fill_data(fill_data),
      .fill_done(fill_done),
      .req_valid(v_req_valid), .req_ready(v_req_ready),
      .req_write(v_req_write), .req_addr(v_req_addr),
      .req_wdata(v_req_wdata), .req_wmask(v_req_wmask), .urgent(v_urgent),
      .rsp_valid(v_rsp_valid), .rsp_ready(v_rsp_ready),
      .rsp_rdata(v_rsp_rdata), .rsp_error(v_rsp_error));

  // -- Puerto 0: el banco, para dejar el framebuffer escrito ----------------
  reg p0_req_valid = 0;
  reg [31:0] p0_req_addr = 0;
  reg [127:0] p0_req_wdata = 0;
  wire p0_req_ready, p0_rsp_valid, p0_rsp_error;
  wire [127:0] p0_rsp_rdata;

  // -- Memoria --------------------------------------------------------------
  wire s_req_valid, s_req_ready, s_req_write, s_done;
  wire [23:0] s_req_addr;
  wire [127:0] s_req_wdata, s_rdata;
  wire [15:0] s_req_wmask;
  wire fabric_busy, ctrl_busy, init_done, sdram_clk_unused;
  wire cke, csn, rasn, casn, wen;
  wire [12:0] sdram_a;
  wire [1:0] sdram_ba, sdram_dqm;
  wire [15:0] sdram_dq;

  memory_fabric_4 fabric_i (
      .clk(clk_sys), .reset(reset),
      .p0_req_valid(p0_req_valid), .p0_req_ready(p0_req_ready),
      .p0_req_write(1'b1), .p0_req_addr(p0_req_addr),
      .p0_req_wdata(p0_req_wdata), .p0_req_wmask(16'hffff),
      .p0_rsp_valid(p0_rsp_valid), .p0_rsp_ready(1'b1),
      .p0_rsp_rdata(p0_rsp_rdata), .p0_rsp_error(p0_rsp_error),

      .p1_req_valid(1'b0), .p1_req_ready(), .p1_req_write(1'b0),
      .p1_req_addr(32'd0), .p1_req_wdata(128'd0), .p1_req_wmask(16'd0),
      .p1_rsp_valid(), .p1_rsp_ready(1'b1), .p1_rsp_rdata(), .p1_rsp_error(),

      .p2_req_valid(v_req_valid), .p2_req_ready(v_req_ready),
      .p2_req_write(v_req_write), .p2_req_addr(v_req_addr),
      .p2_req_wdata(v_req_wdata), .p2_req_wmask(v_req_wmask),
      .p2_urgent(v_urgent),
      .p2_rsp_valid(v_rsp_valid), .p2_rsp_ready(v_rsp_ready),
      .p2_rsp_rdata(v_rsp_rdata), .p2_rsp_error(v_rsp_error),

      .p3_req_valid(1'b0), .p3_req_ready(), .p3_req_write(1'b0),
      .p3_req_addr(32'd0), .p3_req_wdata(128'd0), .p3_req_wmask(16'd0),
      .p3_rsp_valid(), .p3_rsp_ready(1'b1), .p3_rsp_rdata(), .p3_rsp_error(),

      .sdram_req_valid(s_req_valid), .sdram_req_ready(s_req_ready),
      .sdram_req_write(s_req_write), .sdram_req_addr(s_req_addr),
      .sdram_req_wdata(s_req_wdata), .sdram_req_wmask(s_req_wmask),
      .sdram_done(s_done), .sdram_rdata(s_rdata), .busy(fabric_busy));

  sdram_controller_128 #(
      .CLK_FREQ_HZ(CLK_HZ), .POWERUP_DELAY_US(POWERUP_US)
  ) ctrl (
      .clk(clk_sys), .reset(reset),
      .req_valid(s_req_valid), .req_write(s_req_write), .req_addr(s_req_addr),
      .req_wdata(s_req_wdata), .req_wmask(s_req_wmask),
      .req_ready(s_req_ready), .done(s_done), .rdata(s_rdata),
      .init_done(init_done), .busy(ctrl_busy),
      .sdram_clk(sdram_clk_unused), .sdram_cke(cke), .sdram_csn(csn),
      .sdram_rasn(rasn), .sdram_casn(casn), .sdram_wen(wen),
      .sdram_a(sdram_a), .sdram_ba(sdram_ba), .sdram_dqm(sdram_dqm),
      .sdram_d(sdram_dq));

  sdram_model #(
      .POWERUP_DELAY_NS(POWERUP_US * 1000), .READ_DELAY_CYCLES(1),
      .CLK_PERIOD_NS(12)
  ) mem (
      .clk(clk_sys), .cke(cke), .csn(csn), .rasn(rasn), .casn(casn), .wen(wen),
      .a(sdram_a), .ba(sdram_ba), .dqm(sdram_dqm), .dq(sdram_dq));

  // -------------------------------------------------------------------------
  // El patron que se escribe en el framebuffer, y la referencia contra la que
  // se comprueba lo que sale. Un degradado con marco: el marco delata recortes
  // y errores de pitch, el degradado delata bytes intercambiados dentro del
  // pixel.
  // -------------------------------------------------------------------------
  function [15:0] patron;
    input integer x;
    input integer y;
    begin
      if (x == 0 || y == 0 || x == SRC_W - 1 || y == SRC_H - 1)
        patron = 16'hffff;
      else
        patron = {x[4:0], y[5:0], x[4:0]};
    end
  endfunction

  task escribir_rafaga;
    input [23:0] word_address;
    input [127:0] data;
    begin
      @(negedge clk_sys);
      // OJO: `valid` primero y `ready` despues. Ver la trampa del handshake en
      // el README.
      p0_req_valid = 1'b1;
      p0_req_addr = {word_address, 1'b0};
      p0_req_wdata = data;
      guard = 0;
      while (!p0_req_ready && guard < 500) begin
        @(negedge clk_sys);
        guard = guard + 1;
      end
      if (!p0_req_ready) $fatal(1, "el arbitro no acepto la escritura");
      @(negedge clk_sys);
      p0_req_valid = 1'b0;
      guard = 0;
      while (!p0_rsp_valid && guard < 500) begin
        @(negedge clk_sys);
        guard = guard + 1;
      end
      if (!p0_rsp_valid) $fatal(1, "el arbitro no respondio a la escritura");
      @(negedge clk_sys);
    end
  endtask

  integer x, y, w;
  reg [127:0] burst;

  task pintar_framebuffer;
    begin
      // SRC_W pixeles por linea, ocho por rafaga.
      for (y = 0; y < SRC_H; y = y + 1)
        for (w = 0; w < SRC_W; w = w + 8) begin
          for (i = 0; i < 8; i = i + 1)
            burst[i*16 +: 16] = patron(w + i, y);
          escribir_rafaga(FB_BASE[24:1] + y * SRC_W + w, burst);
        end
    end
  endtask

  // -------------------------------------------------------------------------
  // Volcado de frames a PPM y comprobacion pixel a pixel
  // -------------------------------------------------------------------------
  reg [11:0] sx_d, sy_d;
  always @(posedge clk_pix) begin
    sx_d <= sx;
    sy_d <= sy;
  end

  integer frames = 0;
  integer checked = 0;
  integer fd;
  integer dumped = 0;
  reg dumping = 1'b0;
  reg [15:0] want;
  reg [8*40:1] nombre;

  function [7:0] expand5(input [4:0] v);
    expand5 = {v, v[4:2]};
  endfunction
  function [7:0] expand6(input [5:0] v);
    expand6 = {v, v[5:4]};
  endfunction

  always @(posedge clk_pix) begin
    if (!reset && sy == V_ACTIVE && sx == 0) begin
      frames = frames + 1;
      // El primer frame arranca con el barrido en marcha y muestra basura
      // hasta el primer `frame_start`. Se empieza en el segundo.
      if (frames >= 2 && dumped < FRAMES_TO_DUMP) begin
        $sformat(nombre, "frame_%03d.ppm", dumped);
        fd = $fopen(nombre, "w");
        // PPM de texto: sin dependencias para escribirlo ni para leerlo.
        $fwrite(fd, "P3\n%0d %0d\n255\n", H_ACTIVE, V_ACTIVE);
        dumping = 1'b1;
      end
    end
  end

  always @(posedge clk_pix) begin
    if (dumping && pix_de) begin
      $fwrite(fd, "%0d %0d %0d\n", pix_r, pix_g, pix_b);

      // Y la comprobacion contra el patron que se escribio en memoria. El
      // scanout duplica cada pixel en horizontal y cada linea en vertical.
      want = patron(sx_d[ADDR_BITS:1], sy_d[LINE_BITS:1]);
      checked = checked + 1;
      if (pix_r !== expand5(want[15:11]) || pix_g !== expand6(want[10:5])
          || pix_b !== expand5(want[4:0])) begin
        errors = errors + 1;
        if (errors <= 10)
          $display("FALLO en (%0d,%0d): rgb=%02x%02x%02x, esperado %02x%02x%02x",
                   sx_d, sy_d, pix_r, pix_g, pix_b,
                   expand5(want[15:11]), expand6(want[10:5]),
                   expand5(want[4:0]));
      end

      // Fin del frame visible.
      if (sx_d == H_ACTIVE - 1 && sy_d == V_ACTIVE - 1) begin
        $fclose(fd);
        dumping = 1'b0;
        dumped = dumped + 1;
        $display("  volcado frame_%03d.ppm", dumped - 1);
      end
    end
  end

  initial begin
    repeat (4) @(negedge clk_sys);
    reset = 1'b0;
    guard = 0;
    while (!init_done && guard < 200_000) begin
      @(negedge clk_sys);
      guard = guard + 1;
    end
    if (!init_done) $fatal(1, "la inicializacion de la SDRAM no termino");

    pintar_framebuffer;

    guard = 0;
    while (dumped < FRAMES_TO_DUMP && guard < 2_000_000) begin
      @(negedge clk_pix);
      guard = guard + 1;
    end
    if (dumped < FRAMES_TO_DUMP)
      $fatal(1, "solo se volcaron %0d frames de %0d", dumped, FRAMES_TO_DUMP);

    if (checked < FRAMES_TO_DUMP * H_ACTIVE * V_ACTIVE)
      $fatal(1, "se comprobaron %0d pixeles, se esperaban %0d",
             checked, FRAMES_TO_DUMP * H_ACTIVE * V_ACTIVE);
    if (errors != 0)
      $fatal(1, "%0d pixeles incorrectos de %0d", errors, checked);
    if (underflow !== 1'b0)
      $fatal(1, "underflow leyendo el framebuffer por rafagas");
    if (mem.errors != 0)
      $fatal(1, "el modelo de SDRAM conto %0d violaciones JEDEC", mem.errors);

    $display("");
    $display("PASS: video_frame (%0d frames, %0d pixeles comprobados)",
             dumped, checked);
    $finish;
  end
endmodule

`default_nettype wire
