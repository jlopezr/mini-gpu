# `jalr-r0-is-jr`

## Objetivo

`JALR R0, Ra, 0` es un `JR Ra` completo, y por eso el opcode `0x2E` queda
obsoleto.

## Comportamiento esperado

- Es la razón de peso para cablear `R0` a cero (la otra son los idiomas): la
  familia de control `0x20-0x2F` se había quedado sin opcodes libres, y esto
  devuelve uno.
- `JR` no se ha quitado: sigue implementado y sigue siendo válido. Su hueco es
  *reclamable*, no libre. Quitarlo hoy rompería todo lo que usa `RET`.

## Qué comprueba el `test.json`

Las tres cosas que tienen que pasar a la vez:

1. El salto ocurre (`R2 = 42`, no 99).
2. El enlace se descarta en vez de escribirse: `R0` sigue valiendo cero.
3. `JR` hace exactamente lo mismo.

Parada limpia en `pc = 0x2C`. `requires: ["calls"]`.

Contexto: [README de la categoría](../../README.md).
