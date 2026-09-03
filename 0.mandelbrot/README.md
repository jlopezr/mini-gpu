# Modelos de Mandelbrot

Modelos de referencia usados como workload y golden model del proyecto.

- `mandelbrot_float.py` calcula la referencia en coma flotante.
- `mandelbrot_fixed.py` reproduce la aritmética Q16.16 de MiniISA.
- `compare_iterations.py` compara dos ficheros de iteraciones.
- `view_iterations.py` convierte el resultado de iteraciones en una imagen.

Los cálculos producen ficheros `.iter`: cabecera `ITER`, anchura, altura,
máximo de iteraciones y un `uint16` little-endian por píxel. Este formato
permite comparar el cálculo sin mezclarlo con la paleta de color.

Uso típico desde esta carpeta:

```powershell
python mandelbrot_float.py
python mandelbrot_fixed.py
python compare_iterations.py mandelbrot.iter mandelbrot_fixed.iter
python view_iterations.py
```

Los nombres de entrada y salida predeterminados están definidos al principio
de cada script. Se necesita Pillow para generar imágenes.
