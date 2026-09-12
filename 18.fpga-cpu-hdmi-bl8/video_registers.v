`default_nettype none

// Registros de video, accesibles en 0x80000000 por la CPU y por el monitor.
//
//   0x80000000  FB_FRONT   RW  direccion de byte del buffer que se muestra
//   0x80000004  FB_BACK    RW  direccion de byte del buffer que se dibuja
//   0x80000008  SWAP       RW  escribir: pide intercambio en el proximo frame
//                              leer bit 0: intercambio pendiente
//   0x8000000c  STATUS     R   bit 0    underflow del line buffer (pegajoso)
//                              bit 1    intercambio pendiente
//                              31:16    contador de frames
//
// Las direcciones de framebuffer se alinean a cuatro bytes: los dos bits bajos
// se ignoran al escribir y se leen como cero. El scanout necesita direcciones
// de palabra de 16 bits, asi que `fb_base` sale ya desplazado.
//
// ---------------------------------------------------------------------------
// El swap, y por que ocurre donde ocurre
// ---------------------------------------------------------------------------
//
// Intercambiar los buffers a mitad de frame parte la imagen: la mitad de
// arriba sale de un buffer y la de abajo del otro. Hay que hacerlo cuando no
// queda nada del frame anterior por leer y no se ha leido nada del siguiente.
//
// Ese instante existe y es exacto: la PRIMERA peticion de linea de un frame.
// El scanout la marca con `fill_first`. No hace falta cruzar una senal de
// VBlank desde el dominio de pixel ni razonar sobre cual de los dos cruces
// llega antes, porque el swap viaja dentro de la propia peticion.
//
// `fb_base` es combinacional respecto a esa decision a proposito. El lector de
// lineas registra su direccion base en el mismo flanco en que se actualizan
// `fb_front` y `fb_back`, asi que si `fb_base` fuera un registro, la linea 0
// usaria el buffer viejo y las demas el nuevo: un desgarro de una linea, justo
// el fallo que este mecanismo existe para evitar.
//
// El contador de frames tambien avanza con `fill_first`: es un VBlank contado
// en el dominio de sistema, sin cruces adicionales. Sirve para esperar a un
// frame sin sondear un nivel, y para detectar frames perdidos.

module video_registers #(
    parameter [31:0] FB_FRONT_RESET = 32'h0100_0000,
    parameter [31:0] FB_BACK_RESET  = 32'h0102_5800  // 320*240*2 bytes despues
) (
    input wire clk,
    input wire reset,

    // Acceso desde el adaptador. Siempre una palabra de 32 bits con mascara de
    // byte: la CPU escribe 4'b1111 y el monitor un solo byte.
    input wire select,
    input wire write,
    input wire [3:0] write_mask,
    input wire [3:0] address,      // byte dentro de la ventana; [3:2] elige registro
    input wire [31:0] write_data,
    output reg [31:0] read_data,

    // Interfaz con el subsistema de video
    input wire fill_start,
    input wire fill_first,
    output wire [23:0] fb_base,    // direccion de palabra de 16 bits
    input wire underflow_pix,      // nivel pegajoso del dominio de pixel

    output wire [31:0] debug_front,
    output wire [31:0] debug_back
);
  localparam [1:0] REG_FB_FRONT = 2'd0;
  localparam [1:0] REG_FB_BACK  = 2'd1;
  localparam [1:0] REG_SWAP     = 2'd2;
  localparam [1:0] REG_STATUS   = 2'd3;

  reg [31:0] fb_front;
  reg [31:0] fb_back;
  reg swap_pending;
  reg [15:0] frame_count;

  // El underflow nace en el dominio de pixel. Es un nivel pegajoso, asi que
  // basta con sincronizarlo; no hay pulso que perder.
  reg underflow_sync_0, underflow_sync_1;
  always @(posedge clk) begin
    underflow_sync_0 <= underflow_pix;
    underflow_sync_1 <= underflow_sync_0;
  end

  wire [1:0] selected = address[3:2];

  // El instante del intercambio. Ver la explicacion de arriba.
  wire swap_now = fill_start && fill_first && swap_pending;
  wire [31:0] fb_display = swap_now ? fb_back : fb_front;
  assign fb_base = fb_display[24:1];

  assign debug_front = fb_front;
  assign debug_back = fb_back;

  // Mezcla por bytes, para que el monitor pueda escribir un registro byte a
  // byte sin destruir los otros tres.
  function [31:0] merge(input [31:0] old_value, input [31:0] new_value,
                        input [3:0] mask);
    begin
      merge = {mask[3] ? new_value[31:24] : old_value[31:24],
               mask[2] ? new_value[23:16] : old_value[23:16],
               mask[1] ? new_value[15:8]  : old_value[15:8],
               mask[0] ? new_value[7:0]   : old_value[7:0]};
    end
  endfunction

  wire bus_write = select && write;
  // Verilog no admite seleccionar bits del resultado de una funcion, asi que
  // la mezcla se materializa en una senal antes de forzar el alineamiento.
  wire [31:0] merged_front = merge(fb_front, write_data, write_mask);
  wire [31:0] merged_back = merge(fb_back, write_data, write_mask);

  always @(posedge clk) begin
    if (reset) begin
      fb_front <= FB_FRONT_RESET;
      fb_back <= FB_BACK_RESET;
      swap_pending <= 1'b0;
      frame_count <= 16'd0;
    end else begin
      // El intercambio va primero para que una escritura del bus en el mismo
      // ciclo gane: si el software fija una base justo ahora, esa es la que
      // quiere, no la que acaba de rotar.
      if (swap_now) begin
        fb_front <= fb_back;
        fb_back <= fb_front;
        swap_pending <= 1'b0;
      end

      if (fill_start && fill_first) frame_count <= frame_count + 1'b1;

      if (bus_write) begin
        case (selected)
          REG_FB_FRONT: fb_front <= {merged_front[31:2], 2'b00};
          REG_FB_BACK:  fb_back  <= {merged_back[31:2], 2'b00};
          // Cualquier escritura pide intercambio. Si cae en el mismo ciclo que
          // uno en curso, queda pendiente para el frame siguiente y no se
          // pierde, que es lo que pasaria si el `swap_now` de arriba ganara.
          REG_SWAP:     swap_pending <= 1'b1;
          default: ;  // STATUS es de solo lectura
        endcase
      end
    end
  end

  always @(*) begin
    case (selected)
      REG_FB_FRONT: read_data = fb_front;
      REG_FB_BACK:  read_data = fb_back;
      REG_SWAP:     read_data = {31'd0, swap_pending};
      default:      read_data = {frame_count, 14'd0, swap_pending,
                                 underflow_sync_1};
    endcase
  end
endmodule

`default_nettype wire
