# `calls-reserved-fields`

`program.hex` contiene una sola instruccion, `B8210000`: un `JR` con el campo de
destino puesto a `R1`.

`JR` no tiene destino. Sus bits 25:21 son reservados y tienen que valer cero,
igual que los de `NOP` o `GETTID`, asi que esto es un **encoding invalido**
(`0x05`) y no un opcode desconocido (`0x01`). Distinguir las dos cosas es el
motivo de que exista el codigo `0x05`: un opcode que la CPU conoce, usado mal.

Va en hexadecimal y no en ensamblador porque el ensamblador no sabe producirlo:
`JR` solo acepta un operando y siempre pone a cero ese campo. Un caso que
compruebe la validacion de campos reservados tiene que saltarse el ensamblador
por definicion.
