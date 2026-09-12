`default_nettype none

// Productor de lineas falso para el hito B: rellena la linea pedida con un
// patron calculado, sin tocar memoria.
//
// Existe para validar el cruce de dominios por separado del camino de SDRAM.
// En el hito C se sustituye por un lector de SDRAM con este mismo contrato:
//
//   fill_start  -> pulso: rellena la linea `fill_line`
//   fill_we/addr/data -> SRC_W palabras, direcciones 0..SRC_W-1
//   fill_done   -> pulso: linea completa
//
// El patron esta elegido para que un fallo del handshake se vea, no para que
// sea bonito:
//
//   - una diagonal blanca en x == linea. Si dos lineas se intercambian o se
//     repite un banco, la diagonal aparece rota o escalonada;
//   - un marco blanco de un pixel, que delata lineas perdidas arriba o abajo;
//   - un degradado rojo en horizontal y verde en vertical, que hace evidente
//     si una linea se pinta con el contenido de otra.
//
// `GAP` inserta ciclos muertos entre palabras. A 120 MHz sobran ~7600 ciclos
// para 320 palabras, asi que en la placa vale 0; el banco de pruebas lo usa
// para forzar un productor demasiado lento y comprobar que `underflow` salta.

module video_line_source_pattern #(
    parameter integer SRC_W     = 320,
    parameter integer SRC_H     = 240,
    parameter integer ADDR_BITS = 9,
    parameter integer LINE_BITS = 8,
    parameter integer GAP       = 0
) (
    input wire clk,
    input wire reset,
    input wire fill_start,
    input wire [LINE_BITS-1:0] fill_line,
    output reg fill_we,
    output reg [ADDR_BITS-1:0] fill_addr,
    output reg [15:0] fill_data,
    output reg fill_done
);
  localparam [ADDR_BITS-1:0] LAST_X = SRC_W - 1;
  localparam [LINE_BITS-1:0] LAST_LINE = SRC_H - 1;
  localparam [15:0] GAP_W = GAP;

  reg busy;
  reg [LINE_BITS-1:0] line;
  reg [ADDR_BITS-1:0] x;
  reg [15:0] gap_count;

  wire [15:0] pixel = ({{(16-ADDR_BITS){1'b0}}, x} == {{(16-LINE_BITS){1'b0}}, line}
                       || x == {ADDR_BITS{1'b0}} || x == LAST_X
                       || line == {LINE_BITS{1'b0}} || line == LAST_LINE)
                      ? 16'hffff
                      : {x[ADDR_BITS-1:ADDR_BITS-5],          // rojo   <- horizontal
                         line[LINE_BITS-1:LINE_BITS-6],       // verde  <- vertical
                         5'b00000};

  always @(posedge clk) begin
    if (reset) begin
      busy <= 1'b0;
      fill_we <= 1'b0;
      fill_done <= 1'b0;
      fill_addr <= {ADDR_BITS{1'b0}};
      fill_data <= 16'h0000;
      x <= {ADDR_BITS{1'b0}};
      line <= {LINE_BITS{1'b0}};
      gap_count <= 16'd0;
    end else begin
      fill_we <= 1'b0;
      fill_done <= 1'b0;

      if (!busy) begin
        if (fill_start) begin
          busy <= 1'b1;
          line <= fill_line;
          x <= {ADDR_BITS{1'b0}};
          gap_count <= 16'd0;
        end
      end else if (gap_count != 16'd0) begin
        gap_count <= gap_count - 1'b1;
      end else begin
        fill_we <= 1'b1;
        fill_addr <= x;
        fill_data <= pixel;
        if (x == LAST_X) begin
          busy <= 1'b0;
          fill_done <= 1'b1;
        end else begin
          x <= x + 1'b1;
          gap_count <= GAP_W;
        end
      end
    end
  end
endmodule

`default_nettype wire
