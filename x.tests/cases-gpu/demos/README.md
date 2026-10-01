# Demos de GPU

Las antiguas `examples/` de los prototipos de GPU. Cada programa tiene su carpeta
con `test.json` y `warps.json` (la configuración de warps).

| Caso | Qué es |
|---|---|
| [smoke](smoke/) | Dos instrucciones y **cero** accesos a datos: parte el problema en dos cuando la placa no hace nada |
| [vector](vector/) | El escalón siguiente: cada hilo escribe y relee su palabra |
| [load-store](load-store/) | Bucle de `LOAD`/`STORE` independientes por hilo |
| [mixed-writeback](mixed-writeback/) | Warps que cargan conviviendo con warps que calculan |
| [simt](simt/) / [simt-demo](simt-demo/) | Divergencia y reconvergencia con `SSY`, anidada y simple |
| [bench](bench/) | Núcleo de medida del camino de memoria (22 contra 17) |
| [mmio-selftest](mmio-selftest/) | La GPU alcanza el MMIO por sí misma y se cronometra |
| [plasma](plasma/) / [plasma-nommio](plasma-nommio/) | El efecto plasma a pantalla completa, con y sin MMIO |
| [warp-lane-bands](warp-lane-bands/) | Patrón de diagnóstico: una banda por warp, un escalón por lane |

`smoke` → `vector` → `bench` es el orden de diagnóstico en la placa: si `smoke`
va y `vector` no, el fallo está en la LSU o la SDRAM y no en el fetch; si van los
dos, el camino completo está vivo.

Las variantes para ISAs anteriores llevan `.legacy-<prototipos>.asm` y no se
ejecutan (ver el [README de `x.tests`](../../README.md)).
