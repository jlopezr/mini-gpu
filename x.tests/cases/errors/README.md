# Condiciones de error

Cada caso provoca una parada por error y comprueba el código y el PC de la
instrucción causante.

| Caso | Qué valida |
|---|---|
| [invalid-opcode](invalid-opcode/) | Opcode no asignado (código 0x01); se carga como `.hex` porque el ensamblador no lo generaría |
| [invalid-encoding](invalid-encoding/) | Codificación inválida (código 0x05), también cargada como `.hex` |
| [trap](trap/) | `TRAP` explícito (código 0x03) |

`invalid-encoding` usa un `NOP` con los 26 bits bajos distintos de cero, y eso
sigue valiendo en todos los backends: la regla de `NOP` no ha cambiado. Lo que
sí cambió con los desplazamientos inmediatos es la regla de `SHL`, `SHR` y
`SAR`, para los que el campo reservado pasó de `extra` entero a `extra[9:0]`
—el bit 10 ya significa algo—. Ese caso, que es el que se habría quedado sin
probar nada si se hubiera escrito con un desplazamiento, está aparte y con su
`requires`, en
[extensions/shift-immediate/reserved-fields](../extensions/shift-immediate/reserved-fields/).
