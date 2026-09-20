`default_nettype none

/*
 * Reparte el espacio MMIO entre dispositivos. Contrato: 1.isa/mmio.md v2.
 *
 * Mapa (§2). Los bloques son de 64 KiB y estan alineados a 64 KiB, asi que el
 * bloque se elige con `address[26:16]` y el registro con `address[15:0]`:
 *
 *   0x8000_0000   SYSTEM            identificacion, memoria, version
 *   0x8010_0000   SERIAL
 *   0x8020_0000   VIDEO
 *   0x8101_0000   CPU PERFORMANCE
 *
 * Todo lo demas del espacio MMIO da error: dispositivo ausente, hueco
 * reservado u offset sin registro (§4.3). No devuelve cero en silencio.
 *
 * ---------------------------------------------------------------------
 * POR QUE BLOQUES GRANDES, si antes cabia todo en 4 KiB
 * ---------------------------------------------------------------------
 *
 * Esto sustituye a la pagina unica de 4 KiB con dieciseis ranuras de 256 B
 * (§21.6 y §21.7 la abandonan explicitamente). El mapa viejo no se quedo
 * pequeno por casualidad: compactar registros para ahorrar espacio de
 * direcciones dejo la ventana de configuracion de warps llena al 100 %, con
 * ocho descriptores y ni un hueco.
 *
 * Reservar no cuesta: un hueco de 64 KiB en el mapa no gasta ni un LUT,
 * porque lo que crece con el tamano del mapa es el numero de bits que se
 * comparan --once en vez de cuatro-- y no el mux de `read_data`, que crece
 * con los dispositivos que EXISTEN.
 *
 * ---------------------------------------------------------------------
 * EL ANCHO
 * ---------------------------------------------------------------------
 *
 * `address` entra ENTERA, de 32 bits. No se recorta aqui ni en el camino que
 * llega hasta aqui, y no es celo: la 18 declaro doce bits en este modulo y
 * cinco en su `top.v`, Verilog trunco al conectar el puerto sin decir nada, y
 * los dieciseis dispositivos cayeron todos sobre el de video --pedir `SYS_ID`
 * devolvia `FB_FRONT`--. No lo vio ningun banco porque ninguno instancia
 * `top`. Hoy lo vigila `x.tests/test_top_wiring.py`.
 *
 * El select se filtra antes del periferico para que un acceso rechazado no
 * tenga efectos. El error acompana al dato hasta el ack del nucleo o del
 * monitor.
 */
module mmio_decoder #(
    // Identidad de esta carpeta, para el bloque SYSTEM. Va por parametro y no
    // cableada aqui para que el fichero pueda ser copia entre prototipos: lo
    // que cambia de uno a otro vive en su top.v. Un test comprueba que el
    // numero coincide con el del directorio.
    parameter [7:0] FOLDER = 8'd0,
    parameter [31:0] ISA_PROFILE = 32'd0,
    parameter HAS_SERIAL = 1,
    // Que palabras del bloque VIDEO existen. Diez en MMIO v2 (§9): CTRL,
    // FB_FRONT, FB_BACK, SWAP, STATUS, FRAME_COUNT, SWAP_COUNT, HALT_AT,
    // HALT_TARGET y VIDEO_TX.
    parameter [63:0] VIDEO_REGISTERS = 64'h3ff,
    // Bitmap de dispositivos presentes (§5.4). Lo pone el top.
    parameter [31:0] DEVICES = 32'd0,
    parameter [31:0] MEM_BASE = 32'h0000_0000,
    parameter [31:0] MEM_SIZE = 32'h0200_0000,
    parameter [31:0] MONITOR_VERSION = 32'd0
) (
    // Desde mmio_mux.
    input  wire        select,
    input  wire        write,
    input  wire [3:0]  write_mask,
    input  wire [31:0] address,

    // Hacia cada dispositivo: el `select` ya filtrado.
    output wire        video_select,
    input  wire [31:0] video_read_data,
    // Error de DATO del dispositivo: base desalineada, modo reservado. El
    // decodificador solo sabe de direcciones, asi que esto lo pone VIDEO.
    input  wire        video_error,

    output wire        serial_select,
    input  wire [31:0] serial_read_data,

    // Los contadores ya no son de solo lectura: PERF_CTRL y PERF_OVF se
    // escriben, asi que necesitan `select` filtrado.
    output wire        perf_select,
    input  wire [31:0] perf_read_data,

    output reg  [31:0] read_data,
    output reg         error
);
  // El bloque: bits [26:16] de la direccion. Once bits cubren de 0x8000_0000
  // a 0x87FF_0000, de sobra para todo lo que el contrato asigna (§2).
  localparam [10:0] BLK_SYSTEM   = 11'h000;   // 0x8000_0000
  localparam [10:0] BLK_SERIAL   = 11'h010;   // 0x8010_0000
  localparam [10:0] BLK_VIDEO    = 11'h020;   // 0x8020_0000
  localparam [10:0] BLK_CPU_PERF = 11'h101;   // 0x8101_0000

  wire [10:0] block  = address[26:16];
  wire [15:0] offset = address[15:0];
  // Fuera del espacio MMIO, o en la mitad alta que el contrato no asigna.
  wire fuera = !address[31] || |address[30:27];

  wire es_system = !fuera && (block == BLK_SYSTEM);
  wire es_serial = !fuera && (block == BLK_SERIAL) && (HAS_SERIAL != 0);
  wire es_video  = !fuera && (block == BLK_VIDEO);
  wire es_perf   = !fuera && (block == BLK_CPU_PERF);

  // El registro dentro del bloque. Los dispositivos siguen recibiendo solo la
  // parte baja, porque ninguno usa mas de 256 bytes hoy; lo que cambia es que
  // un offset por encima de eso es ERROR y no un alias.
  wire [5:0] palabra = offset[7:2];
  wire offset_alto = |offset[15:8];

  // ---- SYSTEM (§5) ------------------------------------------------------
  //
  // Siete palabras de solo lectura, en `sysid.v`. Sigue siendo un modulo
  // aparte --y no siete constantes aqui-- porque `test_sysid_device.py` y
  // `test_monitor_port.py` lo leen para contrastar el perfil de ISA contra el
  // simulador, y porque no necesita ni reloj ni `select`.
  wire [31:0] system_read_data;
  sysid #(.FOLDER(FOLDER), .ISA_PROFILE(ISA_PROFILE), .DEVICES(DEVICES),
          .MEM_BASE(MEM_BASE), .MEM_SIZE(MEM_SIZE),
          .MONITOR_VERSION(MONITOR_VERSION))
      sysid_i (.word(offset[4:2]), .read_data(system_read_data));

  // El error se calcula en dos piezas. `error_direccion` sale solo de la
  // direccion y es lo que filtra los `select`; el error total incluye ademas
  // el del dispositivo, que depende del DATO y llega despues.
  reg error_direccion;

  // `video_select` NO se filtra con `video_error`: seria un lazo
  // combinacional --VIDEO calcula su error a partir de `select`--. El
  // dispositivo ya ignora por su cuenta una escritura con error, y el error
  // viaja hacia el nucleo por `error`.
  assign video_select  = select && !error_direccion && es_video;
  assign serial_select = select && !error_direccion && es_serial;
  assign perf_select   = select && !error_direccion && es_perf;

  // DEUDA CONOCIDA, y merece leerse entera.
  //
  // §4.1 dice que MMIO admite EXCLUSIVAMENTE palabras de 32 bits, y §16.2
  // que un acceso byte a byte del monitor no debe convertirse en un acceso
  // sub-palabra al periferico. Aqui NO se aplica todavia: una escritura con
  // mascara parcial pasa, como en v1.
  //
  // El riesgo es real y concreto, no teorico. `HALT_AT` rearma la alarma y
  // reinicia el contador de frames CADA VEZ que se escribe, asi que hacerlo
  // en cuatro trozos la rearma cuatro veces con valores intermedios
  // --0x000000NN, 0x0000NNNN...-- y la captura se dispara donde no toca. Es
  // exactamente el ejemplo que pone §16.2.
  //
  // POR QUE NO SE ARREGLA AQUI. Rechazarlo es una linea; lo caro es el otro
  // lado: `monitor.py`, `capture-frames` y varios bancos escriben MMIO byte
  // a byte y todos tienen que pasar a WRITE_WORD a la vez. Es un cambio del
  // protocolo del host, no del mapa, y mezclarlo con la migracion de
  // direcciones haria indistinguibles dos clases de fallo.
  //
  // `write_mask` entra ya al modulo para que el dia que se aplique sea una
  // condicion y no un cambio de interfaz.
  /* verilator lint_off UNUSEDSIGNAL */
  wire escritura_parcial = write && (write_mask != 4'b1111);
  /* verilator lint_on UNUSEDSIGNAL */

  always @* begin
    error_direccion = 1'b0;
    if (fuera) begin
      error_direccion = 1'b1;
    end else if (es_system) begin
      // Solo lectura, y solo las siete palabras. El resto del bloque da
      // error: no devuelve cero ni repite las palabras por alias (§5).
      error_direccion = write || offset_alto || (offset[7:2] > 6'd6)
                        || |offset[1:0];
    end else if (es_serial) begin
      error_direccion = offset_alto || (palabra > 6'd2);
    end else if (es_video) begin
      error_direccion = offset_alto || !VIDEO_REGISTERS[palabra];
    end else if (es_perf) begin
      // Disposicion de §12.6. Aqui SI hay registros por encima de +0xFF: el
      // array llega hasta +0x0FC y el control esta detras, en +0x100.
      //
      //   +0x000..+0x0FC  array: solo las ranuras con contador
      //   +0x100..+0x108  PERF_CTRL, PERF_OVF0, PERF_OVF1
      if (offset < 16'h0100)
        error_direccion = (palabra > 6'd1) || |offset[15:8];
      else
        error_direccion = (offset > 16'h0108) || |offset[1:0]
                          || (offset[15:8] != 8'h01);
    end else begin
      error_direccion = 1'b1;       // bloque sin dispositivo
    end
  end

  // El error que ve el nucleo: el de direccion mas el que pone el
  // dispositivo cuando el VALOR escrito no es valido (§4.3, punto 6).
  always @* begin
    error = error_direccion || (es_video && video_error);
  end

  always @* begin
    if (es_system)      read_data = system_read_data;
    else if (es_serial) read_data = serial_read_data;
    else if (es_video)  read_data = video_read_data;
    else if (es_perf)   read_data = perf_read_data;
    else                read_data = 32'd0;
  end
endmodule

`default_nettype wire
