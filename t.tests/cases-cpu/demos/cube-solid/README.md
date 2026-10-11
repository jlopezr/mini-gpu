# `cube-solid`

## Objetivo

Un cubo sólido que gira, como prueba de integración de casi toda la CPU:
llamadas, multiplicación, desplazamientos inmediatos, escrituras de 16 bits y
vídeo con doble buffer.

## Comportamiento esperado

- Conserva la transformación Q16.16 y la perspectiva de `cube.asm`.
- Cada una de las seis caras se descarta con el área orientada de su primer
  triángulo. Las visibles se dividen en dos triángulos y se rellenan con tres
  funciones de borde incrementales: solo el primer píxel usa multiplicaciones.
- El cubo es convexo, así que tras descartar las caras traseras las visibles no
  se tapan entre sí y no hace falta z-buffer.

## Qué comprueba el `test.json`

- Se detiene tras el **swap 3**, parada limpia y sin error.
- El frame capturado contra [`expected/frame.bin`](expected/frame.bin).
- `requires`: `calls`, `frame_capture`, `mul_div`, `shift_immediate` y
  `subword_memory`. Límites holgados (3,79 M de instrucciones, 60 s).
