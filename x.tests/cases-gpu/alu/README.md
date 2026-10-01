# ALU

Casos de aritmética y del banco de registros que no dependen del reparto de hilos.

| Caso | Qué valida |
|---|---|
| [random-arithmetic](random-arithmetic/) | 33 operaciones con operandos aleatorios de semilla fija y casos límite de `DIV`/`MULFX` |
| [r0-hardwired-zero](r0-hardwired-zero/) | `R0` vale siempre 0: las escrituras se descartan |
| [r0-load-still-faults](r0-load-still-faults/) | `LOAD R0` sigue haciendo el acceso y puede fallar |
