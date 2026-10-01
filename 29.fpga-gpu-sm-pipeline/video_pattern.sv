// Patron de prueba generado por logica, sin tocar memoria.
//
// Existe solo para el hito A: demuestra que el dominio de pixel, el PLL, el
// generador de sincronismos y la cadena TMDS funcionan, antes de que haya
// ningun framebuffer. En el hito C este modulo se sustituye por el scanout que
// lee SDRAM, y el interfaz (sx, sy, de -> r, g, b) es deliberadamente el mismo.
//
// Lo que se ve:
//
//   - ocho barras verticales de color, 80 pixeles cada una;
//   - una banda horizontal blanca que baja una linea por frame, para distinguir
//     una imagen viva de una imagen congelada;
//   - una rejilla de puntos cada 64 pixeles, util para detectar recortes de
//     imagen o sobreescaneo del monitor.

`default_nettype none
`timescale 1ns / 1ps

module video_pattern (
    input  wire logic clk_pix,
    input  wire logic rst_pix,
    input  wire logic [11:0] sx,
    input  wire logic [11:0] sy,
    input  wire logic de,
    input  wire logic frame,          // un ciclo al empezar el blanking vertical
    output      logic [7:0] r,
    output      logic [7:0] g,
    output      logic [7:0] b
    );

    localparam V_RES = 480;

    // posicion de la banda movil
    logic [11:0] band_y;
    always_ff @(posedge clk_pix) begin
        if (rst_pix) begin
            band_y <= 0;
        end else if (frame) begin
            band_y <= (band_y == V_RES - 4) ? 12'd0 : band_y + 4;
        end
    end

    // Barras de color de 80 px. Se cuenta en lugar de dividir `sx`: 640 no es
    // potencia de dos, y un divisor por 80 en hardware no se justifica aqui.
    localparam BAR_W = 80;
    logic [6:0] bar_cnt;
    logic [2:0] bar;
    always_ff @(posedge clk_pix) begin
        if (rst_pix || sx == 12'd0) begin
            bar_cnt <= 0;
            bar <= 0;
        end else if (de) begin
            if (bar_cnt == BAR_W - 1) begin
                bar_cnt <= 0;
                bar <= bar + 1;
            end else begin
                bar_cnt <= bar_cnt + 1;
            end
        end
    end

    logic [7:0] bar_r, bar_g, bar_b;
    always_comb begin
        bar_r = bar[2] ? 8'hff : 8'h00;
        bar_g = bar[1] ? 8'hff : 8'h00;
        bar_b = bar[0] ? 8'hff : 8'h00;
    end

    logic in_band, on_grid;
    always_comb begin
        in_band = (sy >= band_y && sy < band_y + 4);
        on_grid = (sx[5:0] == 6'd0 && sy[5:0] == 6'd0);
    end

    always_comb begin
        if (!de) begin
            {r, g, b} = 24'h000000;             // negro obligatorio en blanking
        end else if (in_band || on_grid) begin
            {r, g, b} = 24'hffffff;
        end else begin
            r = bar_r;
            g = bar_g;
            b = bar_b;
        end
    end
endmodule

`default_nettype wire
