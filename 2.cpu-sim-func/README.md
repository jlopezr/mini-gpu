# Simulador funcional de MiniCPU

Implementación Python de MiniISA utilizada como referencia de comportamiento.
Modela PC, 32 registros y memoria unificada byte-addressed, pero no las
latencias internas de la CPU FPGA.

**Va por delante del RTL, a propósito.** Implementa la ISA entera, incluidas las
dos extensiones posteriores a la v0.1 que hoy solo tiene el bitstream de
[`../19.fpga-cpu-hdmi-ls`](../19.fpga-cpu-hdmi-ls): los accesos de 8 y 16 bits
(`LOADB`, `LOADUB`, `STOREB`, `LOADH`, `LOADUH`, `STOREH`) y las llamadas
(`JAL`, `JALR`, `JR`). Aquí es donde se prueba primero una instrucción nueva;
por eso el backend declara las capacidades `subword_memory` y `calls`, y los
casos de [`../x.cpu-tests/cases/extensions`](../x.cpu-tests/cases/extensions)
corren aquí sin placa.

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
