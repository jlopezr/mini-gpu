`default_nettype none

module pll_mem #(
    // Fase de CLKOS (el reloj de la SDRAM) al salir de fabrica, en pasos de
    // 1/8 de ciclo de VCO (208 ps). Debe coincidir con INITIAL_POS de
    // pll_phase_ctl: top.v pasa el mismo SDRAM_PHASE a los dos.
    parameter integer CLKOS_POS = 0
) (
    input  wire clkin,
    output wire clkout0,
    output wire clkout1,
    input  wire phasestep,
    input  wire phasedir,
    input  wire phaseloadreg,
    input  wire [1:0] phasesel,
    output wire locked
);

`ifdef SYNTHESIZE

    wire clkfb;

    (* FREQUENCY_PIN_CLKI="25" *)
    (* FREQUENCY_PIN_CLKOP="100" *)
    (* ICP_CURRENT="12" *)
    (* LPF_RESISTOR="8" *)
    (* MFG_ENABLE_FILTEROPAMP="1" *)
    (* MFG_GMCREF_SEL="2" *)

    // verilator lint_off PINMISSING
    EHXPLLL #(
        .PLLRST_ENA("DISABLED"),
        .INTFB_WAKE("DISABLED"),
        .STDBY_ENABLE("DISABLED"),
        .DPHASE_SOURCE("ENABLED"),

        .OUTDIVIDER_MUXA("DIVA"),
        .OUTDIVIDER_MUXB("DIVB"),
        .OUTDIVIDER_MUXC("DIVC"),
        .OUTDIVIDER_MUXD("DIVD"),

        // 25 / 5 = 5 MHz reference
        .CLKI_DIV(5),

        .CLKOP_ENABLE("ENABLED"),
        .CLKOS_ENABLE("ENABLED"),

        // 5 * 20 = 100 MHz
        .CLKFB_DIV(20),

        // VCO = 100 * 6 = 600 MHz
        .CLKOP_DIV(6),

        .CLKOP_CPHASE(5),
        .CLKOP_FPHASE(0),
        .CLKOS_DIV(6),
        // CLKOP_CPHASE + 1 es un ciclo de VCO = 8 pasos finos:
        // POS = 8 * (CPHASE - 5) + FPHASE.
        .CLKOS_CPHASE(5 + CLKOS_POS / 8),
        .CLKOS_FPHASE(CLKOS_POS % 8),

        .FEEDBK_PATH("INT_OP")
    ) pll_i (
        .RST(1'b0),
        .STDBY(1'b0),

        .CLKI(clkin),
        .CLKOP(clkout0),
        .CLKOS(clkout1),

        .CLKFB(clkfb),
        .CLKINTFB(clkfb),

        .PHASESEL0(phasesel[0]),
        .PHASESEL1(phasesel[1]),
        .PHASEDIR(phasedir),
        .PHASESTEP(phasestep),
        .PHASELOADREG(phaseloadreg),
        .PLLWAKESYNC(1'b0),
        .ENCLKOP(1'b0),

        .LOCK(locked)
    );
    // verilator lint_on PINMISSING

`else

    assign clkout0 = clkin;
    assign clkout1 = clkin;
    assign locked  = 1'b1;

`endif

endmodule

`default_nettype wire
