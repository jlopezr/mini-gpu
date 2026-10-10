# diverge

Cinco kernels con divergencia: un bucle cuyas lanes salen en vueltas distintas, `if`/`else` por id de hilo, un
`while` con un número de vueltas distinto por lane, una salida anticipada y dos bucles anidados con `break`. Se
comprueban contra un modelo en Python (`CDivergenceTest`).

```text
build-c x.tests/cases-cpu-gpu/simt/diverge/diverge.c
python 32.cpu-gpu-func-sim/cpu_gpu_sim.py _build/c/diverge.bin
```

La divergencia no se escribe: la pone el pase `ssy` de `mini-opt` (ver [programas-en-c.md](../../programas-en-c.md)).
