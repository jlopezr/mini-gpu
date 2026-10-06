# Media palabra en dirección impar

## Objetivo

El byte no tiene alineación que respetar, pero la media palabra sí: una dirección
impar es un acceso inválido, y quien lo comprueba es la unidad de memoria, que
es la única que conoce el tamaño.

## Comportamiento esperado

- `LOADUB` en `0x1001` (impar) es legal.
- `LOADH` en `0x1001` detiene la GPU con `ERROR_MEMORY_ACCESS` (`0x02`), con el
  PC en la instrucción culpable (`8`).

## Qué comprueba el `test.json`

`error_code = 2`, fallo en `pc = 8`, `warp 0`, `lane 0`, dirección `4097`, y que
`R2` no llegó a escribirse.

## Notas

Declara `fault.address`, que el monitor de la placa no expone: el caso se omite
allí. La LSU de la 29 lo cubre en su banco directo (`gpu_lsu2_tb.v`, prueba 15).
