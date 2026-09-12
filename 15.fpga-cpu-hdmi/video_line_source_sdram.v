`default_nettype none

// Productor de lineas del hito C: lee una linea del framebuffer en SDRAM.
//
// Sustituye a `video_line_source_pattern` sin cambiar el contrato:
//
//   fill_start        -> pulso: rellena la linea `fill_line`
//   fill_we/addr/data -> SRC_W palabras, direcciones 0..SRC_W-1
//   fill_done         -> pulso: linea completa
//
// Un pixel RGB565 ocupa 16 bits y el bus fisico de la SDRAM tambien, asi que
// cada pixel es exactamente un acceso: no hay que componer palabras ni
// preocuparse del endianness dentro del pixel. Es la razon de fondo por la que
// RGB565 es el formato comodo para empezar, incluso antes que INDEX8.
//
// El framebuffer es lineal, sin pitch propio:
//
//   direccion de byte    = FB_BASE + linea * SRC_W * 2 + x * 2
//   direccion de palabra = FB_BASE/2 + linea * SRC_W + x
//
// El adaptador trabaja en direcciones de palabra de 16 bits, asi que se usa la
// segunda forma. `line_base` se calcula una vez al recibir la peticion, no por
// pixel, lo que lo saca del camino critico del dominio de CPU.
//
// El producto `fill_line * SRC_W` acaba en un MULT18X18D. Se podria forzar a
// sumas de desplazamientos (320 = 256 + 64), pero eso ataria el modulo a un
// SRC_W concreto y el ECP5-85F tiene 156 DSP sin usar. Se deja el producto
// generico: una vez por linea, registrado y fuera de todo camino critico.
//
// Sin soporte de burst cada pixel es una transaccion independiente. Una linea
// son SRC_W transacciones y hay dos lineas de pantalla para completarla
// (64 us), de sobra incluso a un acceso cada diez ciclos. El dia que el
// controlador sepa hacer bursts, este es el modulo que cambia.

module video_line_source_sdram #(
    parameter integer SRC_W     = 320,
    parameter integer ADDR_BITS = 9,
    parameter integer LINE_BITS = 8,
    // Direccion de palabra de 16 bits del framebuffer. 24'h800000 son los
    // bytes 0x01000000, la region que el mapa de memoria reserva a graficos.
    parameter [23:0] FB_BASE_HALFWORD = 24'h800000
) (
    input wire clk,
    input wire reset,

    input wire fill_start,
    input wire [LINE_BITS-1:0] fill_line,
    output reg fill_we,
    output reg [ADDR_BITS-1:0] fill_addr,
    output reg [15:0] fill_data,
    output reg fill_done,

    output reg video_req,
    output wire [23:0] video_addr,
    input wire [15:0] video_read_data,
    input wire video_ready
);
  localparam [ADDR_BITS-1:0] LAST_X = SRC_W - 1;

  localparam [1:0] S_IDLE = 2'd0, S_REQUEST = 2'd1, S_WAIT = 2'd2;

  reg [1:0] state;
  reg [23:0] line_base;
  reg [ADDR_BITS-1:0] x;

  assign video_addr = line_base + {{(24-ADDR_BITS){1'b0}}, x};

  always @(posedge clk) begin
    if (reset) begin
      state <= S_IDLE;
      video_req <= 1'b0;
      fill_we <= 1'b0;
      fill_done <= 1'b0;
      fill_addr <= {ADDR_BITS{1'b0}};
      fill_data <= 16'h0000;
      line_base <= FB_BASE_HALFWORD;
      x <= {ADDR_BITS{1'b0}};
    end else begin
      fill_we <= 1'b0;
      fill_done <= 1'b0;

      case (state)
        S_IDLE:
          if (fill_start) begin
            line_base <= FB_BASE_HALFWORD + fill_line * SRC_W;
            x <= {ADDR_BITS{1'b0}};
            state <= S_REQUEST;
          end

        S_REQUEST: begin
          video_req <= 1'b1;
          state <= S_WAIT;
        end

        S_WAIT:
          if (video_ready) begin
            video_req <= 1'b0;
            fill_we <= 1'b1;
            fill_addr <= x;
            fill_data <= video_read_data;
            if (x == LAST_X) begin
              fill_done <= 1'b1;
              state <= S_IDLE;
            end else begin
              x <= x + 1'b1;
              state <= S_REQUEST;
            end
          end

        default: state <= S_IDLE;
      endcase
    end
  end
endmodule

`default_nettype wire
