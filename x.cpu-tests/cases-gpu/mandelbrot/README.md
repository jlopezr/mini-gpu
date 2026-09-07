# Mandelbrot en MiniGPU

Desde la raíz del repositorio:

```powershell
.venv/Scripts/python.exe x.cpu-tests/cases-gpu/mandelbrot/run.py
```

Para ejecutar únicamente este caso con el runner, pasa su `test.json` como
argumento desde `x.cpu-tests`:

```powershell
python run_gpu_tests.py cases-gpu/mandelbrot/test.json --backend gpu-simulator
```

Ensambla el programa en memoria, lanza los ocho warps, comprueba los 76 800
píxeles contra `expected.bin` y guarda en `output/`:

- `framebuffer.bin`: 76 800 palabras uint32 little-endian, sin cabecera.
- `mandelbrot.iter`: cabecera `ITER`, dimensiones y límite uint32 little-endian,
  seguidos de los contadores uint16 little-endian; compatible con `0.mandelbrot`.
- `mandelbrot.png`: la misma escala de grises que el visor de `0.mandelbrot`.

La exportación PNG requiere Pillow (incluido en el entorno virtual actual).
La conversión del dump a `.iter` reutiliza `convert_raw_to_iter` de
`2.cpu-sim-func/raw_to_iter.py`, incluidas sus validaciones de tamaño y uint16.
`--output-dir RUTA` cambia el destino. La simulación completa puede tardar varios
minutos: es un intérprete funcional Python, no una ejecución sobre hardware GPU.

Para ejecutar solo la prueba de conformidad, sin exportar imagen ni usar Pillow:

```powershell
.venv/Scripts/python.exe x.cpu-tests/run_gpu_tests.py x.cpu-tests/cases-gpu/mandelbrot/test.json --backend gpu-simulator
```

`test.json` se incluye también en el descubrimiento automático de casos GPU;
por tanto añade el coste de una imagen completa a esa ejecución.

## Configuración y revisión

Imagen de 320 × 240, máximo 256 iteraciones, coordenadas Q16.16 en
[-2, 1] × [-1.125, 1.125], incluyendo los extremos. Cada lane escribe un contador
en `0x00100000 + 4*pixel` y avanza 64 píxeles. El framebuffer termina en
`0x0014B000` (exclusivo), dentro de los 32 MiB del simulador.

`warps.json` habilita los ocho warps completos: el salto de 64 del ensamblador
depende de este lanzamiento. Los 76 800 píxeles son múltiplo de 64, de modo que
la salida de `pixel_loop` es uniforme y no necesita SSY. Si se cambian dimensiones
o máscaras, hay que revisar tanto ese salto como la salida del bucle exterior.

El SSY del bucle Mandelbrot se renueva en cada iteración: el simulador exige una
entrada nueva para cada divergencia. Las lanes que escapan quedan pendientes
hasta `mandel_done`, conservando su contador individual. No hace falta BAR:
cada píxel tiene un único escritor y el host lee después de terminar todos.
El simulador cuenta instrucciones emitidas por warp, no ciclos de hardware.

`expected.bin` procede del algoritmo escalar de `0.mandelbrot/mandelbrot_fixed.py`,
no de la salida GPU. Para regenerarlo intencionadamente:

```powershell
.venv/Scripts/python.exe x.cpu-tests/cases-gpu/mandelbrot/run.py --reference-only
```

La ejecución normal nunca regenera la referencia. La prueba compara todas las
palabras, el total de 10 255 708 instrucciones de warp, que no hay fallo, que
los ocho warps han terminado y los registros de configuración final de una lane
de cada warp.
