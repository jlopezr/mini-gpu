# `invalid-opcode`

`program.hex` es una sola palabra, `78000000`: opcode `0x1E`, que no esta
implementado en los backends de este caso. En el mapa compatible propuesto
se reserva para EXT, todavía sin implementar.

**El opcode elegido importa.** Este caso usaba `6C000000`, o sea `0x1B`, que
estaba libre cuando se escribio. Dejo de estarlo al llegar `LOADH`, y desde
entonces el caso no probaba lo que decia: en el simulador y en el bitstream de
[`19.fpga-cpu-hdmi-ls`](../../../../19.fpga-cpu-hdmi-ls/) ejecutaba una carga de
media palabra, no paraba, y agotaba el limite de instrucciones.

Al elegir un opcode para este caso hay que comprobar que sigue sin estar soportado por el backend, consultando el
mapa y el estado de implementación de [`isa.md`](../../../../1.isa/isa.md), que distingue repertorio vigente y propuestas. `0x1E` propone EXT y `0x1F`
permanece libre; si un backend adopta EXT habrá que revisar este caso.
