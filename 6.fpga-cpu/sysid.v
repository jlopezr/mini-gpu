`default_nettype none

/*
 * Bloque de identificacion, en 0x80000F00. Cuatro palabras de SOLO LECTURA.
 *
 *   +0x00  SYS_ID        magic 4D47 ("MG") + numero de carpeta
 *   +0x04  CONTRACT      version del contrato de mapa de memoria
 *   +0x08  DEV_BITMAP    un bit por dispositivo presente (fase 4b, hoy cero)
 *   +0x0C  ISA_PROFILE   que sabe ejecutar el nucleo
 *
 * POR QUE EXISTE. El host no tenia forma de saber que hardware tiene delante.
 * Se venia usando la version de monitor, y no sirve: 14, 17 y 22 contestaban
 * las tres 2.4 siendo hardware distinto, asi que `board-upload -p 22` con la 17
 * flasheada daba el bitstream por bueno y no subia nada. El sintoma era un
 * kernel fallando con error_code=0x02 al escribir un registro de video que ese
 * prototipo no tiene. Ver docs/resumen-prototipos.md.
 *
 * SYS_ID lleva el NUMERO DE CARPETA porque ya existe, ya es unico y ya lo
 * resuelve `resolve_prototype`: no hay registro central que mantener ni nada
 * que recordar al anadir un prototipo, y no se puede duplicar porque lo impone
 * el nombre del directorio.
 *
 * El magic no es adorno: sin el, el valor 0 seria ambiguo entre "prototipo
 * antiguo, sin bloque" y "prototipo numero 0", y 0.mandelbrot existe.
 *
 * El byte libre se queda SIN USAR a proposito. CPU-vs-GPU ya lo deriva
 * `backend_from_rtl` del RTL, y las capacidades son trabajo de DEV_BITMAP y de
 * ISA_PROFILE. SYS_ID es identidad pura y asi no se solapa con nadie.
 *
 * LIMITE CONOCIDO: identifica el PROTOTIPO, no el BITSTREAM. Dos sintesis de la
 * misma carpeta con parametros distintos contestan lo mismo. Para el caso que
 * duele hoy basta.
 */
module sysid #(
    // El numero de la carpeta. Un test comprueba que coincide, asi que no se
    // puede poner mal sin que salte.
    parameter [7:0] FOLDER = 8'd0,

    // Version del contrato de direcciones de docs/resumen-prototipos.md. Es
    // DISTINTA de la version de monitor a proposito: el mapa cambia por otras
    // razones y a otro ritmo que el juego de comandos, y mezclarlos es como se
    // llego a diez numeros de version para cuatro juegos de comandos.
    parameter [31:0] CONTRACT = 32'd1,

    // Que sabe ejecutar el nucleo. Lo que DISCRIMINA hoy esta en la familia CPU
    // --a la 10 le faltan MUL y DIV, y eso no se detecta de ninguna otra forma
    // en ejecucion-- pero el campo se declara aqui tambien para que el bloque
    // signifique lo mismo en las dos familias.
    //
    //   bit 0  MUL, MULHI
    //   bit 1  DIV, DIVU, REM, REMU
    //   bit 2  cargas y almacenes de 8 y 16 bits
    //   bit 3  SIMT: SSY, BAR, EXIT y GETTID no constante
    parameter [31:0] ISA_PROFILE = 32'd0
) (
    input wire [1:0] word,
    output reg [31:0] read_data
);

  localparam [15:0] MAGIC = 16'h4D47;   // "MG"

  always @* begin
    case (word)
      2'd0: read_data = {MAGIC, 8'd0, FOLDER};
      2'd1: read_data = CONTRACT;
      // DEV_BITMAP es de la fase 4b: se generara desde capabilities.json, no a
      // mano, para no crear una tercera gemela junto a la lista blanca y
      // MONITOR_REGIONS. Hasta entonces lee cero, que con CONTRACT=1 significa
      // "sin declarar" y no "ningun dispositivo".
      2'd2: read_data = 32'd0;
      default: read_data = ISA_PROFILE;
    endcase
  end
endmodule

`default_nettype wire
