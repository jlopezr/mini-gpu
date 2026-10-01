# `text-scroll-demo`

## Objetivo

Scroll continuo de la consola de texto 80x30 del prototipo 30.

## Comportamiento esperado

- **No hay scroll por hardware**: en cada vuelta la CPU copia las filas 1..29
  sobre las 0..28 (un `LOAD` y un `STORE` por celda) y escribe una fila nueva
  abajo. La pantalla arranca vacía, así que se llena desde abajo y luego sigue
  subiendo.
- El texto es el flujo ASCII imprimible 32..126 repetido, con el color cambiando
  por línea (paleta 1, 2 y 3).
- Activa `CONFIG.TEXT_ENABLE` en el *shadow* y espera al *commit* en la siguiente
  entrada a VBlank antes de empezar a escribir.

## Por qué no hay `test.json`

Corre en un bucle sin fin: no se detiene sola ni pide `SWAP`, así que no hay punto
de parada en el que comprobar nada. Se mira a ojo en la placa.

Contexto: [README de la categoría](../README.md).
Su pareja estática es [`text-console-demo`](../text-console-demo/).
