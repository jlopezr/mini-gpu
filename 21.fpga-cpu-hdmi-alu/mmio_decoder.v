`default_nettype none

/*
 * Reparte la ventana MMIO entre dispositivos.
 *
 * Hasta ahora la ventana eran 32 bytes y dentro solo estaba el video, asi que
 * `mmio_mux` iba cableado directo a `video_registers`. Con mas de un
 * dispositivo hace falta decidir a quien va el `select` y de quien viene el
 * dato leido, y eso es todo lo que hace este modulo.
 *
 * Mapa:
 *
 *   0x80000000 - 0x800000FF   dispositivo 0   video
 *   0x80000100 - 0x800001FF   dispositivo 1   RESERVADO: depuracion
 *   0x80000200 - 0x800002FF   dispositivo 2   serie
 *   0x80000300 - 0x80000FFF   dispositivos 3..15, libres
 *
 * El hueco del 1 no es casualidad ni desorden: en la familia MiniGPU
 * (12/14/17) `0x80000100` ya es la ventana de depuracion global --contadores,
 * warp y lane del primer fallo--. Dejarlo reservado aqui permite que las dos
 * familias converjan sin recolocar nada, y que `mapa-de-memoria.md` describa un
 * solo mapa en vez de dos parecidos.
 *
 * COSTE. Ensanchar la ventana ABARATA la comparacion de prefijo: los dos
 * adaptadores pasan de comparar `address[31:5]` --27 bits-- a `address[31:12]`
 * --20--. Lo que se anade aqui es un nivel de LUT en el mux de `read_data`, que
 * crece con los dispositivos que EXISTEN, no con el tamano del mapa: reservar
 * dieciseis ventanas no cuesta nada. Y el camino critico de esta carpeta no
 * pasa por aqui: es el handshake de SDRAM, `scanout_i.req_line` ->
 * `source_i.req_addr`, 29 etapas.
 *
 * Un dispositivo que no existe lee cero y se traga las escrituras, que es lo
 * que ya hacian los dos registros libres de la ventana del video. La
 * alternativa --levantar un error de bus como hace `gpu_system.v` con
 * `mmio_bad`-- obliga a cablear una ruta de ERROR_MEMORY_ACCESS nueva, y se
 * deja para cuando haya dispositivos suficientes como para perderlos de vista.
 */
module mmio_decoder (
    // Desde mmio_mux.
    input  wire        select,
    input  wire [11:0] address,

    // Hacia cada dispositivo: el `select` ya filtrado.
    output wire        video_select,
    input  wire [31:0] video_read_data,

    output wire        serial_select,
    input  wire [31:0] serial_read_data,

    output reg  [31:0] read_data
);
  localparam [3:0] DEV_VIDEO  = 4'd0;
  localparam [3:0] DEV_SERIAL = 4'd2;

  wire [3:0] device = address[11:8];

  assign video_select  = select && (device == DEV_VIDEO);
  assign serial_select = select && (device == DEV_SERIAL);

  // `read_data` no depende de `select`: el cliente solo lo mira en el ciclo de
  // su `ack`, y dejarlo fuera del mux ahorra un nivel.
  always @* begin
    case (device)
      DEV_VIDEO:  read_data = video_read_data;
      DEV_SERIAL: read_data = serial_read_data;
      default:    read_data = 32'd0;
    endcase
  end
endmodule

`default_nettype wire
