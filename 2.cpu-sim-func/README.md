# Simulador funcional de MiniCPU

Implementación Python de MiniISA utilizada como referencia de comportamiento.
Modela PC, 32 registros y memoria unificada byte-addressed, pero no las
latencias internas de la CPU FPGA.

**Va por delante del RTL, a propósito.** Implementa la ISA entera, incluidas
todas las extensiones posteriores a la v0.1:

| Extensión | RTL que la tiene |
|---|---|
| `LOADB`…`STOREH`, accesos de 8 y 16 bits | [`../19.fpga-cpu-hdmi-ls`](../19.fpga-cpu-hdmi-ls) |
| `JAL`, `JALR`, `JR` | 19 |
| Puerto serie en `0x80000200` | 19 |
| `MULHI`, `DIVU`, `REM`, `REMU` | [`../21.fpga-cpu-hdmi-alu`](../21.fpga-cpu-hdmi-alu) |
| `SHLI`, `SHRI`, `SARI` | 21 |
| `R0` cableado a cero | 21 |

Aquí es donde se prueba primero una instrucción nueva; por eso el backend
declara las ocho capacidades y los casos de
[`../x.cpu-tests/cases/extensions`](../x.cpu-tests/cases/extensions) corren aquí
sin placa.

**`R0` está cableado a cero** desde que lo está la 21, y es el único cambio de
esa lista que no es aditivo: un programa escrito para la v0.1 que use `R0` como
registro general se comporta distinto aquí, sin parar con error. Las escrituras
pasan todas por `CPU.set_register`, que es el único sitio del simulador que
escribe el banco, igual que en el RTL la condición vive dentro de
`register_file.v`.

**Lo que NO modela, deliberadamente**, es el camino rápido de `MULHI`/`REM` de
la 21: es invisible para la arquitectura —solo cambia ciclos— y el simulador no
tiene ciclos. Por eso `--backend both` sigue valiendo: `x.cpu-tests` ya excluye
`cycles` de la comparación diferencial.

Ejecutar sus pruebas:

```powershell
python -m unittest test_minicpu_sim.py
```

Consultar las opciones del simulador:

```powershell
python minicpu_sim.py --help
```

`raw_to_iter.py` convierte un framebuffer de palabras de 32 bits en el formato
`.iter` usado por los modelos de Mandelbrot. Para las pruebas compartidas entre
simulador y FPGA se recomienda usar [`../x.cpu-tests`](../x.cpu-tests).
