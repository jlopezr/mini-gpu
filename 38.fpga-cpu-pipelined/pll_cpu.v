`default_nettype none

// Reloj del dominio de CPU y monitor: 25 MHz.
//
// En este prototipo se baja deliberadamente a la frecuencia del oscilador de la
// placa para probar si los fallos restantes son de timing del pipeline. La SDRAM
// conserva su propio dominio de 100 MHz en `pll_mem.v`; el cruce hacia memoria
// ya pasa por FIFOs.
//
// Sin PLL aqui no hay reloj generado que ajustar: `clkout0` es `clk_25mhz`.
module pll_cpu (
    input  wire clkin,
    output wire clkout0,
    output wire locked
);
  assign clkout0 = clkin;
  assign locked = 1'b1;
endmodule

`default_nettype wire
