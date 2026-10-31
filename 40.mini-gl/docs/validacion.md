# Validación realizada

Compilación GCC C89: PASS

`make test`:

- `test_cpu`: PASS: V0 direct == V1 deferred CPU, bytes=312; y PASS: doble buffer (mgl_set_target) == un lienzo,
  directo y diferido
- `test_gpu`: PASS: V0 direct == V1 deferred CPU == V2 GPU host 8 lanes, 528 command bytes
- `test_fuzz_v2`: PASS: 3000 escenas, V0 == V2 (escenas al azar con bordes gruesos, círculos, triángulos, líneas,
  puntos, imágenes y recortes por los cuatro lados, en un framebuffer de 101x67: un `pitch` impar)

`make run` (ejemplos, `-v all`): `shapes` y `pattern` dan PASS: V0 == V1 == V2

`make check-minigpu` (compilado con `build-c` y ejecutado en `32.cpu-gpu-func-sim`): los cinco ejemplos dan los
76 800 píxeles idénticos al host con la misma versión, en V0, V1 y V2, en el frame 3; `trail` también en el frame 121
(V0 y V1). La entrada (INPUT) se ha probado con el guion `examples/paint.input`, que da el mismo frame en V0 y en V1.

## Coste

Instrucciones hasta el frame 3 (`make profile-minigpu-<nombre>`), incluido el arranque: borrar la pantalla y, en el
primer frame, copiar el lienzo. En V2, la CPU de la tabla es la que trabaja: sin contar lo que espera a la GPU
(`gpu_run_check` y `gpu_run_poll`). El tiempo supone una instrucción por ciclo, con la CPU a 80 MHz y la GPU a
25 MHz, y en V2 suma las dos, porque la CPU espera mientras la GPU dibuja.

| | V0 (CPU) | V1 (CPU) | V2 (CPU + GPU, instrucciones de warp) |
|---|---|---|---|
| `shapes` | 826 000 (10,3 ms) | 839 000 (10,5 ms) | 211 591 + 504 693 (2,6 + 20,2 = 22,8 ms) |
| `pattern` | 1 369 000 (17,1 ms) | 1 475 000 (18,4 ms) | 366 650 + 1 044 162 (4,6 + 41,8 = 46,4 ms) |

V0 y V1 salen redondeados a miles: el simulador para por lotes. En instrucciones, la GPU de V2 dibuja con menos que
la CPU de V0; en tiempo es más lenta porque va a menos de un tercio de la frecuencia y hoy usa un solo warp.

No se ha validado nada en la FPGA.
