# `invalid-opcode`

`program.hex` es una sola palabra, `78000000`: opcode `0x1E`, que no esta
asignado en ninguna version de la ISA.

**El opcode elegido importa.** Este caso usaba `6C000000`, o sea `0x1B`, que
estaba libre cuando se escribio. Dejo de estarlo al llegar `LOADH`, y desde
entonces el caso no probaba lo que decia: en el simulador y en el bitstream de
[`19.fpga-cpu-hdmi-ls`](../../../../19.fpga-cpu-hdmi-ls/) ejecutaba una carga de
media palabra, no paraba, y agotaba el limite de instrucciones.

Al elegir un opcode para este caso hay que comprobar que sigue sin asignar en el
mapa de [`propuesta-v0.2.md`](../../../../1.isa/propuesta-v0.2.md), que es el que
implementan los backends actuales. `0x1E` y `0x1F` son los ultimos huecos del
bloque de memoria.
