// GENERADO por tools/generate-sysid desde el RTL de esta carpeta. No editar.
//
// La identidad de este prototipo, para el bloque SYSTEM de MMIO v2
// (1.isa/mmio.md §5). La LOGICA que sirve estos valores esta en
// `sysid.v`, que es byte a byte identico en las diez carpetas; aqui
// solo estan los numeros, que si son de cada una.
//
// Prototipo: 18.fpga-cpu-hdmi-bl8

// La guarda no es adorno: la 22 tiene DOS sistemas --`gpu_system.v` y
// `gpu_system_bl8.v`-- y los dos se compilan juntos, asi que los dos
// incluyen este fichero. Un `define` de Verilog es global al fichero
// de compilacion, y redefinirlo avisa o falla segun la herramienta.
`ifndef SYSID_PARAMS_VH
`define SYSID_PARAMS_VH

`define SYSID_FOLDER             32'h0000_0012
`define SYSID_ISA_PROFILE        32'h0000_0003
`define SYSID_DEVICES            32'h0000_0227
`define SYSID_MEM_BASE           32'h0000_0000
`define SYSID_MEM_SIZE           32'h0200_0000
`define SYSID_MONITOR_VERSION    32'h0000_0312

`endif
