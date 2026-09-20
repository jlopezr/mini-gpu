`default_nettype none

// Registros de video, accesibles en 0x80000000 por la CPU y por el monitor.
//
//   0x80000000  FB_FRONT   RW  direccion de byte del buffer que se muestra
//   0x80000004  FB_BACK    RW  direccion de byte del buffer que se dibuja
//   0x80000008  SWAP       RW  escribir: pide intercambio en el proximo frame
//                              leer bit 0: intercambio pendiente
//   0x8000000c  STATUS     RW  bit 0    underflow del line buffer (pegajoso)
//                              bit 1    intercambio pendiente
//                              31:16    contador de frames de VIDEO
//                              escribir bit 0 a 1: borra el underflow
//   0x80000010  SWAP_COUNT R   intercambios completados desde que se armo
//                              HALT_AT (o desde el reset, si no se ha armado)
//   0x80000014  HALT_AT    RW  parar la CPU dentro de N intercambios; armarlo
//                              pone SWAP_COUNT a cero (0 = desactivado)
//   0x80000018  VIDEO_CTRL RW  bits 1:0  modo de salida
//                                  0  BLANK    negro, sin leer la memoria
//                                  1  PATTERN  patron de prueba, sin leerla
//                                  2  SCANOUT  framebuffer desde la memoria
//                                  3  reservado (se trata como BLANK)
//
// Con VIDEO_CTRL el bloque es el MISMO que el de la MiniGPU, offset a offset.
// Era la ultima diferencia: HALT_AT no existe alli --lee cero-- pero ocupa su
// hueco, y por eso VIDEO_CTRL fue al final en las dos familias en vez de al
// principio, que es donde lo pondria uno si no tuviera que encajar con nada.
//
// ---------------------------------------------------------------------------
// Para que sirven los tres ultimos, que son de prueba y no de dibujo
// ---------------------------------------------------------------------------
//
// **El borrado del underflow.** Antes el bit solo se iba recargando el
// bitstream, y eso impide tener una suite: el primer caso que falla contamina
// todos los siguientes de la misma sesion. El latch vive en el dominio de
// pixel, asi que el borrado sale de aqui como pulso y cruza como toggle.
//
// **SWAP_COUNT, que no es el contador de frames.** `frame_count` cuenta frames
// de VIDEO y avanza aunque la CPU este parada. Lo que normalmente se quiere
// medir es a que ritmo el programa TERMINA frames, y eso son intercambios. Con
// este registro, los fps de dibujo son (swaps2 - swaps1) / tiempo, sin saber
// nada del programa; hasta ahora habia que leer un registro interno de cada
// demo, con la trampa de los 250 ms del puerto serie encima.
//
// **HALT_AT, y por que se ancla al intercambio y no al contador de frames.**
// Parar la CPU cuando el contador de frames llega a N la para en un punto
// cualquiera de su dibujo: el buffer trasero esta a medias y lo que se capture
// depende de la velocidad relativa entre CPU y barrido, que es justo lo que
// hace que tear_demo_fast tenga una costura viajando. El test saldria distinto
// cada vez.
//
// Parando en el N-esimo intercambio COMPLETADO, en cambio, el frame esta
// entero por construccion y en el buffer frontal. Determinista y repetible, y
// ademas funciona con programas que no colaboren.
//
// Es una alarma de UN disparo y RELATIVA al momento de armarla. Las dos cosas
// las enseno la placa: con `==` contra un contador que solo el reset pone a
// cero, el caso `bounce` pasaba la primera vez y despues no paraba nunca, para
// siempre, porque SWAP_COUNT ya iba por 3 655 y la igualdad no volvia a darse.
// En simulacion no se veia, porque alli cada ejecucion empieza de cero.
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
// otro es que resumen-prototipos.md dice que esas bases "no son reservas
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

    // Error de DATO, no de direccion. El decodificador rechaza offsets que no
    // existen mirando solo la direccion; esto es lo otro que §4.3 llama
    // invalido: "se escribe un valor arquitectonicamente invalido". Una base
    // de framebuffer desalineada y un modo de CTRL reservado son eso.
    //
    // Sale del dispositivo porque es el unico que conoce la semantica de sus
    // registros. El decodificador lo mezcla con el suyo.
    output reg error,

    // Alto mientras el nucleo ejecuta. Solo lo usa VIDEO_TX: §12.3 dice que
    // ese contador no corre libre, porque el scanout sigue leyendo memoria
    // con el nucleo parado y ese trafico no es del programa.
    input wire running,

    // Interfaz con el subsistema de video
    input wire fill_start,
    input wire fill_first,
    output wire [23:0] fb_base,    // direccion de palabra de 16 bits
    input wire underflow_pix,      // nivel pegajoso del dominio de pixel
    output reg underflow_clear,    // pulso hacia el dominio de pixel

    // Pulso que para la CPU al completar el intercambio numero HALT_AT.
    output reg halt_request,

    // Modo de salida (VIDEO_CTRL). Tras el reset vale PATTERN y no SCANOUT, y
    // no es un descuido: la memoria recien encendida contiene basura, asi que
    // arrancar en SCANOUT seria elegir un valor por defecto cuya salida es
    // indefinida --y entonces ver basura no dice si falla HDMI, el PLL, el
    // cable, `fb_base` o el programa--. Con PATTERN, ver el patron demuestra
    // que la cadena hasta el monitor funciona y no verlo senala aguas arriba.
    // El razonamiento entero esta en 22.fpga-gpu-bl8/video-scanout.md.
    output reg [1:0] video_mode,

    output wire [31:0] debug_front,
    output wire [31:0] debug_back
);

  // Disposicion de MMIO v2 (1.isa/mmio.md §9). CTRL vuelve a +0x00, que es lo
  // natural para un registro de control; estaba al final porque en su dia se
  // anadio sin querer desplazar los que la CPU ya tenia, y v2 renumera de una
  // vez para no arrastrar esa decision para siempre.
  localparam [5:0] REG_CTRL        = 6'd0;   // +0x00
  localparam [5:0] REG_FB_FRONT    = 6'd1;   // +0x04
  localparam [5:0] REG_FB_BACK     = 6'd2;   // +0x08
  localparam [5:0] REG_SWAP        = 6'd3;   // +0x0C
  localparam [5:0] REG_STATUS      = 6'd4;   // +0x10
  localparam [5:0] REG_FRAME_COUNT = 6'd5;   // +0x14
  localparam [5:0] REG_SWAP_COUNT  = 6'd6;   // +0x18
  localparam [5:0] REG_HALT_AT     = 6'd7;   // +0x1C
  localparam [5:0] REG_HALT_TARGET = 6'd8;   // +0x20
  localparam [5:0] REG_VIDEO_TX    = 6'd9;   // +0x24

  // Bits de HALT_TARGET (§9.6). Existe porque quien produce los frames y
  // quien se para no tienen por que ser el mismo: en un sistema donde dibuja
  // la GPU y la CPU orquesta, parar una, otra o las dos son tres casos.
  localparam integer HALT_TARGET_CPU = 0;
  localparam integer HALT_TARGET_GPU = 1;

  // Alineamiento exigido a FB_FRONT y FB_BACK (§9.2). Dieciseis bytes, porque
  // el scanout lee en rafagas. Antes se TRUNCABA a cuatro; ahora desalinear
  // es error, y el motivo es concreto: el truncamiento era distinto en cada
  // familia --4 bytes en CPU y 16 en GPU-- asi que el mismo programa dibujaba
  // bien en una placa y torcido en la otra sin que nada avisara.
  localparam integer FB_ALIGN_BITS = 4;

  // Modos de salida. Los mismos numeros que gpu_video_regs.v.
  localparam [1:0] MODE_BLANK   = 2'd0;   // negro, sin leer la memoria
  localparam [1:0] MODE_PATTERN = 2'd1;   // patron de prueba, sin leer memoria
  localparam [1:0] MODE_SCANOUT = 2'd2;   // framebuffer desde memoria
                                          // 3 reservado, se trata como BLANK

  reg [31:0] fb_front;
  reg [31:0] fb_back;
  reg swap_pending;
  // FRAME_COUNT es un registro PROPIO de 32 bits (§9.4 y §9.5). Vivia en los
  // bits altos de STATUS, con dieciseis bits: los contadores no se mezclan
  // con el estado.
  reg [31:0] frame_count;
  reg [31:0] swap_count;
  reg [31:0] halt_at;
  reg [31:0] halt_target;
  reg        halt_armed;
  reg [31:0] video_tx;

  // El underflow nace en el dominio de pixel. Es un nivel pegajoso, asi que
  // basta con sincronizarlo; no hay pulso que perder.
  reg underflow_sync_0, underflow_sync_1;
  always @(posedge clk) begin
    underflow_sync_0 <= underflow_pix;
    underflow_sync_1 <= underflow_sync_0;
  end

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
  // la mezcla se materializa en una senal antes de comprobar el alineamiento.
  wire [31:0] merged_front = merge(fb_front, write_data, write_mask);
  wire [31:0] merged_back = merge(fb_back, write_data, write_mask);

  // --- Validacion del DATO (§9.1 y §9.2) ---------------------------------
  //
  // Se comprueba sobre el valor YA MEZCLADO, no sobre `write_data`: el
  // monitor puede escribir un registro byte a byte, y juzgar un byte suelto
  // rechazaria una escritura parcial perfectamente valida.
  // Solo se juzga la escritura de PALABRA COMPLETA. Con mascara parcial el
  // valor mezclado pasa por estados intermedios que no cumplen el
  // alineamiento --escribir 0x01000000 byte a byte empieza por 0x00000000 y
  // sigue por 0x00000000, 0x00000000, 0x01000000-- y rechazarlos haria
  // imposible escribir el registro desde el camino de byte del monitor.
  //
  // La solucion de verdad es que MMIO no acepte escrituras sub-palabra
  // (§4.1 y §16.2); esta condicion desaparece el dia que se aplique. Ver la
  // deuda anotada en `mmio_decoder.v`.
  wire palabra_completa = (write_mask == 4'b1111);
  wire front_desalineada = palabra_completa && |merged_front[FB_ALIGN_BITS-1:0];
  wire back_desalineada  = palabra_completa && |merged_back[FB_ALIGN_BITS-1:0];
  // El modo 3 esta reservado; escribirlo es error, no se trata como BLANK.
  wire modo_reservado = (write_data[1:0] == 2'd3);

  always @* begin
    error = 1'b0;
    if (bus_write) begin
      case (selected)
        REG_FB_FRONT: error = front_desalineada;
        REG_FB_BACK:  error = back_desalineada;
        REG_CTRL:     error = write_mask[0] && modo_reservado;
        // Los contadores y VIDEO_TX son de solo lectura. No se filtran aqui
        // --eso lo hace el decodificador por offset-- salvo que algun dia
        // dejen de serlo.
        default: ;
      endcase
    end
  end

  always @(posedge clk) begin
    underflow_clear <= 1'b0;
    halt_request <= 1'b0;

    if (reset) begin
      // Estado tras reset, §9.8. El sistema NO arranca en SCANOUT: la SDRAM
      // recien encendida contiene basura.
      fb_front <= FB_FRONT_RESET;
      fb_back <= FB_BACK_RESET;
      swap_pending <= 1'b0;
      frame_count <= 32'd0;
      swap_count <= 32'd0;
      halt_at <= 32'd0;
      halt_target <= 32'd0;
      video_tx <= 32'd0;
      video_mode <= MODE_PATTERN;
      halt_armed <= 1'b0;
    end else begin
      // El intercambio va primero para que una escritura del bus en el mismo
      // ciclo gane: si el software fija una base justo ahora, esa es la que
      // quiere, no la que acaba de rotar.
      if (swap_now) begin
        fb_front <= fb_back;
        fb_back <= fb_front;
        swap_pending <= 1'b0;
        swap_count <= swap_count + 1'b1;
      end

      // FRAME_COUNT y la alarma. En v1 `HALT_AT` contaba contra SWAP_COUNT;
      // §9.6 lo cambia a FRAME_COUNT, y el motivo esta escrito en el
      // contrato: "un programa que se cuelga sin pedir swaps tambien tiene
      // que poder capturarse". Con la cuenta de swaps, un programa colgado no
      // dispara la alarma nunca y el host se queda esperando.
      //
      // El bit de armado se consume al disparar: es una alarma de un disparo,
      // no una coincidencia permanente. Y armar reinicia la cuenta, que es lo
      // que arreglo el fallo de la placa -- sin eso la alarma solo sirve una
      // vez por arranque, porque la segunda el contador ya paso de largo.
      //
      // La comparacion es `>=` y no `==`, defensa barata por si el contador
      // se pasara de largo (§9.6).
      if (fill_start && fill_first) begin
        frame_count <= frame_count + 1'b1;
        if (halt_armed && (frame_count + 1'b1) >= halt_at) begin
          // A quien se para lo dice HALT_TARGET (§9.6). Esta carpeta solo
          // tiene CPU, asi que el bit de GPU se acepta y no hace nada: el
          // registro significa lo mismo en las dos familias y un binario
          // compartido no tiene que saber donde corre.
          halt_request <= halt_target[HALT_TARGET_CPU];
          halt_armed <= 1'b0;
        end
      end

      // VIDEO_TX: transacciones de memoria del scanout (§9.7). Cuenta los
      // arranques de relleno de linea, que es lo que el scanout pide a la
      // memoria. Pertenece a VIDEO y no al bloque de contadores de la CPU
      // porque cada contador es de quien GENERA el evento (§12.1).
      //
      // Solo avanza con el nucleo corriendo (§12.3): con la CPU parada el
      // scanout sigue leyendo, y ese trafico no es del programa. Da la vuelta
      // y no satura (§12.2), que es lo que hace que la resta siga valiendo.
      if (running && fill_start) video_tx <= video_tx + 1'b1;

      // `!error`: una escritura invalida no tiene efecto. §4.3 dice que los
      // accesos invalidos no ignoran la escritura EN SILENCIO --generan
      // error-- pero tampoco la aplican a medias.
      if (bus_write && !error) begin
        case (selected)
          // Ya no se trunca: si llega aqui, esta alineada. El truncamiento
          // silencioso es lo que §9.2 prohibe.
          REG_FB_FRONT: fb_front <= merged_front;
          REG_FB_BACK:  fb_back  <= merged_back;
          // Cualquier escritura pide intercambio. Si cae en el mismo ciclo que
          // uno en curso, queda pendiente para el frame siguiente y no se
          // pierde, que es lo que pasaria si el `swap_now` de arriba ganara.
          REG_SWAP:     swap_pending <= 1'b1;
          // Escribir un uno en el bit 0 borra el underflow. El resto de STATUS
          // sigue siendo de solo lectura: son cuentas, no estado que nadie
          // deba poder falsear.
          REG_STATUS:   if (write_mask[0] && write_data[0])
                          underflow_clear <= 1'b1;
          // Armar la alarma pone el origen de la cuenta AQUI. `HALT_AT` es
          // "para dentro de N intercambios", no "para en el intercambio
          // numero N desde el encendido": sin esto, un programa solo puede
          // usarla una vez por arranque de la placa, porque la segunda vez el
          // contador ya ha pasado de largo. El simulador construye el
          // dispositivo de cero en cada ejecucion, asi que alli no se nota.
          // Armar pone el origen de la cuenta AQUI: `HALT_AT` es "para dentro
          // de N frames", no "para en el frame numero N desde el encendido".
          // Sin esto un programa solo puede usarla una vez por arranque de la
          // placa. El simulador construye el dispositivo de cero en cada
          // ejecucion, asi que alli no se nota -- es un fallo que solo da la
          // placa, y ya lo dio una vez.
          REG_HALT_AT:  begin
            halt_at <= merge(halt_at, write_data, write_mask);
            frame_count <= 32'd0;
            halt_armed <= merge(halt_at, write_data, write_mask) != 32'd0;
          end
          REG_HALT_TARGET: halt_target <= merge(halt_target, write_data,
                                                write_mask);
          REG_CTRL:     if (write_mask[0]) video_mode <= write_data[1:0];
          // FRAME_COUNT, SWAP_COUNT y VIDEO_TX son de solo lectura.
          default: ;
        endcase
      end
    end
  end

  always @(*) begin
    case (selected)
      REG_CTRL:        read_data = {30'd0, video_mode};
      REG_FB_FRONT:    read_data = fb_front;
      REG_FB_BACK:     read_data = fb_back;
      REG_SWAP:        read_data = {31'd0, swap_pending};
      // STATUS ya NO lleva el contador de frames en los bits altos (§9.4):
      // bit 0 UNDERFLOW pegajoso W1C, bit 1 SWAP_PENDING, resto reservado.
      REG_STATUS:      read_data = {30'd0, swap_pending, underflow_sync_1};
      REG_FRAME_COUNT: read_data = frame_count;
      REG_SWAP_COUNT:  read_data = swap_count;
      REG_HALT_AT:     read_data = halt_at;
      REG_HALT_TARGET: read_data = halt_target;
      REG_VIDEO_TX:    read_data = video_tx;
      default:         read_data = 32'd0;
    endcase
  end
endmodule

`default_nettype wire
