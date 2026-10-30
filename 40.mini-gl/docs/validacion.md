# Validación realizada

Compilación GCC C89: PASS

`make test`:
- `test_cpu`: PASS: V0 direct == V1 deferred CPU, bytes=312
- `test_gpu`: PASS: V0 direct == V1 deferred CPU == V2 GPU host 8 lanes, 528 command bytes

`make run` (ejemplos, `-v all`): `shapes` y `pattern` dan PASS: V0 == V1 == V2

No se ha validado LCC, mini-opt, simulador MiniGPU ni FPGA.
