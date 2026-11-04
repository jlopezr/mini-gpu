`default_nettype none

// Reloj del dominio de CPU y monitor: 100 MHz.
//
// Fue de 120 mientras el monitor no tuvo WRITE_WORD. Con el comando dentro no
// cumple NINGUNA semilla: barrido de ocho entre 85,92 y 99,40 MHz, mediana
// 88,93. No es la colocacion, es el diseno, asi que se baja la restriccion en
// vez de perseguir semillas -- el mismo camino que ya tomaron 16 (120 -> 100)
// y 18 (100 -> 80), y por la misma razon.
//
// Los parametros son los de `16.fpga-cpu-hdmi/pll_cpu.v`, que es la misma
// placa a la misma frecuencia y esta probado, salvo CLKOP_CPHASE: aqui es
// CLKOP_DIV-1 (5) y alli DIV/2 (3). Con DIV/2 la salida queda 120 grados
// desfasada de la entrada y Diamond >= 3.10 aborta en Map ("should not be used
// as the feedback signal"); yosys/nextpnr lo aceptan sin avisar. Con DIV-1 la
// fase es 0. Probado con Diamond 3.14.
//
//   fref  = 25 / CLKI_DIV(5)         =   5 MHz
//   CLKOP = fref * CLKFB_DIV(20)     = 100 MHz
//   VCO   = CLKOP * CLKOP_DIV(6)     = 600 MHz, dentro del rango del ECP5
module pll_100 (
    input  wire clkin,    // 25 MHz, 0 deg
    output wire clkout0,  // 100 MHz, 0 deg
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
    // El EHXPLLL tiene mas salidas de las que usamos (CLKOS, ENCLKOS...). No
    // conectarlas es lo normal en una primitiva de Lattice, asi que se silencia
    // aqui y solo aqui: avisos fijos tapan los que si importan.
  // verilator lint_off PINMISSING
  EHXPLLL #(
      .PLLRST_ENA("DISABLED"), .INTFB_WAKE("DISABLED"),
      .STDBY_ENABLE("DISABLED"), .DPHASE_SOURCE("DISABLED"),
      .OUTDIVIDER_MUXA("DIVA"), .OUTDIVIDER_MUXB("DIVB"),
      .OUTDIVIDER_MUXC("DIVC"), .OUTDIVIDER_MUXD("DIVD"),
      .CLKI_DIV(5), .CLKOP_ENABLE("ENABLED"), .CLKOP_DIV(6),
      .CLKOP_CPHASE(5), .CLKOP_FPHASE(0), .FEEDBK_PATH("INT_OP"),
      .CLKFB_DIV(20)
  ) pll_i (
      .RST(1'b0), .STDBY(1'b0), .CLKI(clkin), .CLKOP(clkout0),
      .CLKFB(clkfb), .CLKINTFB(clkfb), .PHASESEL0(1'b0),
      .PHASESEL1(1'b0), .PHASEDIR(1'b1), .PHASESTEP(1'b1),
      .PHASELOADREG(1'b1), .PLLWAKESYNC(1'b0), .ENCLKOP(1'b0),
      .LOCK(locked)
  );
      // verilator lint_on PINMISSING
`else
  // Behavioral fallback so logic-only testbenches do not require ECP5 primitives.
  assign clkout0 = clkin;
  assign locked  = 1'b1;
`endif
endmodule

`default_nettype wire
