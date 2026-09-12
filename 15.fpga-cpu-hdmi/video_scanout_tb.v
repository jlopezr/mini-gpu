`default_nettype none
`timescale 1ns / 1ps

// Banco de pruebas del hito B: el cruce de dominios entre el productor de
// lineas (120 MHz) y el scanout (25 MHz).
//
// Se usa una pantalla diminuta (32x16 visibles, fuente de 16x8) en lugar de
// 640x480. La logica ejercitada es exactamente la misma -- prellenado, cambio
// de banco, duplicado 2x y handshake -- pero un frame son 960 ciclos de pixel
// en vez de 420000, asi que la simulacion tarda milisegundos.
//
// Dos sistemas en paralelo:
//
//   rapido  GAP=0   -> imagen correcta, `underflow` siempre a cero
//   lento   GAP=60  -> el productor no llega a tiempo y `underflow` se activa
//
// El segundo importa tanto como el primero: un detector de underflow que nunca
// se dispara no sirve de nada en el hito C.

module video_scanout_tb;
  localparam integer SRC_W     = 16;
  localparam integer SRC_H     = 8;
  localparam integer H_ACTIVE  = 32;
  localparam integer V_ACTIVE  = 16;
  localparam integer LINE_END  = 39;
  localparam integer SCREEN    = 23;
  localparam integer ADDR_BITS = 5;
  localparam integer LINE_BITS = 6;

  reg clk_sys = 1'b0;
  reg clk_pix = 1'b0;
  reg reset = 1'b1;

  always #4.1667 clk_sys = ~clk_sys;  // 120 MHz
  always #20.0   clk_pix = ~clk_pix;  // 25 MHz

  // ---------------------------------------------------------------------------
  // Sistema bajo prueba, instanciado dos veces con productores de distinta
  // velocidad. `GAP` es el unico parametro que cambia.
  // ---------------------------------------------------------------------------
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

  wire [7:0] fast_r, fast_g, fast_b;
  wire fast_de, fast_underflow;
  wire fast_start, fast_we, fast_done;
  wire [LINE_BITS-1:0] fast_line;
  wire [ADDR_BITS-1:0] fast_addr;
  wire [15:0] fast_data;

  video_scanout #(
      .SRC_W(SRC_W), .SRC_H(SRC_H), .H_ACTIVE(H_ACTIVE), .V_ACTIVE(V_ACTIVE),
      .LINE_END(LINE_END), .ADDR_BITS(ADDR_BITS), .LINE_BITS(LINE_BITS)
  ) fast_i(
      .clk_pix(clk_pix), .rst_pix(reset), .sx(sx), .sy(sy),
      .de_in(de), .hsync_in(hsync), .vsync_in(vsync),
      .r(fast_r), .g(fast_g), .b(fast_b),
      .de_out(fast_de), .hsync_out(), .vsync_out(),
      .underflow(fast_underflow),
      .clk_sys(clk_sys), .rst_sys(reset),
      .fill_start(fast_start), .fill_line(fast_line),
      .fill_we(fast_we), .fill_addr(fast_addr), .fill_data(fast_data),
      .fill_done(fast_done));

  video_line_source_pattern #(
      .SRC_W(SRC_W), .SRC_H(SRC_H), .ADDR_BITS(ADDR_BITS),
      .LINE_BITS(LINE_BITS), .GAP(0)
  ) fast_source_i(
      .clk(clk_sys), .reset(reset), .fill_start(fast_start),
      .fill_line(fast_line), .fill_we(fast_we), .fill_addr(fast_addr),
      .fill_data(fast_data), .fill_done(fast_done));

  wire slow_underflow;
  wire slow_start, slow_we, slow_done;
  wire [LINE_BITS-1:0] slow_line;
  wire [ADDR_BITS-1:0] slow_addr;
  wire [15:0] slow_data;

  video_scanout #(
      .SRC_W(SRC_W), .SRC_H(SRC_H), .H_ACTIVE(H_ACTIVE), .V_ACTIVE(V_ACTIVE),
      .LINE_END(LINE_END), .ADDR_BITS(ADDR_BITS), .LINE_BITS(LINE_BITS)
  ) slow_i(
      .clk_pix(clk_pix), .rst_pix(reset), .sx(sx), .sy(sy),
      .de_in(de), .hsync_in(hsync), .vsync_in(vsync),
      .r(), .g(), .b(),
      .de_out(), .hsync_out(), .vsync_out(),
      .underflow(slow_underflow),
      .clk_sys(clk_sys), .rst_sys(reset),
      .fill_start(slow_start), .fill_line(slow_line),
      .fill_we(slow_we), .fill_addr(slow_addr), .fill_data(slow_data),
      .fill_done(slow_done));

  video_line_source_pattern #(
      .SRC_W(SRC_W), .SRC_H(SRC_H), .ADDR_BITS(ADDR_BITS),
      .LINE_BITS(LINE_BITS), .GAP(60)
  ) slow_source_i(
      .clk(clk_sys), .reset(reset), .fill_start(slow_start),
      .fill_line(slow_line), .fill_we(slow_we), .fill_addr(slow_addr),
      .fill_data(slow_data), .fill_done(slow_done));

  // ---------------------------------------------------------------------------
  // Modelo de referencia
  // ---------------------------------------------------------------------------
  function [15:0] expected_pixel(input [LINE_BITS-1:0] line,
                                 input [ADDR_BITS-1:0] x);
    begin
      if (x == line[ADDR_BITS-1:0] || x == 0 || x == SRC_W - 1
          || line == 0 || line == SRC_H - 1)
        expected_pixel = 16'hffff;
      else
        expected_pixel = {x[ADDR_BITS-1:ADDR_BITS-5],
                          line[LINE_BITS-1:LINE_BITS-6], 5'b00000};
    end
  endfunction

  function [7:0] expand5(input [4:0] value);
    expand5 = {value, value[4:2]};
  endfunction

  function [7:0] expand6(input [5:0] value);
    expand6 = {value, value[5:4]};
  endfunction

  // El dato sale un ciclo despues de presentar `sx`, asi que se compara contra
  // la posicion anterior, la misma que `de_out` acompana.
  reg [11:0] sx_d, sy_d;
  always @(posedge clk_pix) begin
    sx_d <= sx;
    sy_d <= sy;
  end

  integer frames = 0;
  integer checked = 0;
  integer errors = 0;
  reg checking = 1'b0;

  always @(posedge clk_pix) begin
    if (!reset && sy == V_ACTIVE && sx == 0) begin
      frames = frames + 1;
      // El primer frame arranca con el barrido ya en marcha y muestra basura
      // hasta el primer `frame_start`. Se comprueba a partir del segundo.
      if (frames >= 2) checking = 1'b1;
    end
  end

  reg [15:0] want;
  always @(posedge clk_pix) begin
    if (checking && fast_de) begin
      want = expected_pixel(sy_d[LINE_BITS:1], sx_d[ADDR_BITS:1]);
      checked = checked + 1;
      if (fast_r !== expand5(want[15:11]) || fast_g !== expand6(want[10:5])
          || fast_b !== expand5(want[4:0])) begin
        errors = errors + 1;
        if (errors <= 10)
          $display("ERROR en (%0d,%0d): rgb=%02x%02x%02x esperado %02x%02x%02x",
                   sx_d, sy_d, fast_r, fast_g, fast_b,
                   expand5(want[15:11]), expand6(want[10:5]), expand5(want[4:0]));
      end
    end
  end

  initial begin
    $dumpvars(0, video_scanout_tb);

    repeat (4) @(posedge clk_pix);
    reset = 1'b0;

    wait (frames == 4);
    @(posedge clk_pix);

    if (checked < 2 * H_ACTIVE * V_ACTIVE)
      $fatal(1, "se comprobaron solo %0d pixeles, se esperaban al menos %0d",
             checked, 2 * H_ACTIVE * V_ACTIVE);
    if (errors != 0)
      $fatal(1, "%0d pixeles incorrectos de %0d", errors, checked);
    if (fast_underflow !== 1'b0)
      $fatal(1, "underflow espurio con el productor rapido");
    if (slow_underflow !== 1'b1)
      $fatal(1, "el productor lento no ha provocado underflow: el detector no sirve");

    $display("OK: %0d pixeles correctos; underflow detectado solo en el lento",
             checked);
    $finish;
  end

  initial begin
    #2_000_000;
    $fatal(1, "timeout");
  end
endmodule

`default_nettype wire
