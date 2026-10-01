# `load-store`

## Objetivo

Palabras independientes por hilo, para estresar el solape entre la LSU y el banco
de registros sin carreras de memoria.

## Comportamiento esperado

- Cada hilo calcula su dirección `4096 + tid*4` y hace 32 iteraciones de
  `LOAD`, `+1`, `STORE` sobre su propia palabra.
- Termina con `BAR` y `EXIT`.
- Ningún hilo toca la palabra de otro, así que el resultado no depende del orden
  en que se sirvan las peticiones.

## Qué comprueba el `test.json`

- Parada limpia sin error, hasta 1000 instrucciones, y el número de instrucciones
  y los registros de cada warp (`warps.json`).

Contexto: [README de la categoría](../README.md).
