# `tear-demo-fast`

## Objetivo

La costura limpia, en un solo buffer: lo que se reconoce de un juego sin vsync.

## Comportamiento esperado

- [`tear-demo`](../tear-demo/) tarda 96,6 ms en repintar las 240 líneas, así que
  lo que se ve es un frente de repintado, no una costura. Esta versión pinta solo
  las 32 líneas que cambian, como `swap_demo_fast`, y tarda **13,2 ms** medidos en
  la placa.
- 13,2 ms contra los 16,7 ms de un frame de vídeo: la CPU y el barrido van casi a
  la misma velocidad, pero no exactamente, así que el punto donde se cruzan se
  desplaza poco a poco. En pantalla es una costura horizontal que recorre la
  imagen cada ~63 ms: por encima del corte la banda ya se ha movido, por debajo
  todavía no.
- El ritmo **no** está ajustado a mano: sale de lo que tarda esta CPU en escribir
  5 120 palabras compitiendo con el vídeo por la SDRAM. Es además la única medida
  limpia de ese tiempo: como no espera a nadie, sus 75,7 frames por segundo son
  CPU pura, sin el redondeo a los 60 Hz que impone `swap_demo_fast`.
- Diferencias con `swap_demo_fast`: carga `FB_FRONT`, no pide `SWAP` ni espera,
  usa un solo registro de posición anterior en vez de dos (con un solo buffer, lo
  que hay en pantalla es lo que se dibujó la última vez) y hace un solo borrado
  completo al arrancar.
- [`tear_demo_fast.legacy-16-18-19.asm`](tear_demo_fast.legacy-16-18-19.asm) es la
  variante para las placas viejas y no se ejecuta.

## Por qué no hay `test.json`

Igual que `tear-demo`: nunca pide `SWAP` y depende de una carrera con el barrido
que el simulador no modela. Ver el [README de vídeo](../../video/README.md).

Contexto: [README de la categoría](../README.md).
