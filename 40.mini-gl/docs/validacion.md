# Validación realizada

Compilación GCC C89: PASS

`make test`:
- `test_cpu`: PASS: V0 direct == V1 deferred CPU, bytes=312
- `test_gpu`: PASS: V0 direct == V1 deferred CPU == V2 GPU host 8 lanes, 528 command bytes

`make run` (ejemplos, `-v all`): `shapes` y `pattern` dan PASS: V0 == V1 == V2

`make check-minigpu` (V0 compilado con `build-c` y ejecutado en `32.cpu-gpu-func-sim`): `shapes`, `pattern` y
`bounce` dan los 76 800 píxeles idénticos a V0 en el host; `bounce` también en el frame 5. Un frame cuesta 1,5 a
3,8 millones de instrucciones de CPU.

No se ha validado V1/V2 en el simulador MiniGPU ni nada en la FPGA.
