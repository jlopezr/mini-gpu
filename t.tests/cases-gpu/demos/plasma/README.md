# `plasma`

## Objetivo

El efecto plasma a pantalla completa con los 64 hilos colaborando, como prueba de
extremo a extremo de la GPU: cómputo, memoria coalescida, MMIO y doble buffer.

## Comportamiento esperado

- **Se configura sola**: el prólogo fija los dos buffers y enciende el scanout.
  El host solo carga y arranca (`run-board --program` basta). Antes se leía un
  `FB_BACK` a cero tras el reset y los 64 hilos pintaban encima del propio
  programa.
- **Doble buffer**: dibuja en `FB_BACK` y pide el intercambio al terminar cada
  frame. Sin él, el scanout lee a 60 Hz la misma memoria que los hilos reescriben
  a ~8 fps y la imagen tiembla.
- 320x240 RGB565 son 38 400 palabras, 600 por hilo. El hilo `t` coge las palabras
  `t`, `t+64`, `t+128`...: el paso de 64 hace que los 8 hilos de un warp escriban
  palabras consecutivas, que la LSU v2 coalesce en 2 transacciones de 16 bytes.
- La GPU hace el intercambio escribiendo el MMIO, posible desde que la ventana
  está abierta a la LSU.

## Variantes de esta carpeta

| Fichero | Para qué |
|---|---|
| `plasma.asm` | El programa de este caso |
| [`plasma_1frame.asm`](plasma_1frame.asm) | Perfilado: dibuja **un** frame, para medir el coste de dibujar y no una media de varios más la espera de swaps |
| [`plasma_small.asm`](plasma_small.asm) | Solo la banda de arriba (320x24): una décima parte del trabajo, para una prueba de extremo a extremo barata (`gpu_plasma_tb` tarda 463 s). Si se toca `plasma.asm`, hay que tocar esta |
| [`plasma_static.asm`](plasma_static.asm) | Diagnóstico: dibuja siempre la misma imagen, para distinguir el *tearing* de otros problemas de vídeo |
| [`plasma_nommio.asm`](plasma_nommio.asm) | Sin MMIO, para [`plasma-nommio`](../plasma-nommio/) |

## Qué comprueba el `test.json`

- Se detiene tras el **swap 2**, parada limpia sin error, hasta 608 000
  instrucciones y 60 s.
- Los registros de cada warp (`warps.json`) y el frame capturado contra
  [`expected/frame.bin`](expected/frame.bin).
- `requires: ["frame_capture", "mul_div"]`.

Contexto: [README de la categoría](../README.md).
