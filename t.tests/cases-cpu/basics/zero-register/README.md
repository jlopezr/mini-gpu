# `zero-register`

## Objetivo

`R0` está cableado a cero: las escrituras se descartan y las lecturas dan
siempre cero. No es una extensión sino una regla de la MiniISA, así que el caso
no lleva `requires` y corre en las seis implementaciones.

## Comportamiento esperado

- Ocho escrituras a `R0` por caminos distintos (`MOVI`, `MOVHI`, `GETTID`, la
  ALU con registro e inmediato y los tres desplazadores). Después `R0` sigue
  valiendo cero.
- Una escritura descartada no deja rastro en la instrucción siguiente
  (`ADD R5, R0, R1` da 7, no 106).
- `R0` leído como cero en los dos puertos y en las dos posiciones
  (`SUB R7, R0, R1` da -7), y como operando de `BEQ`/`BNE`.
- Una operación con destino `R0` se retira sin error.

## Qué comprueba el `test.json`

- `R0`, `R3`-`R10` y `R14`, y parada limpia en `pc = 0x68`.
- El repertorio se limita al mínimo común de las seis implementaciones. Quedan
  fuera `MUL`/`DIV`, `LOAD` y el enlace de `JAL`/`JALR`; los cubre
  `zero_register_tb.v` de la 21 y `extensions/calls/jalr-r0-is-jr`.
