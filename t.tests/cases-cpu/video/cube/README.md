# `cube`

## Objetivo

El cubo en alambre de la 21. Es el único caso de vídeo que ejercita **coma
fija**.

## Comportamiento esperado

- `MULFX` en Q16.16 para las dos rotaciones, tabla de senos en `.rodata` y
  perspectiva con `DIV`.
- Cubre **las dos reglas de redondeo de la ISA a la vez**: `MULFX` y `SARI`
  desplazan aritméticamente (hacia menos infinito) y `DIV` trunca hacia cero.
  Aplicar la misma regla a las tres desplaza un píxel las aristas del lado
  negativo y solo esas. El modelo de referencia las escribe por separado.

## Qué comprueba el `test.json`

- Se detiene tras el **swap 24**: con pasos 1 y 3 los ángulos valen ahí 23 y 69,
  ni múltiplos ni simétricos, así que ninguna cara queda de canto y las doce
  aristas tienen longitud distinta de cero.
- El frame capturado contra `expected/frame.bin`, que calcula
  [`reference.py`](reference.py).
- `requires`: `frame_capture`, `subword_memory`, `calls`, `shift_immediate` y
  `mul_div`.

Contexto: [README de la categoría](../README.md).
