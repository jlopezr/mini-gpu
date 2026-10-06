# `GETID` con un `type` reservado

## Objetivo

Los `type` 0 a 4 de `GETID` existen y el 5 en adelante está reservado: da
`ERROR_INVALID_ENCODING`, no un valor cualquiera ni un `NOP`.

## Comportamiento esperado

- `GETARG` (`type` 4, el más alto válido) se ejecuta y deja el argumento en `R2`.
- La palabra siguiente, escrita a mano (`0xC0250000`: `GETID` con `type = 5`),
  detiene la GPU con error `0x05` y el PC en esa instrucción.

## Qué comprueba el `test.json`

- `error_code = 5`, fallo en `pc = 8`, sin lane ni dirección (no es un fallo de
  memoria).
- `R2 = 4660`: la instrucción válida anterior sí se retiró.

## Notas

No hay mnemónico para un `type` reservado, a propósito.
