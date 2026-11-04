# string_test

Prueba de la biblioteca C mínima que `build-c` compila con cada programa: las cabeceras están en
[`t.tests/inc`](../../../inc/README.md) (`string.h`) y la implementación en
[`t.tests/runtime/libc`](../../../runtime/libc/string.c). Solo CPU.

```text
build-c t.tests/cases-cpu-gpu/libc/string_test/string_test.c     # -> _build/c/string_test.bin
python 32.cpu-gpu-func-sim/cpu_gpu_sim.py _build/c/string_test.bin
```

`main` devuelve un bit por cada comprobación que falla; `test.json` exige `R1 = 0`.
