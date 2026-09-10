# Condiciones de error

Cada caso provoca una parada por error y comprueba el código y el PC de la
instrucción causante.

| Caso | Qué valida |
|---|---|
| [invalid-opcode](invalid-opcode/) | Opcode no asignado (código 0x01); se carga como `.hex` porque el ensamblador no lo generaría |
| [invalid-encoding](invalid-encoding/) | Codificación inválida (código 0x05), también cargada como `.hex` |
| [trap](trap/) | `TRAP` explícito (código 0x03) |
