# `jump-table`

## Objetivo

Una tabla de saltos con `JALR`, para comprobar la **escala** de su inmediato.

## Comportamiento esperado

- Tres rutinas de dos palabras cada una, a partir de `0x18`. El índice se
  convierte en desplazamiento multiplicándolo por dos: el inmediato de `JALR`
  cuenta **palabras**, como todo el control de flujo de esta ISA. Es justo lo que
  rompe quien viene de RISC-V y lo supone en bytes.
- La base va en un registro, no en el inmediato: es el caso que `BRA` no puede
  cubrir, porque su destino se fija al ensamblar.
- Cada rutina suma una marca distinta (`1`, `0x10`, `0x100`) al acumulador.

## Qué comprueba el `test.json`

- `R6 = 0x111` (las tres rutinas se ejecutaron), `R5 = 0x18` y `R31 = 0x14` (el
  último enlace); parada limpia en `pc = 0x18`.
- `requires: ["calls"]`.

Contexto: [README de la categoría](../../README.md).
