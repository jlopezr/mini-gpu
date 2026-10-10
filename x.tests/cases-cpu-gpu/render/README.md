# render

Un programa gráfico, en tres versiones.

[`render/render.asm`](render/render.asm) es un programa gráfico: un
plasma que pinta la GPU y cuyo bucle de frames lleva la CPU.

```bash
cpugpusim x.tests/cases-cpu-gpu/render/render/render.asm --window
mini-dbg --gpu x.tests/cases-cpu-gpu/render/render/render.asm --window     # depurado
```

`--window` abre la ventana y ya implica el vídeo. Sin ventana, `--video` da los
registros de vídeo (en `mini-dbg`, `fb` abre una ventana con el framebuffer).

La CPU configura el vídeo, y en cada frame escribe los argumentos, lanza 8 warps
con el runtime de `x.tests/inc/gpu_runtime.inc`, espera, pide el `SWAP` y espera a que se
aplique. Cada uno de los 64 hilos pinta una fila de un mosaico de 80 × 60 celdas
de 4 × 4 píxeles, con tres ondas triangulares (una por canal RGB565) calculadas
sin ramas; solo diverge al principio, en los 4 hilos que sobran. Un frame son
unas 27 000 instrucciones de warp. `test_cpu_gpu_sim.py` lo compara píxel a píxel
con un modelo en Python. Con `mini-dbg`, `break gpu_k_render` para en cada warp
(ocho veces por frame): `until present` o `watch` sobre el framebuffer trasero
dan una vista más tranquila.

[`render-cpu/render_cpu.asm`](render-cpu/render_cpu.asm) pinta **la misma
imagen byte a byte** solo con la CPU (el test lo exige), para tener con qué
comparar lo que aporta la GPU: 42 instrucciones por celda, unas 203 000 por
frame, frente a las 27 000 de warp de la versión con GPU.

[`render-v2/render_v2.asm`](render-v2/render_v2.asm) es la misma
imagen con **las escrituras coalescidas**: en vez de un hilo por fila de celdas
(8 lanes escribiendo en 8 filas distintas), un warp pinta una fila entera y sus 8
lanes escriben 8 palabras consecutivas, 32 bytes seguidos. Solo cambia el reparto;
la aritmética es idéntica y los tests exigen la misma imagen.

Medido con el simulador de ciclos (`gpusim-cycle`, carpeta 25) sobre el kernel de
cada versión, un frame:

| | instr. de warp | transacciones LSU | ciclos | a 25 MHz | X ocupada |
|---|---:|---:|---:|---:|---:|
| `render.asm` (v1) | 27 072 | 38 400 | 654 550 | 26,2 ms | 16 % |
| `render_v2.asm` | 46 564 | 9 600 | 209 999 | 8,4 ms | 95 % |

La v1 es de la memoria (cada transacción son ~17 ciclos y no se juntan nunca); la
v2 hace casi el doble de instrucciones pero cuatro veces menos transacciones, y
pasa a ser del cálculo: el 85 % del tiempo de X son los desplazamientos, que son
iterativos (un bit por ciclo, `SAR` por 31 cuesta 31). Son cifras del **modelo**:
en la placa el mismo código tarda más (en `demo-bench` la placa midió 1,55× los
ciclos del modelo), así que 8,4 ms es una cota inferior, no una predicción.

### Medido en la placa (36, hito 1)

En la placa, `run-board` ensambla con `-D BOARD`: `gpu_runtime.inc` lanza con `RUN` porque la 36 aún no tiene
`WARP_START`, y los programas cuentan sus propios ciclos con el `CYCLES` de la CPU (80 MHz). Es el mismo `.asm`
que en el simulador: los de `render` llevan la medición entre `.ifdef BOARD` y `.endif`. Se leen con `monitor.py halt` y `read-register`: `R22` ciclos de
pintado, `R29` ciclos del frame entero, `R19` frames válidos (los que cruzan una
parada del monitor se descartan: sin eso salen cifras que dependen de cuánto se
tarda en leer). Vídeo a 59,5 Hz.

| | pintado | frame entero | fps |
|---|---:|---:|---:|
| `render_cpu.asm` | 54,2 ms | 67,2 ms (4 periodos) | 14,8 |
| `render.asm` (v1) | 27,2 ms | 33,6 ms (2 periodos) | 29,8 |
| `render_v2.asm` | 19,6 ms | 33,6 ms (2 periodos) | 29,8 |

El frame entero es siempre un número entero de periodos de vídeo (16,8 ms) porque
el swap espera al siguiente frame. La v2 pinta en 19,6 ms: 3 ms por encima de un
periodo, y por eso va a 30 fps y no a 60. Frente al modelo, la v1 sale como se
esperaba (27,2 ms medidos contra 26,2) y la v2 no (19,6 contra 8,4): el modelo
subestima el código limitado por cálculo.

| Versión | Carpeta |
|---|---|
| v1: un hilo por fila de celdas | [render](render/render.asm) |
| v2: escrituras coalescidas | [render-v2](render-v2/render_v2.asm) |
| solo CPU, la referencia | [render-cpu](render-cpu/render_cpu.asm) |
