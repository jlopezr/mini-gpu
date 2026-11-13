# `invalid-opcode`

`program.hex` es una sola palabra, `D8000000`: opcode `0x36`, reservado en el
mapa vigente y en las propuestas compatibles. Hasta que `EXT` (`0x1E`, con
MIN/MAX/CLZ) llegó a la 38 y a los simuladores, el caso usaba `78000000`.

**El opcode elegido importa.** Este caso usaba `6C000000`, o sea `0x1B`, que
estaba libre cuando se escribio. Dejo de estarlo al llegar `LOADH`, y desde
entonces el caso no probaba lo que decia: en el simulador y en el bitstream de
[`19.fpga-cpu-hdmi-ls`](../../../../19.fpga-cpu-hdmi-ls/) ejecutaba una carga de
media palabra, no paraba, y agotaba el limite de instrucciones.

Al elegir un opcode para este caso hay que comprobar que sigue sin estar soportado por el backend, consultando el
mapa y el estado de implementación de [`isa.md`](../../../../1.isa/isa.md), que distingue repertorio vigente y propuestas.
Libres quedan `0x1F`, `0x36` y `0x37` (`0x1F` es candidato a stores con postincremento).
