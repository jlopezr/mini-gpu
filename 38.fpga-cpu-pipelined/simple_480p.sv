// 640x480p60 display timing (VGA industry standard)
//
// Mismo interfaz que `simple_720p` de Project F, del que deriva, pero con las
// temporizaciones de 640x480 y **polaridad negativa** en ambos sincronismos,
// como exige el modo. Las constantes se escriben como primer/ultimo pixel de
// cada intervalo para que se puedan contrastar directamente con la tabla VGA:
//
//   horizontal: 640 activos + 16 front porch + 96 sync + 48 back porch =  800
//   vertical:   480 activas + 10 front porch +  2 sync + 33 back porch =  525
//
//   800 x 525 x 60 Hz = 25,2 MHz de reloj de pixel (aqui se usan 25,0 MHz).

`default_nettype none
`timescale 1ns / 1ps

module simple_480p (
    input  wire logic clk_pix,   // pixel clock
    input  wire logic rst_pix,   // reset in pixel clock domain
    output      logic [11:0] sx, // horizontal screen position
    output      logic [11:0] sy, // vertical screen position
    output      logic hsync,     // horizontal sync (active low)
    output      logic vsync,     // vertical sync (active low)
    output      logic de         // data enable (low in blanking interval)
    );

    // horizontal timings
    parameter HA_END = 639,             // last active pixel
              HS_STA = HA_END + 16 + 1, // first pixel of sync (656)
              HS_END = HS_STA + 96 - 1, // last pixel of sync (751)
              LINE   = 799;             // last pixel on line (after back porch)

    // vertical timings
    parameter VA_END = 479,             // last active line
              VS_STA = VA_END + 10 + 1, // first line of sync (490)
              VS_END = VS_STA + 2 - 1,  // last line of sync (491)
              SCREEN = 524;             // last line on screen (after back porch)

    always_comb begin
        hsync = !(sx >= HS_STA && sx <= HS_END);  // 480p tiene polaridad negativa
        vsync = !(sy >= VS_STA && sy <= VS_END);
        de = (sx <= HA_END && sy <= VA_END);
    end

    // calculate horizontal and vertical screen position
    always_ff @(posedge clk_pix) begin
        if (sx == LINE) begin  // last pixel on line?
            sx <= 0;
            sy <= (sy == SCREEN) ? 0 : sy + 1;  // last line on screen?
        end else begin
            sx <= sx + 1;
        end
        if (rst_pix) begin
            sx <= 0;
            sy <= 0;
        end
    end
endmodule

`default_nettype wire
