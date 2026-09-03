# Simulador funcional de MiniCPU

Implementación Python de MiniISA utilizada como referencia de comportamiento.
Modela PC, 32 registros y memoria unificada byte-addressed, pero no las
latencias internas de la CPU FPGA.

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
