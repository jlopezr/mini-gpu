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
 *   0x80000300 - 0x800003FF   dispositivo 3   contadores de rendimiento
 *   0x80000400 - 0x80000EFF   dispositivos 4..14, libres
 *   0x80000F00 - 0x80000FFF   dispositivo 15  identificacion (sysid)
 *
 * El slot 3 no se elige: es el que `mapa-de-memoria.md` §6 ya reservaba para
 * los contadores, y el que la MiniGPU ocupa desde antes. El bloque de CPU es un
 * PREFIJO del de GPU --CYCLES en +0x00 y RETIRED en +0x04 en las dos-- asi que
 * un programa que lea esos dos registros vale en las dos familias.
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
 * Un dispositivo ausente o un offset reservado da error. El select se
 * filtra antes del periferico para que un acceso rechazado no tenga efectos.
 * El error acompana al dato hasta el ack del nucleo o del monitor.
 */
module mmio_decoder #(
    // Identidad de esta carpeta, para el bloque de 0x80000F00. Va por
    // parametro y no cableada aqui para que `mmio_decoder.v` siga siendo copia
    // identica entre prototipos: lo que cambia de uno a otro vive en su top.v,
    // junto a los demas parametros. Un test comprueba que el numero coincide
    // con el del directorio.
    parameter [7:0] FOLDER = 8'd0,
    parameter [31:0] ISA_PROFILE = 32'd0,
    parameter HAS_SERIAL = 1,
    parameter [63:0] VIDEO_REGISTERS = 64'h7f
) (
    // Desde mmio_mux.
    input  wire        select,
    input  wire        write,
    input  wire [11:0] address,

    // Hacia cada dispositivo: el `select` ya filtrado.
    output wire        video_select,
    input  wire [31:0] video_read_data,

    output wire        serial_select,
    input  wire [31:0] serial_read_data,

    // Los contadores son de solo lectura, asi que no necesitan `select`.
    input  wire [31:0] perf_read_data,

    output reg  [31:0] read_data,
    output reg         error
);
  localparam [3:0] DEV_VIDEO  = 4'd0;
  localparam [3:0] DEV_SERIAL = 4'd2;
  localparam [3:0] DEV_PERF   = 4'd3;
  // El ULTIMO, no el primero libre: asi los dispositivos de verdad pueden
  // crecer hacia arriba sin tropezarse con el, y la direccion de identificacion
  // es la misma en las dos familias --0x80000F00-- que es todo el objetivo.
  localparam [3:0] DEV_SYSID  = 4'd15;

  wire [3:0] device = address[11:8];

  assign video_select  = select && !error && (device == DEV_VIDEO);
  assign serial_select = select && !error && (device == DEV_SERIAL);

  // Constantes de solo lectura: no necesita `select` ni reloj, asi que se
  // instancia aqui en vez de sacar otro par de puertos al top.
  wire [31:0] sysid_read_data;
  sysid #(.FOLDER(FOLDER), .ISA_PROFILE(ISA_PROFILE))
      sysid_i (.word(address[3:2]), .read_data(sysid_read_data));

  // `read_data` no depende de `select`: el cliente solo lo mira en el ciclo de
  // su `ack`, y dejarlo fuera del mux ahorra un nivel.
  always @* begin
    error = 1'b0;
    case (device)
      DEV_VIDEO:  error = !VIDEO_REGISTERS[address[7:2]];
      DEV_SERIAL: error = !HAS_SERIAL || address[7:2] > 6'd2;
      DEV_PERF:   error = address[7:2] > 6'd1 || write;
      DEV_SYSID:  error = address[7:4] != 0 || write;
      default:    error = 1'b1;
    endcase
    case (device)
      DEV_VIDEO:  read_data = video_read_data;
      DEV_SERIAL: read_data = serial_read_data;
      DEV_PERF:   read_data = perf_read_data;
      DEV_SYSID:  read_data = sysid_read_data;
      default:    read_data = 32'd0;
    endcase
  end
endmodule

`default_nettype wire
