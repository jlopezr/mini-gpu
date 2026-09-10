# Divergencia y reconvergencia

Casos base: una divergencia parte la máscara, cada camino hace su trabajo y
todas las lanes vuelven a juntarse en el join.

| Caso | Qué valida |
|---|---|
| [convergence](convergence/) | Caso mínimo de `SSY` + rama divergente |
| [ssy-if-else-path](ssy-if-else-path/) | `if/else` con exactamente un `PATH` |
| [ssy-two-paths](ssy-two-paths/) | Dos divergencias en una misma REGION |
| [ssy-nested-path-base](ssy-nested-path-base/) | `path_base` separa las capas anidadas |
| [ssy-fallthrough-is-join](ssy-fallthrough-is-join/) | `PC+4 == join`: se aparca sin reservar `PATH` |
| [branch-target-next-pc](branch-target-next-pc/) | Destino tomado `== PC+4`: no hay divergencia |
| [simt-reached-join](simt-reached-join/) | El join cierra la REGION en cada vuelta |
