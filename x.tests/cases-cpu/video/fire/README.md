# `fire`

## Objetivo

La referencia secuencial del efecto de fuego, en MiniISA.

## Comportamiento esperado

- Un mapa de calor de 64x120 que se propaga hacia arriba con un decaimiento de 2.
  La fila inferior se siembra con ruido (`xorshift32`, semilla `0x2545F491`) y solo
  se conservan los valores mayores de 80.
- Cada celda ocupa 5x2 píxeles (64 x 5 = 320, 120 x 2 = 240) y se convierte a
  RGB565 con una paleta por tramos: `0..63` negro → rojo, `64..191` rojo →
  amarillo, `192..255` amarillo → blanco.
- Doble buffer: `FB0 = 0x01000000` y `FB1 = 0x01040000`, con pila propia.

## Ficheros

- [`fire.asm`](fire.asm): el programa.
- [`fire.py`](fire.py): el mismo algoritmo en Python, que sirve de **modelo
  independiente**.

## Por qué no hay `test.json`

La comprobación vive en [`x.tests/test_fire_reference.py`](../../../test_fire_reference.py),
una regresión cruzada: el modelo Python contra la MiniISA ejecutada en el
simulador (la paleta en sus fronteras y el frame 3). No corre contra la placa.

Contexto: [README de la categoría](../README.md).
