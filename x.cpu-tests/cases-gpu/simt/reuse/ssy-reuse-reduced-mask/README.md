# Reutilización con máscara reducida

## Objetivo

Comprueba que reentrar en el mismo `SSY` con menos lanes activas no sustituye
el `entry_mask` original de la REGION.

## Comportamiento esperado

- Las lanes van abandonando el bucle en vueltas distintas.
- El `SSY` se reejecuta con máscaras cada vez menores.
- Si el `entry_mask` se sobrescribiera con la máscara reducida, al cerrar la
  REGION no se restaurarían todas las lanes.

## Qué comprueba el `test.json`

- `R4` por lane vale `0, 1, 2, 3, 3, 3, 3, 3`: el número de vueltas de cada
  lane, es decir que cada una salió cuando le correspondía.
- Que las ocho lanes tengan un valor coherente demuestra que todas
  reconvergieron con la máscara original.
- `instructions_executed = 22`.

## Notas

Con `--trace-detail` se ve la reducción progresiva de la máscara y la
restauración final.
