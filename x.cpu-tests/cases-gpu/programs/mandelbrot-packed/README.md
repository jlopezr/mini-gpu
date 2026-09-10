# gpu-mandelbrot-packed

Mandelbrot 320×240 con framebuffer de **1 byte por píxel**, empaquetando cuatro
píxeles por palabra en software. Es la versión A del plan descrito en
[`12.fpga-gpu/byte-framebuffer.md`](../../../12.fpga-gpu/byte-framebuffer.md).

Diferencias con `cases-gpu/programs/mandelbrot`:

| | `mandelbrot` | `mandelbrot-packed` |
|---|---|---|
| Formato | 1 palabra/píxel | 1 byte/píxel |
| Framebuffer | 300 KiB en `0x00100000` | **75 KiB en `0x00004000`** |
| ¿Cabe en la BRAM de 128 KiB? | No | **Sí** |
| Rango de valores | 1..256 | 1..255 (saturado) |
| Instrucciones de warp | 9.588.644 | 11.275.220 |

El caso original no puede ejecutarse en `12.fpga-gpu`: su framebuffer es 2.3× la
BRAM entera y su base está fuera del espacio de direcciones válido
(`0x00000`–`0x1FFFF`). Este existe para poder correr el mismo kernel en el
simulador funcional y en la FPGA, y comparar.

La semántica SIMT requerida es la de regiones reutilizables del simulador.
El RTL todavía necesita adaptarse a ella para ejecutar este kernel correctamente.

## Detalles del kernel

- **Reparto**: cada lane posee un grupo de 4 píxeles consecutivos y escribe una
  palabra alineada. Como `thread_id = warp*8 + lane`, los 8 lanes de un warp
  tienen grupos consecutivos, sus direcciones dan `addr[4:2] = 0..7` y el LSU los
  sirve en una sola oleada sin conflicto de bancos.
- **19200 grupos / 64 hilos = 300 iteraciones exactas** por lane, sin cola
  divergente.
- **SSY fuera de `mandel_loop`**: una apertura por píxel, dentro de `pack_loop`.
  Todas sus salidas reconvergen en `mandel_done` antes de saturar y empaquetar.
- **Saturación sin ramificar**: `iter - (iter>>8)` convierte 256 en 255 y no toca
  ningún otro valor. Una rama aquí divergiría el warp.
- **Orden de bytes**: el bucle recorre `k` de 3 a 0 con
  `packed = (packed<<8) | iter`, de modo que el píxel `k=0` queda en el byte
  bajo. La palabra que escribe la GPU y la secuencia de bytes de `expected.bin`
  son la misma cosa.

## expected.bin

Generado por `make_expected.py` desde la referencia escalar Q16.16 de
`0.mandelbrot/mandelbrot_fixed.py`, saturando a 255. Son 76800 bytes, con 17206
píxeles saturados — exactamente los que la referencia sin saturar deja en 256.

```
python x.cpu-tests/cases-gpu/programs/mandelbrot-packed/make_expected.py
```

## Alcance de las expectativas

`test.json` comprueba `halted`, `error`, `error_code` y el volcado de memoria, y
deliberadamente **no** fija `instructions_executed`, `warps` ni `fault`. Esos
campos son observaciones que produce el simulador funcional y que un backend de
FPGA no tiene por qué reportar igual; dejarlos fuera mantiene el caso portable
entre backends, que es justamente para lo que existe.
