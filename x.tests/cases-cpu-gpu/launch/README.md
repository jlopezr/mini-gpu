# launch

Un solo fichero con el código de la CPU y el kernel de la GPU. Se carga entero en la dirección 0, y la CPU
lanza los warps con la etiqueta `kernel` en el descriptor: no hay ninguna dirección escrita a mano. Los
resultados también van en una etiqueta (`out`).

```bash
cpugpusim x.tests/cases-cpu-gpu/launch/launch.asm
mini-dbg --gpu x.tests/cases-cpu-gpu/launch/launch.asm
```

Es el ejemplo más pequeño de CPU + GPU. `x.tests/cases-cpu/gpu/launch-run` es el mismo programa con dos cambios
para correr en la placa, y `36.fpga-cpu-gpu/sim/kernel_square.asm` solo el kernel.
