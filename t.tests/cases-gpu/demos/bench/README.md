# `bench`

## Objetivo

Núcleo de medida para comparar 22 (BL8 + búfer + LSU v2) contra 17 (BL1). Mide el
**camino de memoria**, que es lo que cambia entre los dos, no la ALU.

## Comportamiento esperado

- Direcciones `lane*4 + base`: las 8 lanes caen en dos líneas de 16 bytes
  consecutivas, el caso **coalescido**. En la 17 son 8 accesos de lane con dos BL1
  cada uno; en la 22, 2 transacciones BL8.
- Un `LOAD` y un `STORE` por iteración, para mover tráfico de datos de verdad.
- El bucle son 5 instrucciones (20 bytes, 2 líneas de 16): entra de sobra en las 4
  líneas del búfer de instrucciones, así que el fetch acierta casi siempre y no
  domina la medida.
- `R5` es el contador de iteraciones (2000); subirlo alarga la prueba de forma
  lineal.
- Los 32 casos diferenciales no sirven para medir esto: son pruebas de ISA con
  programas cortos y casi nada de tráfico de datos, y su medida la dominaba el
  fetch.

## Qué comprueba el `test.json`

- Parada limpia sin error, hasta 160 144 instrucciones y el número exacto
  ejecutado por warp (`warps.json`).

Contexto: [README de la categoría](../README.md).
