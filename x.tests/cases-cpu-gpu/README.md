# Programas de CPU + GPU

Programas que usan la CPU y la GPU a la vez, cada uno en su carpeta con su README. Son las antiguas `examples/` del
prototipo [32](../../32.cpu-gpu-func-sim/README.md), que es el simulador que los ejecuta. A diferencia de los casos
de `cases-cpu` y `cases-gpu`, no llevan `expected` ni `test.json`: se comprueban con
[`test_cpu_gpu_sim.py`](../../32.cpu-gpu-func-sim/test_cpu_gpu_sim.py), que compara la imagen o la memoria con un
modelo en Python, y los de la placa se miden con `run-board`.

| Carpeta | Programas |
|---|---|
| [launch](launch/) | CPU y kernel en un solo fichero: lo más pequeño que lanza una GPU |
| [dma](dma/) | Los kernels de sistema (`memset`, `memcpy`, `fill_rect`, `blit`), su arnés y su benchmark |
| [race](race/) | Demos que hacen lo mismo con tres métodos (CPU, GPU inocente, GPU buena): `life`, `blur`, `rotate`, `cube`, `plane` |
| [render](render/) | Un plasma que pinta la GPU, en tres versiones |
| [simt](simt/) | `diverge`: kernels en C cuyas lanes divergen |

Cada programa tiene su carpeta con todo lo suyo: el `.asm` y su `.inc`, el `.c` y su `*_body.h`, los datos y el
informe. Lo que comparten varios programas del mismo tema va en la carpeta del tema (`race/race_host.inc`,
`dma/gpu_kernels.inc`). Lo que comparte todo el repo está en [`x.tests/inc`](../inc/README.md) (`gpu_runtime.inc`,
`bench.inc`, `gpu.h`, `mmio.h`) y [`x.tests/runtime/gpu`](../runtime/gpu/gpu.c).

## Cómo se ejecutan

```bash
sim-sys x.tests/cases-cpu-gpu/launch/launch.asm                        # simulador
mini-dbg --gpu x.tests/cases-cpu-gpu/race/cube/cube.asm --window         # depurado
run-board --prototype 36 --program x.tests/cases-cpu-gpu/race/cube/cube.asm   # placa 36
build-c x.tests/cases-cpu-gpu/dma/memset/memset.c                        # los de C: ver programas-en-c.md
```

`run-board` ensambla con `-D BOARD`, y los `.inc` compartidos eligen la rama de la placa. Es el mismo `.asm` para el
simulador y para la placa. Los programas en C se explican en [programas-en-c.md](programas-en-c.md); lo que
comparan el C y el ensamblador, en [`32.cpu-gpu-func-sim/compare`](../../32.cpu-gpu-func-sim/compare/README.md).

Las pruebas: `python -m unittest test_cpu_gpu_sim` desde `32.cpu-gpu-func-sim` (14 s). Las de los demos de `race`, `dma`
y `render` que simulan varios fotogramas son lentas y se omiten salvo con `RUN_SLOW=1` (unos 110 s en total).
