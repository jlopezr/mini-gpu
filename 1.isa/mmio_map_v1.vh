// -------------------------------------------------------------------------
// MAPA MMIO v1 -- ANDAMIO TEMPORAL, NO ES EL CONTRATO
//
// El contrato es `mmio_map.vh` (v2). Esto es el mapa que el RTL tiene HOY en
// las carpetas todavia sin migrar, escrito CON LOS MISMOS NOMBRES que v2.
//
// PARA QUE SIRVE. Migrar una carpeta son dos cambios que conviene no mezclar:
//
//   1. dar nombre a las direcciones (los `.asm` dejan de llevar 0x8000 a mano);
//   2. cambiar las direcciones (v1 -> v2).
//
// Con este fichero, el paso 1 se hace contra el mapa de hoy y TODO SIGUE
// PASANDO: los programas van por simbolo y apuntan exactamente donde apuntaban.
// El paso 2 es entonces cambiar la linea del `.include` de `mmio_v1.inc` a
// `mmio.inc`, y nada mas. Si algo se rompe despues de eso, es el mapa; si se
// rompio antes, es la simbolizacion. Separarlos es todo el valor de este
// fichero.
//
// Y como los dos ficheros definen LOS MISMOS NOMBRES, incluir los dos a la vez
// es un error de constante duplicada del ensamblador: un programa a medio
// migrar no ensambla, que es justo lo que se quiere.
//
// DE DONDE SALEN LOS NUMEROS. Del RTL de la 19, no de un documento:
//
//   `mmio_decoder.v`  device = address[11:8], sobre MMIO_PREFIX = 20'h80000
//                     DEV_VIDEO=0, DEV_SERIAL=2, DEV_PERF=3, DEV_SYSID=15
//   `video_registers.v`     los `localparam REG_*`, con reg = address[7:2]
//   `serial_port.v`         idem
//   `cpu_perf_counters.v`   idem
//
// CUANDO SE BORRA. Cuando la ultima carpeta este migrada. Si este fichero
// sigue aqui y ningun `.asm` incluye `mmio_v1.inc`, sobra: borralo junto con su
// entrada en `MAPAS` de `tools/generate_mmio.py`.
//
// Ya se borro una vez, al cerrar la migracion de la 21, y hubo que rehacerlo
// para la 19. La leccion esta en `19.fpga-cpu-hdmi-ls/docs/migracion-v2.md`:
// el andamio no sobra mientras quede una carpeta en v1, aunque la carpeta que
// lo estreno ya no lo use.
//
// Las reglas del formato son las de `mmio_map.vh`: solo `define`, nombre y
// constante de 32 bits, sin una sola expresion.
// -------------------------------------------------------------------------

// ==== Memoria principal ==================================================
//
// No cambia entre v1 y v2: la memoria nunca estuvo en el espacio MMIO.

`define MMIO_MEM_BASE              32'h0000_0000
`define MMIO_MEM_SIZE_SDRAM        32'h0200_0000
`define MMIO_MEM_SIZE_EBR          32'h0000_8000

// ==== Bases de dispositivo ===============================================
//
// En v1 no hay "bloques": los dispositivos son ranuras de 256 bytes dentro de
// una unica pagina de 4 KiB en 0x80000000, y quien decide es address[11:8].
// Por eso estas cuatro bases estan pegadas y en v2 estan separadas por
// megabytes. Los nombres son los de v2 a proposito.

`define MMIO_VIDEO_BASE            32'h8000_0000
`define MMIO_SERIAL_BASE           32'h8000_0200
`define MMIO_CPU_PERF_BASE         32'h8000_0300
`define MMIO_SYSTEM_BASE           32'h8000_0F00

// ==== VIDEO (ranura 0) ===================================================
//
// OJO: este es el bloque que MAS se mueve al pasar a v2. En v1 `CTRL` esta al
// final, en +0x18, porque se anadio despues; en v2 esta en +0x00 y empuja a
// todos los demas. O sea que los cuatro registros que usan los programas de la
// 19 --FB_FRONT, FB_BACK, SWAP y CTRL-- cambian los cuatro de offset. Un
// programa migrado a medias no falla al ensamblar: escribe en el registro de
// al lado.

`define MMIO_VIDEO_FB_FRONT_OFF    32'h0000_0000
`define MMIO_VIDEO_FB_BACK_OFF     32'h0000_0004
`define MMIO_VIDEO_SWAP_OFF        32'h0000_0008
`define MMIO_VIDEO_STATUS_OFF      32'h0000_000C
`define MMIO_VIDEO_SWAP_COUNT_OFF  32'h0000_0010
`define MMIO_VIDEO_HALT_AT_OFF     32'h0000_0014
`define MMIO_VIDEO_CTRL_OFF        32'h0000_0018

