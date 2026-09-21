# MiniISA

Especificación y herramientas de la ISA común a MiniCPU y la futura MiniGPU.
La referencia normativa es [`isa.md`](isa.md); [`proyecto.md`](proyecto.md)
describe los objetivos y las decisiones generales.

[`mmio.md`](mmio.md) es la otra referencia normativa: el contrato del espacio de
direcciones y de los periféricos —MMIO v2— para CPU, GPU, el sistema integrado,
los simuladores y el monitor. Dice cómo tiene que quedar todo; lo que implementa
cada prototipo hoy está en
[`../docs/resumen-prototipos.md`](../docs/resumen-prototipos.md), y **ninguno lo
cumple todavía**.

`mini_asm.py` ensambla una palabra little-endian de 32 bits por instrucción:

```powershell
python mini_asm.py minimal.asm -o minimal.bin
python mini_asm.py mandelbrot.asm -o mandelbrot.bin --hex mandelbrot.hex
```

La carpeta contiene además programas pequeños para comprobar el ensamblador y
una primera versión de Mandelbrot escrita en MiniISA. Al cambiar un encoding,
deben actualizarse conjuntamente la especificación, el ensamblador, el
simulador y los tests RTL.
