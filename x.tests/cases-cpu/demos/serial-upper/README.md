# `serial-upper`

## Objetivo

El programa interactivo más pequeño que hace algo visible: lee un byte del puerto
serie, si es una minúscula la convierte y lo devuelve. Escribes `hola` en la
consola y sale `HOLA`.

## Comportamiento esperado

- Corre **para siempre**; se para con `monitor.py halt`. Por eso no es un caso
  con `test.json`.
- El bucle de espera es lo único delicado: **no se puede leer `DATA` sin mirar
  antes `STATUS`**. Una lectura de `DATA` con la cola vacía devuelve cero (no
  bloquea: el bus MMIO se resuelve en un ciclo) y el programa se pondría a mandar
  ceros a toda velocidad. El bucle mira `rx_count` en los ocho bits bajos de
  `STATUS` y solo lee cuando hay algo.
- No mira `tx_free` antes de escribir, y eso sí es una simplificación: manda como
  mucho un byte por cada uno que recibe. Un programa que escupa texto por su
  cuenta tendría que mirar `tx_free`, o perdería bytes en silencio.
- Puerto serie en `0x80000200`: `+0` DATA, `+4` STATUS, `+8` PEEK.
- [`serial_upper.legacy-19.asm`](serial_upper.legacy-19.asm) es la variante para
  la 19 y no se ejecuta.

## Cómo probarlo

```powershell
.\run-demo.ps1 serial_upper
..\.venv\Scripts\python.exe monitor.py console --port COM3
# o, sin terminal:
..\.venv\Scripts\python.exe monitor.py send "hola" --port COM3
```

La versión que **sí** es un caso, porque termina cuando se vacía la entrada, es
[`extensions/serial/uppercase`](../../extensions/serial/uppercase/).

Contexto: [README de la categoría](../README.md).
