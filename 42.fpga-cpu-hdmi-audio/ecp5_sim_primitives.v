`ifdef NO_INCLUDES
/* Icarus' ECP5 cells_sim in the Apio bundle lacks ODDRX1F.  This behavioral
 * model is only present in `apio test`; Yosys/nextpnr still infer the real IO
 * primitive from the RTL. */
module ODDRX1F(input wire D0, input wire D1, input wire SCLK, input wire RST,
               output reg Q);
  always @(posedge SCLK) if (RST) Q <= 1'b0; else Q <= D0;
  always @(negedge SCLK) if (RST) Q <= 1'b0; else Q <= D1;
endmodule
`endif
