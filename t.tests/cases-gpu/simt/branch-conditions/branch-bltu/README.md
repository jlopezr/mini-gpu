# `BLTU`: menor sin signo

## Objetivo

Comprueba la condición de `BLTU` sobre `R1` (lane − 4) y `R0` (= 0). Todos los casos de este subgrupo usan el mismo programa y solo cambia la instrucción de salto: `R1 = (tid & 7) - 4` (de −4 a 3 según la lane), `SSY join`, `OP R1, R0, taken`; el camino sin salto pone `R3 = 3` y el que salta `R3 = 7`.

## Comportamiento esperado

- No salta ninguna lane: todas siguen en el fall-through (`R3 = 3`).
- Sin divergencia: nada es menor que 0 sin signo, así que ninguna lane salta aunque `R1` sea "negativo" para las lanes 0..3. Es justo la diferencia con `BLT`, donde esas cuatro sí saltan.

## Qué comprueba el `test.json`

- `R3` de las 8 lanes del warp 0 (es el único sitio donde se ve qué lanes saltaron) y las lanes 0 y 7 de los otros 7 warps, que ejecutan lo mismo.
- `R1` de las lanes 0 y 7, para fijar el operando.
- 8 instrucciones por warp (con divergencia serían 9: se ejecutan las dos ramas).
- Lleva `rtl.differential`: `tools/make_rtl_fixtures.py` lo ejecuta en el simulador funcional y `gpu_system_tb.v` compara con ello el estado completo del RTL.

Contexto: [README de la categoría](../README.md).
