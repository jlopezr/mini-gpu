# `BGEU`: mayor o igual sin signo

## Objetivo

Comprueba la condición de `BGEU` sobre `R1` (lane − 4) y `R0` (= 0). Todos los casos de este subgrupo usan el mismo programa y solo cambia la instrucción de salto: `R1 = (tid & 7) - 4` (de −4 a 3 según la lane), `SSY join`, `OP R1, R0, taken`; el camino sin salto pone `R3 = 3` y el que salta `R3 = 7`.

## Comportamiento esperado

- Saltan las ocho lanes (`R3 = 7`).
- Sin divergencia: todo es mayor o igual que 0 sin signo, así que saltan las ocho lanes (las "negativas" incluidas). Es la diferencia con `BGE`, donde solo saltan las lanes 4..7.

## Qué comprueba el `test.json`

- `R3` de las 8 lanes del warp 0 (es el único sitio donde se ve qué lanes saltaron) y las lanes 0 y 7 de los otros 7 warps, que ejecutan lo mismo.
- `R1` de las lanes 0 y 7, para fijar el operando.
- 7 instrucciones por warp (con divergencia serían 9: se ejecutan las dos ramas).
- Lleva `rtl.differential`: `tools/make_rtl_fixtures.py` lo ejecuta en el simulador funcional y `gpu_system_tb.v` compara con ello el estado completo del RTL.

Contexto: [README de la categoría](../README.md).
