# `unsigned-branches`

## Objetivo

`BLTU`/`BGEU` comparan **sin signo** y `BLT`/`BGE` con signo. Con
`Ra = 0xFFFFFFFF` y `Rb = 1` las dos familias dan resultados opuestos, así que
cada salto solo se toma si su variante está bien implementada.

## Comportamiento esperado

| Instrucción | ¿Salta? | Efecto |
|---|---|---|
| `BLTU R1, R2` | no (4294967295 < 1 es falso) | `R3 += 1` |
| `BLT R1, R2` | sí (-1 < 1) | se salta `R3 += 10` |
| `BGEU R1, R2` | sí | se salta `R4 += 100` |
| `BGE R1, R2` | no | `R4 += 1` |

## Qué comprueba el `test.json`

- `R3 = 1` y `R4 = 1`: cualquier salto mal resuelto deja `10`, `100` o `101`.
- Parada limpia en `pc = 0x34`.
