`default_nettype none

// Reloj del dominio de CPU y monitor: 50 MHz, del oscilador de 25 MHz.
//
// Parametros de `ecppll -i 25 -o 50`: VCO a 600 MHz (25 / 1 * 2 * 12), salida
// /12. La SDRAM tiene su propio dominio de 100 MHz en `pll_mem.v` y el video el
// suyo en `clock2_gen.v`; los dos cruces ya pasan por FIFOs y sincronizadores.
// Hasta el 12 de noviembre la CPU iba a 25 MHz, directa del oscilador, para
// tener margen mientras se segmentaba el pipeline.
//
// En simulacion (sin SYNTHESIZE) la salida es la entrada.
module pll_cpu (
    input  wire clkin,
    output wire clkout0,
    output wire locked
);
`ifdef SYNTHESIZE
  wire clkfb;
  (* FREQUENCY_PIN_CLKI="25" *)
  (* FREQUENCY_PIN_CLKOP="50" *)
  (* ICP_CURRENT="12" *)
  (* LPF_RESISTOR="8" *)
  (* MFG_ENABLE_FILTEROPAMP="1" *)
  (* MFG_GMCREF_SEL="2" *)
  EHXPLLL #(
      .PLLRST_ENA("DISABLED"), .INTFB_WAKE("DISABLED"),
      .STDBY_ENABLE("DISABLED"), .DPHASE_SOURCE("DISABLED"),
      .OUTDIVIDER_MUXA("DIVA"), .OUTDIVIDER_MUXB("DIVB"),
      .OUTDIVIDER_MUXC("DIVC"), .OUTDIVIDER_MUXD("DIVD"),
      .CLKI_DIV(1), .CLKOP_ENABLE("ENABLED"), .CLKOP_DIV(12),
      .CLKOP_CPHASE(5), .CLKOP_FPHASE(0), .FEEDBK_PATH("CLKOP"),
      .CLKFB_DIV(2)
  ) pll_i (
      .RST(1'b0), .STDBY(1'b0), .CLKI(clkin), .CLKOP(clkout0),
      .CLKFB(clkout0), .PHASESEL0(1'b0),
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
