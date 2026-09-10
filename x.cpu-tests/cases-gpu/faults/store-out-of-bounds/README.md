# STORE fuera del mapa de memoria

## Objetivo

Igual que `load-out-of-bounds` pero con escritura: comprueba que un `STORE`
fuera del mapa produce `ERROR_MEM` (código 2) y **no modifica memoria**.

## Comportamiento esperado

- Misma aritmética de direcciones que el caso de `LOAD`.
- La lane 3 apunta a `0x02000000`, fuera del mapa.
- El warp entero falla en esa instrucción.

## Qué comprueba el `test.json`

- `error_code = 2` y `fault` con `pc = 28`, `core_id = 3` y la dirección.
- El volcado en `0x02000000-12` sigue siendo `sentinel.hex`: ninguna de las
  lanes válidas escribió, es decir el `STORE` es atómico a nivel de warp.
