# MiniISA

Especificación y herramientas de la ISA común a MiniCPU y la futura MiniGPU.
La referencia normativa es [`isa.md`](isa.md); [`proyecto.md`](proyecto.md)
describe los objetivos y las decisiones generales.

`miniisa_asm.py` ensambla una palabra little-endian de 32 bits por instrucción:

```powershell
python miniisa_asm.py minimal.asm -o minimal.bin
python miniisa_asm.py mandelbrot.asm -o mandelbrot.bin --hex mandelbrot.hex
```

La carpeta contiene además programas pequeños para comprobar el ensamblador y
una primera versión de Mandelbrot escrita en MiniISA. Al cambiar un encoding,
deben actualizarse conjuntamente la especificación, el ensamblador, el
simulador y los tests RTL.
