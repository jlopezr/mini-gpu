# Demos de CPU

Las antiguas `examples/` de los prototipos de CPU. Cada programa tiene su carpeta
y lleva `test.json` cuando se puede comprobar de forma barata.

| Caso | Qué es |
|---|---|
| [fpga-smoke-test](fpga-smoke-test/) | Prueba de humo de la placa: `MOVI`/`ADD`/`STORE`/`LOAD` |
| [perf-loop](perf-loop/) | Bucle interior de `swap_demo_fast`, aislado para medir ciclos |
| [fastpath-hit](fastpath-hit/) / [fastpath-miss](fastpath-miss/) | Pareja para medir el camino rápido de `DIV`/`REM` de la 21 |
| [swap-smoke](swap-smoke/) | Doble buffer desde la CPU, sin dibujar nada |
| [fullframe](fullframe/) | «L» y cuadrado a resolución completa, para el banco de RTL |
| [subword-demo](subword-demo/) | Degradado RGB565 píxel a píxel con `STOREH` |
| [cube-solid](cube-solid/) | Cubo sólido con descarte de caras traseras |

Las variantes para ISAs anteriores llevan `.legacy-<prototipos>.asm` y no se
ejecutan: son para las placas viejas (ver el [README de `x.tests`](../../README.md)).
