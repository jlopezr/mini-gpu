# Modelos de Mandelbrot

Modelos de referencia usados como workload y golden model del proyecto.

- `mandelbrot_float.py` calcula la referencia en coma flotante.
- `mandelbrot_fixed.py` reproduce la aritmética Q16.16 de MiniISA.
- `compare_iterations.py` compara dos ficheros de iteraciones.
- `view_iterations.py` convierte el resultado de iteraciones en una imagen.

Los cálculos producen ficheros `.iter`: cabecera `ITER`, anchura, altura,
máximo de iteraciones y un `uint16` little-endian por píxel. Este formato
permite comparar el cálculo sin mezclarlo con la paleta de color.

## Flujo de validación

```text
Mandelbrot float   -> referencia matemática y visual
Mandelbrot Q16.16  -> resultado exacto esperado para esa aritmética
                              |
                 MiniISA -> MiniCPU -> MiniGPU -> RTL / FPGA
                              |
                           .iter -> visor -> PNG
```

La referencia float permite juzgar la imagen ideal. El modelo Q16.16 define el
resultado que deben reproducir los programas que usan ese mismo contrato de
aritmética. Una diferencia respecto a float puede ser cuantización legítima;
una diferencia respecto al modelo Q16.16, con iguales parámetros de entrada,
indica un error. Se comparan iteraciones antes de aplicar la paleta para separar
cálculo y presentación. Otros formatos numéricos requieren su propia referencia.

## Formato `.iter`

Todos los campos numéricos son little-endian. La cabecera ocupa 16 bytes:

| Offset | Tamaño | Campo |
|---:|---:|---|
| 0 | 4 bytes | magic ASCII `ITER` |
| 4 | 4 bytes | anchura, `uint32` |
| 8 | 4 bytes | altura, `uint32` |
| 12 | 4 bytes | máximo de iteraciones, `uint32` |
| 16 | anchura × altura × 2 bytes | iteraciones, un `uint16` por píxel |

Los píxeles se guardan por filas, de izquierda a derecha y de arriba abajo.
El flujo inicial de MiniCPU usa un framebuffer de palabras de 32 bits por píxel
en `0x00100000`; [`raw_to_iter.py`](../2.cpu-sim-func/raw_to_iter.py) reduce cada
valor a uint16 y añade la cabecera. Esa dirección pertenece a ese programa,
no es una dirección de framebuffer obligatoria de la ISA.

## Uso

Uso típico desde esta carpeta:

```powershell
python mandelbrot_float.py
python mandelbrot_fixed.py
python compare_iterations.py mandelbrot.iter mandelbrot_fixed.iter
python view_iterations.py
```

Los nombres de entrada y salida predeterminados están definidos al principio
de cada script. Se necesita Pillow para generar imágenes.
