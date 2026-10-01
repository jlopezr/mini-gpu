# `signed-unsigned`

## Objetivo

`SLT` y `SLTU`: el mismo par de bits da respuestas distintas según se lea con
signo o sin él.

## Comportamiento esperado

- `R2 = 0xFFFFFFFF` es -1 con signo y el mayor valor sin signo; es el operando
  que separa las dos instrucciones.
- Con `R1 = 5`: `5 < -1` con signo da 0 y sin signo da 1; el orden inverso da
  1 y 0.
- Con `R7 = 0` y con operandos iguales, para cubrir los demás bordes.
- El desbordamiento clásico de un `SLT` mal hecho: `INT_MAX - INT_MIN` desborda
  el rango con signo de 32 bits, así que un comparador que solo mirara el bit de
  signo de la resta (en vez de los signos de los operandos por separado) se
  equivocaría. Usa `0x7FFFFFFF` y `0x80000000`.

## Qué comprueba el `test.json`

- Los registros `R1`-`R15` y parada limpia en `pc = 0x48`.
- `requires: ["compare"]`.

Contexto: [README de la categoría](../../README.md).
