# MiniISA

[`isa.md`](isa.md) unifica el repertorio vigente y las extensiones compatibles
propuestas en v0.2, distinguiendo su estado de implementación.

Especificación y herramientas de la ISA común a MiniCPU y MiniGPU.
La referencia normativa es [`isa.md`](isa.md); el [README principal](../README.md)
describe los objetivos y principios generales del proyecto.

Cada especificación incluye su catálogo por opcode, categoría, capability y
soporte funcional, con enlaces internos a los contratos y una tabla separada
de pseudoinstrucciones:

- [ISA vigente y ampliaciones compatibles](isa.md#3-mapa-de-opcodes).
- [Propuesta v0.4](propuesta-v0.4.md#5-mapa-de-opcodes-v04), con mapa incompatible.

[`mmio.md`](mmio.md) es la otra referencia normativa: el contrato del espacio de
direcciones y de los periféricos —MMIO v2— para CPU, GPU, el sistema integrado,
los simuladores y el monitor. Dice cómo tiene que quedar todo; lo que implementa
cada prototipo hoy está en
[`../docs/resumen-prototipos.md`](../docs/resumen-prototipos.md), y **ninguno lo
cumple todavía**.

`asm2/mini-asm.py` es el ensamblador actual y emite una palabra little-endian
de 32 bits por instrucción. `mini_asm.py` queda como entrada de compatibilidad:

```powershell
python mini_asm.py minimal.asm -o minimal.bin
python mini_asm.py mandelbrot.asm -o mandelbrot.bin --hex mandelbrot.hex
```

Sin `-o`, el `.bin` va a `_build/<nombre>.bin` junto al fuente, no al lado del
`.asm`: es salida regenerable y no debe confundirse con un fichero de entrada
(`.incbin`, un `expected.bin`). `_build/` está ignorada por git. `board-load` y
`run-board` ensamblan a la misma carpeta.

La carpeta contiene además programas pequeños para comprobar el ensamblador y
una primera versión de Mandelbrot escrita en MiniISA. Al cambiar un encoding,
deben actualizarse conjuntamente la especificación, el ensamblador, el
simulador y los tests RTL.
