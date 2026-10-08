`default_nettype none

// Reloj del dominio de CPU, monitor y SDRAM: 80 MHz.
//
// La escalera completa, y siempre por el mismo motivo: el emplazador pierde
// libertad y el camino critico pasa a estar dominado por routing.
//
//   10.fpga-cpu-ram   CPU sola                        130,67 MHz alcanzados
//   16.fpga-cpu-hdmi  + subsistema de video           100 MHz, 8 de 8 semillas
//   18 (esta)         + camino de memoria de 128 bits  80 MHz, 8 de 8 semillas
//
// Con la restriccion en 100, el camino de rafagas no cumple NINGUNA semilla:
// entre 83,9 y 91,8 MHz, mediana 86,4. Se probaron los arreglos de RTL que
// tenian sentido --comparadores de rango por bits altos, `urgent` registrado,
// comparacion de etiquetas en paralelo, concesion del arbitro registrada-- y
// llegado ese punto el camino es de routing casi puro: 8,75 ns de 11,2 en la
// ultima medida. Eso no se arregla acortando logica, porque las celdas estan
// fisicamente lejos; es el mismo techo que el README de la 16 describe para el
// monitor.
//
// Asi que se baja la restriccion, como hizo la 16, y por el mismo motivo: la
// loteria de semillas deja de decidir si el diseno funciona. El coste es un
// 20 % de reloj sobre una mejora de 2,94x, o sea 2,35x netos.
//
// 80 MHz ademas mantiene el baudio: divisor 80, multiplo de cuatro, y
// 80/80 = 1 Mbaud, que el FTDI genera exacto como 3/3. Ver README.md.
//
//   fref = 25 / CLKI_DIV(5)          =   5 MHz
//   CLKOP = fref * CLKFB_DIV(16)     =  80 MHz
//   VCO   = CLKOP * CLKOP_DIV(8)     = 640 MHz, dentro del rango del ECP5
module pll_cpu (
    input  wire clkin,
    output wire clkout0,
    output wire locked
);
`ifdef SYNTHESIZE
  wire clkfb;
  (* FREQUENCY_PIN_CLKI="25" *)
  (* FREQUENCY_PIN_CLKOP="80" *)
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
      .CLKI_DIV(5), .CLKOP_ENABLE("ENABLED"), .CLKOP_DIV(8),
      .CLKOP_CPHASE(4), .CLKOP_FPHASE(0), .FEEDBK_PATH("INT_OP"),
      .CLKFB_DIV(16)
  ) pll_i (
      .RST(1'b0), .STDBY(1'b0), .CLKI(clkin), .CLKOP(clkout0),
      .CLKFB(clkfb), .CLKINTFB(clkfb), .PHASESEL0(1'b0),
      .PHASESEL1(1'b0), .PHASEDIR(1'b1), .PHASESTEP(1'b1),
      .PHASELOADREG(1'b1), .PLLWAKESYNC(1'b0), .ENCLKOP(1'b0),
      .LOCK(locked)
  );
      // verilator lint_on PINMISSING
`else
  assign clkout0 = clkin;
  assign locked = 1'b1;
`endif
endmodule

`default_nettype wire
