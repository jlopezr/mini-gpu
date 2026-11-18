// Project F Library - Dual clock generation (ECP5)
// Copyright Will Green, open source hardware released under the MIT License
// Learn more at https://projectf.io/posts/ecp5-fpga-clock/

module clock2_gen #(
    parameter CLKI_DIV  = 1,     // input clock divider
    parameter CLKFB_DIV = 1,     // feedback divider
    parameter CLKOP_DIV = 1,     // primary output clock divider
    parameter CLKOP_CPHASE = 0,  // primary output clock phase
    parameter CLKOS_DIV = 1,     // secondary output clock divider
    parameter CLKOS_CPHASE = 0   // secondary output clock phase
    ) (
    input  wire clk_in,      // input clock
    output wire clk_5x_out,  // output 5x clock
    output wire clk_out,     // output clock
    output reg  clk_locked   // clock locked?
    );

`ifdef SYNTHESIZE
    wire locked;  // unsynced lock signal

    // Diamond (Map) rechaza FEEDBK_PATH=CLKOP si CLKOP lleva desfase ("output CLKOP with
    // -144 degree phase shift should not be used as the feedback signal"). El 0 grados de
    // Lattice es CPHASE = DIV-1, no el DIV/2 que saca ecppll. Se mueven CLKOP a DIV-1 y
    // CLKOS el mismo numero de ciclos de VCO, asi la fase RELATIVA entre los dos relojes
    // (lo que importa en HDMI) no cambia. Vale igual para apio y Diamond: el bitstream
    // lleva el mismo valor con las dos herramientas.
    // Estos localparam van ANTES de los atributos: un (* ... *) se pega a la declaracion
    // que tiene justo detras, y tienen que quedar pegados a la instancia EHXPLLL.
    localparam integer PHASE_FIX = CLKOP_DIV - 1 - CLKOP_CPHASE;
    localparam integer PLL_CLKOP_CPHASE = CLKOP_CPHASE + PHASE_FIX;
    localparam integer PLL_CLKOS_CPHASE = (CLKOS_CPHASE + PHASE_FIX) % CLKOS_DIV;

    // HDL attributes (values are from Project Trellis)
    (* ICP_CURRENT="12" *)
    (* LPF_RESISTOR="8" *)
    (* MFG_ENABLE_FILTEROPAMP="1" *)
    (* MFG_GMCREF_SEL="2" *)

    // Frecuencias para Synplify/Diamond, que no las deduce de los parametros: sin
    // ellas TRACE no analiza los relojes del PLL y solo mide el de entrada. nextpnr
    // no las necesita. Valen para todas las tops que usan este modulo (CLKI_DIV 1,
    // CLKFB_DIV 5, CLKOP_DIV 5, CLKOS_DIV 25): CLKOP = 25/1*5 = 125 MHz;
    // CLKOS = 125*5/25 = 25 MHz. Si cambias los parametros de una top, cambia
    // tambien estos tres.
    (* FREQUENCY_PIN_CLKI="25" *)
    (* FREQUENCY_PIN_CLKOP="125" *)
    (* FREQUENCY_PIN_CLKOS="25" *)

    // El EHXPLLL tiene mas salidas de las que usamos (ENCLKOS, los CLKOS que no
    // se sacan...). No conectarlas es lo normal en una primitiva de Lattice, asi
    // que se silencia aqui y solo aqui: avisos fijos tapan los que si importan.

    // verilator lint_off PINMISSING

    EHXPLLL #(
        .PLLRST_ENA("DISABLED"),
        .INTFB_WAKE("DISABLED"),
        .STDBY_ENABLE("DISABLED"),
        .DPHASE_SOURCE("DISABLED"),
        .OUTDIVIDER_MUXA("DIVA"),
        .OUTDIVIDER_MUXB("DIVB"),
        .OUTDIVIDER_MUXC("DIVC"),
        .OUTDIVIDER_MUXD("DIVD"),
        .CLKI_DIV(CLKI_DIV),
        .CLKOP_ENABLE("ENABLED"),
        .CLKOP_DIV(CLKOP_DIV),
        .CLKOP_CPHASE(PLL_CLKOP_CPHASE),
        .CLKOP_FPHASE(0),
        .CLKOS_ENABLE("ENABLED"),
        .CLKOS_DIV(CLKOS_DIV),
        .CLKOS_CPHASE(PLL_CLKOS_CPHASE),
        .CLKOS_FPHASE(0),
        .FEEDBK_PATH("CLKOP"),
        .CLKFB_DIV(CLKFB_DIV)
    ) pll_i (
        .RST(1'b0),
        .STDBY(1'b0),
        .CLKI(clk_in),
        .CLKOP(clk_5x_out),
        .CLKOS(clk_out),
        .CLKFB(clk_5x_out),
        .CLKINTFB(),
        .PHASESEL0(1'b0),
        .PHASESEL1(1'b0),
        .PHASEDIR(1'b1),
        .PHASESTEP(1'b1),
        .PHASELOADREG(1'b1),
        .PLLWAKESYNC(1'b0),
        .ENCLKOP(1'b0),
        .LOCK(locked)
    );
    // verilator lint_on PINMISSING

    // ensure clock lock is synced with output clock
    reg locked_sync;
    always @(posedge clk_out) begin
        locked_sync <= locked;
        clk_locked <= locked_sync;
    end
`else
    // Sin primitivas de PLL en simulacion, igual que `pll_120`. Los dos relojes
    // pasan a ser el de entrada, asi que una simulacion de `top` no reproduce
    // la relacion 5x ni el cruce de dominios: eso se comprueba en banco aparte.
    assign clk_5x_out = clk_in;
    assign clk_out = clk_in;
    initial clk_locked = 1'b1;
`endif
endmodule
