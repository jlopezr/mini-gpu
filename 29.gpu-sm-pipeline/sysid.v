`default_nettype none

/*
 * Bloque SYSTEM de MMIO v2, en 0x80000000. Siete palabras de SOLO LECTURA.
 * Contrato: 1.isa/mmio.md §5.
 *
 *   +0x00  MAGIC             0x4D474155, reconoce MMIO v2 sin ambiguedad
 *   +0x04  MMIO_VERSION      15:8 mayor, 7:0 menor
 *   +0x08  SYSTEM_ID         numero de carpeta del prototipo
 *   +0x0C  DEVICES           bitmap de dispositivos presentes
 *   +0x10  MEM_BASE          base de la memoria principal
 *   +0x14  MEM_SIZE          tamano de la memoria principal
 *   +0x18  MONITOR_VERSION   version del protocolo del monitor
 *
 * QUE CAMBIA RESPECTO DEL BLOQUE ANTERIOR. Eran cuatro palabras en
 * 0x80000F00 --SYS_ID, CONTRACT, DEV_BITMAP, ISA_PROFILE-- y el magic ocupaba
 * los bits 31:16 de SYS_ID. Ahora:
 *
 *   - El magic es una palabra entera y con otro valor, para que un host no
 *     confunda los dos mapas. Buscar 0x4D47 en 31:16 de +0x00 ya no encuentra
 *     nada: eso es deliberado, no compatibilidad rota por descuido (§5.1).
 *   - CONTRACT desaparece; lo sustituye MMIO_VERSION, que versiona ESTE
 *     contrato con mayor y menor separados.
 *   - Aparecen MEM_BASE, MEM_SIZE y MONITOR_VERSION, o sea que un binario
 *     puede preguntar cuanta RAM hay en vez de suponerlo (§5.5).
 *   - ISA_PROFILE deja de vivir aqui: la identidad del nucleo es de CPU CORE
 *     (§13.1) y este bloque describe el SISTEMA. Se conserva el parametro
 *     porque `test_monitor_port.py` y `test_sysid_device.py` lo leen de este
 *     fichero para contrastar el perfil contra el simulador, y mover eso es
 *     trabajo del bloque CPU CORE, que todavia no existe.
 *
 * POR QUE EL NUMERO DE CARPETA como SYSTEM_ID: ya existe, ya es unico y ya lo
 * resuelve `resolve_prototype`. No hay registro central que mantener al
 * anadir un prototipo y es imposible duplicarlo, porque lo impone el nombre
 * del directorio (§5.3).
 *
 * LIMITE CONOCIDO, que sigue en pie: identifica el PROTOTIPO, no el
 * BITSTREAM. Dos sintesis de la misma carpeta con parametros distintos
 * contestan lo mismo.
 */
module sysid #(
    // El numero de la carpeta. Un test comprueba que coincide, asi que no se
    // puede poner mal sin que salte.
    parameter [7:0] FOLDER = 8'd0,

    // Que sabe ejecutar el nucleo. Lo que DISCRIMINA hoy esta en la familia
    // CPU --a la 10 le faltan MUL y DIV, y eso no se detecta de ninguna otra
    // forma en ejecucion--.
    //
    //   bit 0  MUL, MULHI
    //   bit 1  DIV, DIVU, REM, REMU
    //   bit 2  cargas y almacenes de 8 y 16 bits
    //   bit 3  SIMT: SSY, BAR, EXIT y GETTID no constante
    parameter [31:0] ISA_PROFILE = 32'd0,

    // Bitmap de §5.4. Lo pone el top. Un cero con MMIO_VERSION mayor 2
    // significa "sin declarar", que es un valor legitimo y no un error.
    parameter [31:0] DEVICES = 32'd0,

    parameter [31:0] MEM_BASE = 32'h0000_0000,
    parameter [31:0] MEM_SIZE = 32'h0000_0000,
    parameter [31:0] MONITOR_VERSION = 32'd0
) (
    // Palabra dentro del bloque: address[4:2]. Tres bits para siete palabras.
    input wire [2:0] word,
    output reg [31:0] read_data
);

  // El magic de v2, palabra entera. En el mapa unico se llama
  // MMIO_MAGIC_VALUE, y `x.tests/test_mmio_map.py` comprueba que coinciden.
  localparam [31:0] MAGIC = 32'h4D47_4155;

  localparam [7:0] VERSION_MAJOR = 8'd2;
  localparam [7:0] VERSION_MINOR = 8'd0;

  always @* begin
    case (word)
      3'd0: read_data = MAGIC;
      3'd1: read_data = {16'd0, VERSION_MAJOR, VERSION_MINOR};
      3'd2: read_data = {24'd0, FOLDER};
      3'd3: read_data = DEVICES;
      3'd4: read_data = MEM_BASE;
      3'd5: read_data = MEM_SIZE;
      3'd6: read_data = MONITOR_VERSION;
      // La palabra 7 no existe. El decodificador ya la rechaza antes de
      // llegar aqui, asi que este valor no se observa nunca; se deja a cero
      // en vez de a ISA_PROFILE para que un fallo de decodificacion no
      // parezca un registro valido.
      default: read_data = 32'd0;
    endcase
  end

  // ISA_PROFILE no se expone por este bloque en v2 (ver la cabecera). El
  // parametro se conserva porque los tests lo leen de aqui; esta linea existe
  // para que el parametro no quede sin usar y el linter no lo avise.
  /* verilator lint_off UNUSEDPARAM */
  localparam [31:0] ISA_PROFILE_UNUSED = ISA_PROFILE;
  /* verilator lint_on UNUSEDPARAM */
endmodule

`default_nettype wire
