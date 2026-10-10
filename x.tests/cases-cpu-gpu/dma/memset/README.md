# memset

El kernel más sencillo en C, sin divergencia (`n` es múltiplo de los hilos): un solo `.c` lleva el código de la
CPU (`main`) y el kernel de la GPU. Ver [programas-en-c.md](../../programas-en-c.md) para cómo se compila.

```text
build-c x.tests/cases-cpu-gpu/dma/memset/memset.c          # -> _build/c/memset.bin
python 32.cpu-gpu-func-sim/cpu_gpu_sim.py _build/c/memset.bin
```

Lo comprueba `CKernelTest` en `32.cpu-gpu-func-sim/test_cpu_gpu_sim.py`.
