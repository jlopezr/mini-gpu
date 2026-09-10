# Suma de vectores con máscara parcial

## Objetivo

Variante de `vecsum` en la que el segundo warp arranca con `active_mask = 0x0F`.
Comprueba que las lanes inactivas ni calculan ni escriben.

## Comportamiento esperado

- El warp 0 procesa los índices 0..7 con las ocho lanes.
- El warp 1 arranca con solo cuatro lanes activas y procesa 8..11.
- Los índices 12..15 no los toca nadie.

## Qué comprueba el `test.json`

- `R8 = 111` en la lane 3 del warp 1 (activa) y `R8 = 0` en las lanes 4 y 7
  (inactivas): la máscara se respeta en el cálculo.
- El volcado de `C` (`expected.hex`) conserva el valor centinela en 12..15:
  la máscara también se respeta en la escritura a memoria.
- El warp 2, no configurado, no ejecuta nada.
