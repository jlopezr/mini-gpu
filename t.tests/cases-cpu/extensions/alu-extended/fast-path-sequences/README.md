# `fast-path-sequences`

## Objetivo

Fijar el resultado correcto de las secuencias en las que el camino rápido de la
21 **no** debe acertar.

## Comportamiento esperado

- La 21 puede saltarse el cálculo de un `MULHI`, `REM` o `REMU` cuando la
  instrucción inmediatamente anterior fue su `MUL`, `DIV` o `DIVU` con los mismos
  **números** de registro. Es una optimización de ciclos: el valor tiene que ser
  el mismo haya acierto o no.
- El riesgo no es que rompa algo con ruido, sino que un acierto indebido
  devuelva un valor plausible y equivocado en ciertas secuencias y solo en ellas.
  Este programa reúne las de **fallo** y fija el resultado de cada una.
- El grueso de la comprobación está en
  `21.fpga-cpu-hdmi-alu/alu_fast_path_tb.v`, que ejecuta dos CPUs a la vez (con y
  sin atajo) y compara los 32 registros.

## Qué comprueba el `test.json`

- Los registros de resultado de cada secuencia y parada limpia en `pc = 0x98`.
- No comprueba ciclos (no puede: el simulador no los tiene). Sí vale contra el
  simulador funcional, que no modela el atajo: si el RTL se colara, el
  diferencial `--backend both` lo vería.
- `requires: ["alu_extended"]`.

Contexto: [README de la categoría](../../README.md).
