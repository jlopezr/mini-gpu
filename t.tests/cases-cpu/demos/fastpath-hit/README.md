# `fastpath-hit`

## Objetivo

Medir en la placa lo que ahorra el camino rápido de `DIV`/`REM` de la 21: mitad
**con acierto**. Va en pareja con [`fastpath-miss`](../fastpath-miss/), que es el
mismo fichero con un solo carácter distinto.

## Comportamiento esperado

```text
hit:   DIV R5, R1, R2        miss:  DIV R5, R1, R2
       REM R6, R1, R2               REM R6, R1, R3
```

- `R2` y `R3` valen los dos 3, así que el cociente, el resto y las 4004
  instrucciones ejecutadas son idénticos en las dos versiones.
- Solo cambia el **número** de registro. La etiqueta guarda números, no valores,
  y por eso la versión `miss` falla y rehace la división entera.
- Restar los contadores de ciclos de las dos versiones da directamente el
  ahorro, sin descontar el coste de un `NOP` intercalado.

## Qué comprueba el `test.json`

- Resultado funcional: `R1 = 30000`, `R2 = R3 = 3`, `R5 = 10000`, parada limpia
  en `pc = 36`.
- `requires: ["alu_extended"]`. La medida de ciclos no la hace el caso sino la
  placa.
