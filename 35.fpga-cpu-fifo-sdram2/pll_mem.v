`default_nettype none

module pll_mem (
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

        .CLKOP_CPHASE(3),
        .CLKOP_FPHASE(0),
        .CLKOS_DIV(6),
        .CLKOS_CPHASE(3),
        .CLKOS_FPHASE(0),

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
