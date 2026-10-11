# `uppercase`

## Objetivo

Devolver en mayúscula lo que le manden por el puerto serie, y parar cuando
acaba la entrada.

## Comportamiento esperado

- Es `19.fpga-cpu-hdmi-ls/examples/serial_upper.asm` con una diferencia: aquel
  corre para siempre porque es una demo interactiva, y este **para** cuando la
  cola de entrada se vacía. Un caso de test tiene que terminar solo.
- Esa parada lo hace determinista en los dos backends: la entrada entera está en
  la cola **antes** de arrancar (el runner la mete con `SEND_BYTES` en la placa y
  como `stdin` del `SerialDevice` en el simulador), así que "la cola está vacía"
  significa lo mismo en los dos sitios.
- Puerto serie: `+0` DATA, `+4` STATUS (bits 7:0 = bytes esperando). La dirección
  sale del mapa (`mmio.inc`).

## Qué comprueba el `test.json`

- Entrada `"the quick brown fox 123!\n"`, salida `"THE QUICK BROWN FOX 123!\n"`
  (solo cambian las letras `a`-`z`); parada limpia en `pc = 0x40`.
- `requires: ["serial"]`.

Contexto: [README de la categoría](../../README.md).
