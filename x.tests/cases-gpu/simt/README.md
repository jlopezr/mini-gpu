# Divergencia y reconvergencia SIMT

Casos que validan la semántica de `SSY`, las pilas REGION y PATH, y la
normalización que reconverge las lanes. Es el grupo más grande porque es la
parte del simulador con más reglas propias.

| Subgrupo | Qué valida |
|---|---|
| [reconvergence](reconvergence/) | Divergir y volver a juntarse en el join |
| [reuse](reuse/) | Reejecutar un `SSY` que ya está en el top |
| [exit](exit/) | Lanes que mueren con estado SIMT abierto |
| [capacity](capacity/) | Límites de las pilas REGION y PATH |
| [barriers](barriers/) | Interacción de `BAR` con la divergencia |
