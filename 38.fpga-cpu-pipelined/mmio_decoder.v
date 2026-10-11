`default_nettype none

/*
 * Reparte el espacio MMIO entre dispositivos. Contrato: 1.isa/mmio.md v2.
 *
 * Mapa (§2). Los bloques son de 64 KiB y estan alineados a 64 KiB, asi que el
 * bloque se elige con `address[26:16]` y el registro con `address[15:0]`:
 *
 *   0x8000_0000   SYSTEM            identificacion, memoria, version
 *   0x8002_0000   SDRAM PHASE       EXPERIMENTAL, solo carpeta 35
 *   0x8010_0000   SERIAL
 *   0x8020_0000   VIDEO
 *   0x8060_0000   INPUT           teclado y raton (§25)
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
 *
 * ---------------------------------------------------------------------
 * SEGMENTADO EN DOS ETAPAS
 * ---------------------------------------------------------------------
 *
 * Antes todo esto era combinacional entre la direccion que registra
 * `mmio_mux` y el dispositivo: los comparadores de rango del bloque VIDEO,
 * el error, el filtro de `select` y el `write enable` del registro caian en un
 * ciclo, y la lectura --la RAM de la consola, el mux de dispositivos y el byte
 * que elige el monitor-- en otro. Dieron 75 MHz contra 80 en la 30. Ahora:
 *
 *   etapa 1  la decodificacion (bloque, error de direccion, `select`) se
 *            registra; los dispositivos reciben el `select` un ciclo despues
 *   etapa 2  `read_data` y `error` se registran una vez los dispositivos han
 *            escrito, o sea con el mismo estado que veia el cliente cuando esto
 *            era combinacional: un ciclo despues del `select` del dispositivo
 *
 * Esa segunda muestra NO se adelanta al ciclo del `select`, y es a proposito:
 * `SWAP` calcula su error con un latch que solo vale despues de la escritura
 * (`commit_error_latched`), y el puerto serie saca el byte de la cola un ciclo
 * despues del `select`, asi que `read_data` solo es valido hasta entonces.
 *
 * `mmio_mux` espera esos dos ciclos antes del `ack` (parametro EXTRA_CYCLES);
 * los dos tienen que cambiar a la vez. `address`, `write`, `write_mask` y
 * `write_data` llegan retenidos por el mux durante toda la transaccion.
 */
module mmio_decoder #(
    // Identidad de esta carpeta, para el bloque SYSTEM. Va por parametro y no
    // cableada aqui para que el fichero pueda ser copia entre prototipos: lo
    // que cambia de uno a otro vive en su top.v. Un test comprueba que el
    // numero coincide con el del directorio.
    parameter [31:0] FOLDER = 32'd0,
    parameter [31:0] ISA_PROFILE = 32'd0,
    parameter HAS_SERIAL = 1,
    // 1 si hay bloque INPUT (§25) en 0x8060_0000. Con 0 el bloque da error, como
    // cualquier bloque sin dispositivo.
    parameter HAS_INPUT = 0,
    // Cuantas ranuras del array de CPU PERFORMANCE existen de verdad (mmio.md
    // §12.6): las demas dan error, no ceros. Tiene que coincidir con
    // `NUM_COUNTERS` de `cpu_perf_counters`. Por defecto dos --CYCLES y RETIRED--,
    // que es lo que tienen las carpetas anteriores; esta pone ocho.
    parameter integer PERF_SLOTS = 2,
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
    input  wire        clk,

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

    // INPUT. `input_error` es el error de DATO (bits reservados de EVENT_CTRL,
    // mascara parcial), igual que `video_error`: los de direccion los pone este
    // modulo.
    output wire        input_select,
    input  wire [31:0] input_read_data,
    input  wire        input_error,
    // Los contadores ya no son de solo lectura: PERF_CTRL y PERF_OVF se
    // escriben, asi que necesitan `select` filtrado.
    output wire        perf_select,
    input  wire [31:0] perf_read_data,

    // Experimento local de margen SDRAM. No forma parte del contrato global.
    output wire        phase_select,
    input  wire [31:0] phase_read_data,
    input  wire        phase_error,

    output reg  [31:0] read_data,
    output reg         error
);
  // El bloque: bits [26:16] de la direccion. Once bits cubren de 0x8000_0000
  // a 0x87FF_0000, de sobra para todo lo que el contrato asigna (§2).
  localparam [10:0] BLK_SYSTEM   = 11'h000;   // 0x8000_0000
  localparam [10:0] BLK_PHASE    = 11'h002;   // 0x8002_0000, experimental
  localparam [10:0] BLK_SERIAL   = 11'h010;   // 0x8010_0000
  localparam [10:0] BLK_VIDEO    = 11'h020;   // 0x8020_0000
  localparam [10:0] BLK_INPUT    = 11'h060;   // 0x8060_0000
  localparam [10:0] BLK_CPU_PERF = 11'h101;   // 0x8101_0000

  wire [10:0] block  = address[26:16];
  wire [15:0] offset = address[15:0];
  // Fuera del espacio MMIO, o en la mitad alta que el contrato no asigna.
  wire fuera = !address[31] || |address[30:27];

  // Etapa 1: el bloque sale de la direccion retenida y se registra. Todo lo
  // que hay aguas abajo usa `es_*`, ya en registros; solo `error_direccion`, que
  // se calcula aqui mismo, mira las `_d`.
  wire es_system_d = !fuera && (block == BLK_SYSTEM);
  wire es_phase_d  = !fuera && (block == BLK_PHASE);
  wire es_serial_d = !fuera && (block == BLK_SERIAL) && (HAS_SERIAL != 0);
  wire es_video_d  = !fuera && (block == BLK_VIDEO);
  wire es_perf_d   = !fuera && (block == BLK_CPU_PERF);
  wire es_input_d  = !fuera && (block == BLK_INPUT) && (HAS_INPUT != 0);

  reg es_system, es_phase, es_serial, es_video, es_perf, es_input;
  reg select_q;
  reg error_direccion_q;

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
  always @(posedge clk) begin
    es_system <= es_system_d;
    es_phase  <= es_phase_d;
    es_serial <= es_serial_d;
    es_video  <= es_video_d;
    es_perf   <= es_perf_d;
    es_input  <= es_input_d;
    error_direccion_q <= error_direccion;
    select_q <= select;
  end

  assign video_select  = select_q && !error_direccion_q && es_video;
  assign serial_select = select_q && !error_direccion_q && es_serial;
  assign perf_select   = select_q && !error_direccion_q && es_perf;
  assign input_select  = select_q && !error_direccion_q && es_input;
  assign phase_select  = select_q && !error_direccion_q && es_phase;

  // DEUDA CONOCIDA, y merece leerse entera.
  //
  // §4.1 dice que MMIO admite EXCLUSIVAMENTE palabras de 32 bits, y §16.2
  // que un acceso byte a byte del monitor no debe convertirse en un acceso
  // sub-palabra al periferico. Aqui NO se aplica todavia: una escritura con
  // mascara parcial pasa, como en v1.
  //
  // El riesgo es real y concreto, no teorico. `HALT_AT` rearma la alarma y
  // reinicia su cuenta de intercambios CADA VEZ que se escribe, asi que hacerlo
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

  // El error de direccion se calcula EN PARALELO: un `e_*` por dispositivo, sin
  // depender del bloque, y al final se elige con las coincidencias de bloque.
  // Antes era una cadena if/else que ponia los comparadores de rango de VIDEO
  // y de PERF detras de la decodificacion del bloque, en el camino critico de
  // la CPU. Los rangos son ahora decodificaciones de bits.
  wire word_aligned = !(|offset[1:0]);

  // Solo lectura, y solo las siete palabras. El resto del bloque da error: no
  // devuelve cero ni repite las palabras por alias (§5).
  wire e_system = write || offset_alto || (offset[7:2] > 6'd6) || !word_aligned;
  // El dispositivo valida permisos, mascara y valor. Aqui solo existen CTRL
  // (+0) y STATUS (+4), ambos alineados.
  wire e_phase = offset_alto || !word_aligned || (palabra > 6'd1);
  wire e_serial = offset_alto || (palabra > 6'd2);

  // Registros de control bajos y ventanas de consola 2D v0.4.
  // 0x0080..0x0094: offset[15:5] == 4 y, alineado, offset[4:0] <= 0x14, que es
  // !(offset[4] && offset[3]).
  wire v_rango_80 = (offset[15:5] == 11'd4) && !(offset[4] && offset[3]);
  // 0x1000..0x13FC.
  wire v_rango_1000 = (offset[15:10] == 6'b000100);
  // 0x6000..0x857C: 0x6000..0x7FFF mas 0x8000..0x857C (offset[10:8] <= 5 y, en 5,
  // offset[7] = 0).
  wire v_rango_6000 = (offset[15:13] == 3'b011)
      || ((offset[15:11] == 5'b10000)
          && !(offset[10] && offset[9])
          && !(offset[10] && offset[8] && offset[7]));
  wire e_video = !((!offset_alto && VIDEO_REGISTERS[palabra])
      || ((v_rango_80 || v_rango_1000 || v_rango_6000) && word_aligned));

  // §25. Palabras alineadas y nada mas (restriccion de INPUT: solo accesos
  // de 32 bits). Lectura: EVENT_DATA (+0x00), STATUS (+0x04), KEY_STATE0..7
  // (+0x10..+0x2C) y MOUSE_BUTTONS (+0x30). Escritura: SOLO EVENT_CTRL
  // (+0x08); leerlo, escribir un registro de solo lectura, el hueco +0x0C,
  // los huecos hasta +0x10 y todo lo que pase de +0x30 dan error. Una
  // escritura con mascara parcial tambien: no es una palabra.
  wire e_input = offset_alto || !word_aligned
      || (write ? ((palabra != 6'd2) || (write_mask != 4'b1111))
                : !((palabra <= 6'd1) || (palabra >= 6'd4 && palabra <= 6'd12)));

  // Disposicion de §12.6. Aqui SI hay registros por encima de +0xFF: el array
  // llega hasta +0x0FC y el control esta detras, en +0x100.
  //
  //   +0x000..+0x0FC  array: solo las ranuras con contador (PERF_SLOTS)
  //   +0x100..+0x108  PERF_CTRL, PERF_OVF0, PERF_OVF1
  wire e_perf = !offset_alto
      ? (palabra >= PERF_SLOTS[5:0])
      : ((offset > 16'h0108) || !word_aligned || (offset[15:8] != 8'h01));

  wire hay_bloque = es_system_d || es_phase_d || es_serial_d || es_video_d || es_perf_d
                    || es_input_d;

  always @* begin
    error_direccion = fuera || !hay_bloque
        || (es_system_d && e_system)
        || (es_phase_d  && e_phase)
        || (es_serial_d && e_serial)
        || (es_video_d  && e_video)
        || (es_input_d  && e_input)
        || (es_perf_d   && e_perf);
  end

  // El error que ve el nucleo: el de direccion mas el que pone el
  // dispositivo cuando el VALOR escrito no es valido (§4.3, punto 6).
  //
  // Etapa 2: se registran el error y el dato. Se muestrean con los `es_*` ya en
  // registros, un ciclo despues de que el dispositivo recibiera su `select`.
  always @(posedge clk) begin
    error <= error_direccion_q || (es_video && video_error)
             || (es_input && input_error) || (es_phase && phase_error);

    if (es_system)      read_data <= system_read_data;
    else if (es_phase)  read_data <= phase_read_data;
    else if (es_serial) read_data <= serial_read_data;
    else if (es_video)  read_data <= video_read_data;
    else if (es_perf)   read_data <= perf_read_data;
    else if (es_input)  read_data <= input_read_data;
    else                read_data <= 32'd0;
  end
endmodule

`default_nettype wire
