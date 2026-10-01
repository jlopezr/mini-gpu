# Condiciones de salto

Las seis instrucciones de salto condicional (`BEQ BNE BLT BGE BLTU BGEU`) bajo un `SSY`. Un mismo
programa para todas: `R1 = (tid & 7) - 4` se compara con `R0` y el camino tomado pone `R3 = 7`
en vez de `R3 = 3`. Qué lanes saltan es lo que distingue cada condición.

| Caso | Salta (lanes) |
|---|---|
| [branch-beq](branch-beq/) | solo la 4 (`R1 == 0`) |
| [branch-bne](branch-bne/) | todas menos la 4 |
| [branch-blt](branch-blt/) | 0..3 (`R1 < 0` con signo) |
| [branch-bge](branch-bge/) | 4..7 |
| [branch-bltu](branch-bltu/) | ninguna: sin signo nada es menor que 0 |
| [branch-bgeu](branch-bgeu/) | todas: sin signo todo es mayor o igual que 0 |
| [branch-unsigned-divergence](branch-unsigned-divergence/) | `BLTU`/`BGEU` contra `R2 = 2`: sí divergen |

`BLTU` y `BGEU` no divergen con este programa (comparan contra `R0 = 0`); lo que prueban es
que la comparación es **sin signo**: un `BLT`/`BGE` en su lugar daría la divergencia de arriba.
La divergencia sin signo entre valores distintos de cero la cubre `branch-unsigned-divergence`.
