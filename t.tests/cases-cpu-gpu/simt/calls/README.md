# calls

Un kernel escrito con funciones auxiliares: una hoja pequeña, una con seis parámetros (dos por la pila), una con un
bucle que usa registros preservados, una con un array local cuya dirección se toma, llamadas anidadas y una llamada
dentro de un `if` que depende de la lane. La CPU calcula lo mismo llamando a las mismas funciones, y `main` devuelve
cuántos resultados no coinciden (0).

```text
build-c t.tests/cases-cpu-gpu/simt/calls/calls.c
python 32.cpu-gpu-func-sim/cpu_gpu_sim.py _build/c/calls.bin
```

La GPU del simulador y de la 36 no tiene `JAL`: el pase `kernelcalls` de `mini-opt` expande cada llamada del kernel
con el cuerpo entero de la función, marco incluido (ver [programas-en-c.md](../../programas-en-c.md)).
