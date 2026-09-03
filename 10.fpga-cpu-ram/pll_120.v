`default_nettype none

module pll_120 (
    input  wire clkin,
    output wire clkout0,
    output wire locked
);
`ifdef SYNTHESIZE
  wire clkfb;
  (* FREQUENCY_PIN_CLKI="25" *)
  (* FREQUENCY_PIN_CLKOP="120" *)
  (* ICP_CURRENT="12" *)
  (* LPF_RESISTOR="8" *)
  (* MFG_ENABLE_FILTEROPAMP="1" *)
  (* MFG_GMCREF_SEL="2" *)
  EHXPLLL #(
      .PLLRST_ENA("DISABLED"), .INTFB_WAKE("DISABLED"),
      .STDBY_ENABLE("DISABLED"), .DPHASE_SOURCE("DISABLED"),
      .OUTDIVIDER_MUXA("DIVA"), .OUTDIVIDER_MUXB("DIVB"),
      .OUTDIVIDER_MUXC("DIVC"), .OUTDIVIDER_MUXD("DIVD"),
      .CLKI_DIV(5), .CLKOP_ENABLE("ENABLED"), .CLKOP_DIV(5),
      .CLKOP_CPHASE(2), .CLKOP_FPHASE(0), .FEEDBK_PATH("INT_OP"),
      .CLKFB_DIV(24)
  ) pll_i (
      .RST(1'b0), .STDBY(1'b0), .CLKI(clkin), .CLKOP(clkout0),
      .CLKFB(clkfb), .CLKINTFB(clkfb), .PHASESEL0(1'b0),
      .PHASESEL1(1'b0), .PHASEDIR(1'b1), .PHASESTEP(1'b1),
      .PHASELOADREG(1'b1), .PLLWAKESYNC(1'b0), .ENCLKOP(1'b0),
      .LOCK(locked)
  );
`else
  assign clkout0 = clkin;
  assign locked = 1'b1;
`endif
endmodule

`default_nettype wire
