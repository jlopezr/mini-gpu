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
//   0x80000018  VIDEO_CTRL RW  bits 1:0  modo de salida
//                                  0  BLANK    negro, sin leer la memoria
//                                  1  PATTERN  patron de prueba, sin leerla
//                                  2  SCANOUT  framebuffer desde la memoria
//                                  3  reservado (se trata como BLANK)
//
// Los dos registros de `frame_capture` (+0x10 y +0x14) no existen aqui: esa
// capacidad llego en la 18. Leen cero, igual que cualquier registro que no
// existe. VIDEO_CTRL conserva su offset pese al hueco, porque el contrato es de
// DIRECCIONES y no de orden de aparicion.
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

// ---------------------------------------------------------------------------
// Por que las bases arrancan en cero
// ---------------------------------------------------------------------------
//
// Hasta la unificacion valian 0x01000000 y 0x01025800, y la razon era que un
// programa que dibujara ahi funcionaba sin configurar nada. Esa ventaja ya no
// existe: desde que el modo de reset es PATTERN, un programa que quiera que se
// vea lo que dibuja tiene que escribir VIDEO_CTRL de todas formas, y quien
// escribe un registro puede escribir tres.
//
// A cambio, cablearlas tenia dos costes. Uno es que 0x01000000 no es una
// direccion valida en todos los mapas --en la 12, con 128 KiB de EBR, cae
// fuera--, asi que el valor por defecto era correcto solo por coincidencia. El
// otro es que mapa-de-memoria.md dice que esas bases "no son reservas
// impuestas a todos los programas", y cableadas en el reset si lo eran.
//
// Cero no es una direccion util --es el principio de la memoria, donde esta el
// propio programa--, y eso es deliberado: no pretende funcionar sin que nadie
// la escriba. El programa elige donde quiere su framebuffer y lo dice.
//
// Los parametros se quedan: los bancos de pruebas los usan para poner los
// buffers donde les conviene sin depender del valor de encendido.

module video_registers #(
    parameter [31:0] FB_FRONT_RESET = 32'h0000_0000,
    parameter [31:0] FB_BACK_RESET  = 32'h0000_0000
) (
    input wire clk,
    input wire reset,

    // Acceso desde el adaptador. Siempre una palabra de 32 bits con mascara de
    // byte: la CPU escribe 4'b1111 y el monitor un solo byte.
    input wire select,
    input wire write,
    input wire [3:0] write_mask,
    input wire [7:0] address,     // byte dentro de la ventana del dispositivo; [7:2] elige registro
    input wire [31:0] write_data,
    output reg [31:0] read_data,

    // Interfaz con el subsistema de video
    input wire fill_start,
    input wire fill_first,
    output wire [23:0] fb_base,    // direccion de palabra de 16 bits
    input wire underflow_pix,      // nivel pegajoso del dominio de pixel

    // Modo de salida (VIDEO_CTRL). Tras el reset vale PATTERN y no SCANOUT, y
    // no es un descuido: la memoria recien encendida contiene basura, asi que
    // arrancar en SCANOUT seria elegir un valor por defecto cuya salida es
    // indefinida. Con PATTERN, ver el patron demuestra que la cadena hasta el
    // monitor funciona y no verlo senala aguas arriba. El razonamiento entero
    // esta en 22.fpga-gpu-bl8/video-scanout.md.
    output reg [1:0] video_mode,

    output wire [31:0] debug_front,
    output wire [31:0] debug_back
);
  localparam [5:0] REG_FB_FRONT = 6'd0;
  localparam [5:0] REG_FB_BACK  = 6'd1;
  localparam [5:0] REG_SWAP     = 6'd2;
  localparam [5:0] REG_STATUS   = 6'd3;
  // Los indices 4 y 5 se saltan: son los dos registros de `frame_capture`, que
  // esta carpeta no tiene. El hueco se respeta para que VIDEO_CTRL caiga en la
  // misma direccion que en el resto de la familia y en la MiniGPU.
  //
  // Los nombres no se escriben ni en comentario: `capabilities.json` detecta
  // las capacidades buscando texto en este fichero, asi que nombrar aqui un
  // registro que no existe hacia que la 16 declarase tenerlo.
  localparam [5:0] REG_CTRL     = 6'd6;

  // Modos de salida. Los mismos numeros que gpu_video_regs.v.
  localparam [1:0] MODE_BLANK   = 2'd0;
  localparam [1:0] MODE_PATTERN = 2'd1;
  localparam [1:0] MODE_SCANOUT = 2'd2;

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

  // Seis bits, no dos: la ventana del dispositivo son 256 bytes aunque esta
  // carpeta solo tenga cuatro registros. Un registro que no existe lee cero,
  // que es lo que ya hacia antes el resto de la ventana.
  wire [5:0] selected = address[7:2];

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
      video_mode <= MODE_PATTERN;
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
          REG_CTRL:     if (write_mask[0]) video_mode <= write_data[1:0];
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
      REG_STATUS:   read_data = {frame_count, 14'd0, swap_pending,
                                 underflow_sync_1};
      REG_CTRL:     read_data = {30'd0, video_mode};
      // STATUS pasa a ser explicito: con la ventana de 16 bytes, `default` era
      // STATUS y nada mas, porque no habia mas direcciones. Ahora la ventana
      // son 256 bytes y dejarlo en `default` haria que los 60 registros que no
      // existen devolvieran el contador de frames en vez de cero.
      default:      read_data = 32'd0;
    endcase
  end
endmodule

`default_nettype wire
