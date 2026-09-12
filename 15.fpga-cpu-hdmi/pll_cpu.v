`default_nettype none

// Reloj del dominio de CPU, monitor y SDRAM: 100 MHz.
//
// Fue de 120 MHz mientras la CPU estuvo sola en el chip (10.fpga-cpu-ram
// alcanzaba 130,67 MHz). Al anadir el subsistema de video el emplazador pierde
// libertad y el mismo camino critico de siempre -- interno a la CPU, de
// `instruction` a `pc` -- deja de cumplir: ninguna semilla pasa de 111 MHz.
// Se baja la restriccion en lugar de perseguir semillas. Ver README.md.
//
//   fref = 25 / CLKI_DIV(5)          =   5 MHz
//   CLKOP = fref * CLKFB_DIV(20)     = 100 MHz
//   VCO   = CLKOP * CLKOP_DIV(6)     = 600 MHz, dentro del rango del ECP5
module pll_cpu (
    input  wire clkin,
    output wire clkout0,
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
  EHXPLLL #(
      .PLLRST_ENA("DISABLED"), .INTFB_WAKE("DISABLED"),
      .STDBY_ENABLE("DISABLED"), .DPHASE_SOURCE("DISABLED"),
      .OUTDIVIDER_MUXA("DIVA"), .OUTDIVIDER_MUXB("DIVB"),
      .OUTDIVIDER_MUXC("DIVC"), .OUTDIVIDER_MUXD("DIVD"),
      .CLKI_DIV(5), .CLKOP_ENABLE("ENABLED"), .CLKOP_DIV(6),
      .CLKOP_CPHASE(3), .CLKOP_FPHASE(0), .FEEDBK_PATH("INT_OP"),
      .CLKFB_DIV(20)
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
