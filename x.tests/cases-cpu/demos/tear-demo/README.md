# `tear-demo`

## Objetivo

`swap_demo` **sin doble buffer**, para ver las costuras. Es el control negativo
del hito D: la misma banda que baja, dibujada directamente sobre el buffer que se
está mostrando.

## Comportamiento esperado

- El hardware de vídeo no espera a nadie: lee las líneas de arriba mientras la
  CPU todavía escribe las de abajo, y en pantalla conviven dos frames a la vez.
- Solo hay dos diferencias con [`swap-demo`](../../video/swap-demo/), y las dos
  van marcadas en el `.asm`: carga `FB_FRONT` (el buffer visible) en vez de
  `FB_BACK`, y no pide `SWAP` ni espera a que ocurra. Lo demás es idéntico a
  propósito: si algo se ve distinto, es por el doble buffer y por nada más.
- Medido en la placa, repintar las 240 líneas tarda **96,6 ms**, casi seis frames
  de vídeo. El barrido da seis vueltas por cada pasada de la CPU, así que no se ve
  una costura sino un frente de repintado bajando despacio: por encima la banda
  nueva, por debajo la vieja. Es tearing llevado al extremo; para el que se parece
  a un juego, [`tear-demo-fast`](../tear-demo-fast/).
- [`tear_demo.legacy-16-18-19.asm`](tear_demo.legacy-16-18-19.asm) es la variante
  para las placas viejas y no se ejecuta.

## Por qué no hay `test.json`

No es un caso y no puede serlo: no pide `SWAP` nunca (es justo lo que demuestra),
así que `run_until.swap` no se dispara, y lo que enseña es una carrera entre la
CPU y el barrido que el simulador no modela. Se queda como demo de mirar a ojo.
Ver el [README de vídeo](../../video/README.md).

Contexto: [README de la categoría](../README.md).