// Modos de CTRL. No cambian de valor entre v1 y v2; el registro si de sitio.
`define MMIO_VIDEO_MODE_BLANK      32'h0000_0000
`define MMIO_VIDEO_MODE_PATTERN    32'h0000_0001
`define MMIO_VIDEO_MODE_SCANOUT    32'h0000_0002

// En v1 el hardware TRUNCA los bits bajos de FB_FRONT/FB_BACK en vez de dar
// error, y el alineamiento es de 4, no de 16. Se declara para que un programa
// pueda citarlo, pero es de las pocas constantes cuyo VALOR cambia en v2.
`define MMIO_VIDEO_FB_ALIGN        32'h0000_0004

// NO EXISTEN EN v1, y por eso no estan aqui: FRAME_COUNT, HALT_TARGET y TX.
// Un programa que los cite contra este mapa no ensambla, que es la respuesta
// correcta: en este hardware no hay nada detras de esas direcciones.

// ==== SERIAL (ranura 2) ==================================================
//
// Los tres registros coinciden en offset con v2. Lo unico que se mueve es la
// base.

`define MMIO_SERIAL_DATA_OFF       32'h0000_0000
`define MMIO_SERIAL_STATUS_OFF     32'h0000_0004
`define MMIO_SERIAL_PEEK_OFF       32'h0000_0008

// ==== Contadores de rendimiento (ranura 3) ===============================
//
// En v1 solo hay dos, de solo lectura, y no hay registro de control ni
// banderas de desbordamiento: `PERF_CTRL`, `PERF_OVF0` y `PERF_OVF1` son de
// v2. Los dos que hay caen en el mismo offset que en v2.
//
// Como en `mmio_map.vh`, estos `_OFF` no tienen un `_BASE` que sea prefijo de
// su nombre (`MMIO_PERF_` frente a `MMIO_CPU_PERF_BASE`), asi que el generador
// no les inventa una direccion absoluta. Es deliberado: la plantilla vale para
// varios bloques.

`define MMIO_PERF_CYCLES_OFF       32'h0000_0000
`define MMIO_PERF_RETIRED_OFF      32'h0000_0004

// ==== SYSTEM / sysid (ranura 15) =========================================
//
// AQUI NO HAY EQUIVALENCIA DE NOMBRES, y por eso solo se declara la base.
//
// v1 tiene cuatro palabras de solo lectura --SYS_ID, CONTRACT, DEV_BITMAP,
// ISA_PROFILE-- y v2 tiene siete con otro reparto: `SYS_ID` junta el magic y
// el numero de carpeta en una palabra, mientras que v2 los separa en
// `MAGIC` y `SYSTEM_ID`. No son los mismos registros con otro offset, son
// otros registros.
//
// Darles nombres de v2 seria justo el error que este fichero existe para
// evitar: haria que cambiar el `.include` pareciera suficiente cuando no lo
// es. Ningun `.asm` de la 19 lee este bloque --lo lee el host por el camino
// del monitor-- asi que no hace falta, y cuando haga falta se migra a mano y
// mirando.
