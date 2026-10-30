# Validación realizada

Compilación GCC C89: PASS

`make test`:
- `test_cpu`: PASS: V0 direct == V1 deferred CPU, bytes=312
- `test_gpu`: PASS: V0 direct == V1 deferred CPU == V2 GPU host 8 lanes, 528 command bytes

`make run` (ejemplos, `-v all`): `shapes` y `pattern` dan PASS: V0 == V1 == V2

`make check-minigpu` (compilado con `build-c` y ejecutado en `32.cpu-gpu-func-sim`): los cinco ejemplos dan los
76 800 píxeles idénticos al host con la misma versión, en V0 y en V1 (`V=1`), en el frame 3; `trail` también en el
frame 121. Con 3 frames, `shapes` cuesta 0,97 M de instrucciones de CPU en V0 y 0,99 M en V1, y `pattern`, 1,58 M
y 1,68 M (`make profile-minigpu-<nombre>`). La entrada (INPUT) se ha probado con el guion `examples/paint.input`,
que da el mismo frame en V0 y en V1.

No se ha validado V2 en el simulador MiniGPU ni nada en la FPGA.
