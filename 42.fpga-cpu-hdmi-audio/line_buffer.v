`default_nettype none

// Dos bancos de linea en EBR, con reloj de escritura y de lectura distintos.
//
// Es el unico sitio donde los dos dominios tocan el mismo dato. No hay
// sincronizacion aqui a proposito: quien garantiza que nunca se lee un banco
// mientras se escribe es el handshake de `video_scanout`. La memoria solo tiene
// que cumplir que lectura y escritura de bancos DISTINTOS son independientes,
// que es justo lo que da un EBR en modo pseudo-dual-port.
//
// Una linea fuente de 320 pixeles RGB565 son 5120 bits, asi que cada banco cabe
// holgadamente en un EBR de 18 kbit.

module line_buffer #(
    parameter integer ADDR_BITS = 9
) (
    input wire wr_clk,
    input wire wr_en,
    input wire wr_bank,
    input wire [ADDR_BITS-1:0] wr_addr,
    input wire [15:0] wr_data,

    input wire rd_clk,
    input wire rd_bank,
    input wire [ADDR_BITS-1:0] rd_addr,
    output reg [15:0] rd_data
);
  reg [15:0] mem [0:(2 << ADDR_BITS) - 1];

  always @(posedge wr_clk) begin
    if (wr_en) mem[{wr_bank, wr_addr}] <= wr_data;
  end

  // Una etapa de registro: el dato de `rd_addr` sale en el ciclo siguiente.
  // `video_scanout` retrasa los sincronismos para compensarla.
  always @(posedge rd_clk) begin
    rd_data <= mem[{rd_bank, rd_addr}];
  end
endmodule

`default_nettype wire
