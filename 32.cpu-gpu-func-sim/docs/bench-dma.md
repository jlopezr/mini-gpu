# Benchmark de memset, memcpy, fill_rect y blit: CPU contra GPU

Medido en la placa (prototipo 36, hito 1 del RTL, 8 de octubre de 2026). Es el
benchmark que pedía `diseno-gpu-dma.md` §8.2 para fijar los umbrales de decisión.

## Cómo se mide

`examples/dma/bench_dma_board.asm` (código en `bench_dma.inc`) ejecuta cada operación
con cada tamaño (32 B a 1 MiB) y cada configuración (la CPU sola y la GPU con 1, 2, 4
y 8 warps). Se hacen tres repeticiones de cada una y se queda con la mejor. Los
ciclos son los del contador `CYCLES` de la CPU (80 MHz), medidos alrededor de la
operación entera. Para la GPU eso es lo que ve el programa: preparar el bloque de
argumentos, escribir los descriptores, lanzar con `RUN` y sondear hasta el fin
(`gpu_run`). Incluye por tanto el coste fijo de cada lanzamiento, que es lo que decide
si merece la pena.

- **La CPU** usa bucles desenrollados de cuatro palabras (no es una CPU de paja).
- **Las formas.** `memset` y `memcpy` trabajan N palabras seguidas. `fill_rect` y
  `blit` usan filas de min(N, 64) palabras en un pitch de destino de 640 bytes (una
  pantalla de 320 píxeles de 16 bits); el `blit` lee de un origen contiguo.
- **La comprobación.** Antes de cada repetición se ponen a cero la primera y la
  última palabra del destino y después se comprueban. Resultado: **0 fallos** en las
  200 configuraciones.
- **No hay vídeo activo** durante la prueba, así que no compite por la memoria.
- Los MB/s son bytes entre microsegundos.

Para repetirlo:

```text
run-board --prototype 36 --port COM3 --program 32.cpu-gpu-func-sim/examples/dma/bench_dma_board.asm
python 32.cpu-gpu-func-sim/examples/dma/bench_dma_report.py --out tabla.md
```

## Resultados

Fallos de comprobación: 0

### memset

| Tamaño | CPU | GPU 1w | GPU 2w | GPU 4w | GPU 8w | mejor GPU | GPU / CPU |
|---|---:|---:|---:|---:|---:|---:|---:|
| 32 B | 7.6 µs (4.2 MB/s) | 42.7 µs (0.7 MB/s) | 49.5 µs (0.6 MB/s) | 66.6 µs (0.5 MB/s) | 104.1 µs (0.3 MB/s) | GPU 1w | 0.18 x |
| 64 B | 9.7 µs (6.6 MB/s) | 48.9 µs (1.3 MB/s) | 51.8 µs (1.2 MB/s) | 69.0 µs (0.9 MB/s) | 106.5 µs (0.6 MB/s) | GPU 1w | 0.20 x |
| 128 B | 13.9 µs (9.2 MB/s) | 58.0 µs (2.2 MB/s) | 57.9 µs (2.2 MB/s) | 74.5 µs (1.7 MB/s) | 113.2 µs (1.1 MB/s) | GPU 2w | 0.24 x |
| 256 B | 22.4 µs (11.5 MB/s) | 77.8 µs (3.3 MB/s) | 72.2 µs (3.5 MB/s) | 86.5 µs (3.0 MB/s) | 124.7 µs (2.1 MB/s) | GPU 2w | 0.31 x |
| 1 KiB | 72.7 µs (14.1 MB/s) | 193.2 µs (5.3 MB/s) | 149.1 µs (6.9 MB/s) | 161.0 µs (6.4 MB/s) | 199.3 µs (5.1 MB/s) | GPU 2w | 0.49 x |
| 4 KiB | 278.9 µs (14.7 MB/s) | 659.9 µs (6.2 MB/s) | 459.1 µs (8.9 MB/s) | 459.0 µs (8.9 MB/s) | 492.7 µs (8.3 MB/s) | GPU 4w | 0.61 x |
| 16 KiB | 1,100.7 µs (14.9 MB/s) | 2,520.5 µs (6.5 MB/s) | 1,702.5 µs (9.6 MB/s) | 1,647.6 µs (9.9 MB/s) | 1,658.7 µs (9.9 MB/s) | GPU 4w | 0.67 x |
| 64 KiB | 4,391.3 µs (14.9 MB/s) | 9,982.1 µs (6.6 MB/s) | 6,665.4 µs (9.8 MB/s) | 6,401.4 µs (10.2 MB/s) | 6,362.9 µs (10.3 MB/s) | GPU 8w | 0.69 x |
| 256 KiB | 17,522.2 µs (15.0 MB/s) | 39,812.1 µs (6.6 MB/s) | 26,538.0 µs (9.9 MB/s) | 25,437.1 µs (10.3 MB/s) | 25,157.2 µs (10.4 MB/s) | GPU 8w | 0.70 x |
| 1 MiB | 70,079.1 µs (15.0 MB/s) | 159,151.9 µs (6.6 MB/s) | 106,035.4 µs (9.9 MB/s) | 101,586.8 µs (10.3 MB/s) | 100,344.8 µs (10.4 MB/s) | GPU 8w | 0.70 x |

### memcpy

| Tamaño | CPU | GPU 1w | GPU 2w | GPU 4w | GPU 8w | mejor GPU | GPU / CPU |
|---|---:|---:|---:|---:|---:|---:|---:|
| 32 B | 12.8 µs (2.5 MB/s) | 45.6 µs (0.7 MB/s) | 52.3 µs (0.6 MB/s) | 69.4 µs (0.5 MB/s) | 107.0 µs (0.3 MB/s) | GPU 1w | 0.28 x |
| 64 B | 18.8 µs (3.4 MB/s) | 53.2 µs (1.2 MB/s) | 56.0 µs (1.1 MB/s) | 71.7 µs (0.9 MB/s) | 110.8 µs (0.6 MB/s) | GPU 1w | 0.35 x |
| 128 B | 30.8 µs (4.2 MB/s) | 66.9 µs (1.9 MB/s) | 65.4 µs (2.0 MB/s) | 82.4 µs (1.6 MB/s) | 118.3 µs (1.1 MB/s) | GPU 2w | 0.47 x |
| 256 B | 55.0 µs (4.7 MB/s) | 95.7 µs (2.7 MB/s) | 86.5 µs (3.0 MB/s) | 100.1 µs (2.6 MB/s) | 137.6 µs (1.9 MB/s) | GPU 2w | 0.64 x |
| 1 KiB | 199.6 µs (5.1 MB/s) | 269.0 µs (3.8 MB/s) | 208.4 µs (4.9 MB/s) | 215.6 µs (4.7 MB/s) | 251.6 µs (4.1 MB/s) | GPU 2w | 0.96 x |
| 4 KiB | 779.9 µs (5.3 MB/s) | 962.2 µs (4.3 MB/s) | 696.0 µs (5.9 MB/s) | 679.2 µs (6.0 MB/s) | 707.6 µs (5.8 MB/s) | GPU 4w | 1.15 x |
| 16 KiB | 3,098.4 µs (5.3 MB/s) | 3,730.2 µs (4.4 MB/s) | 2,652.3 µs (6.2 MB/s) | 2,532.0 µs (6.5 MB/s) | 2,530.3 µs (6.5 MB/s) | GPU 8w | 1.22 x |
| 64 KiB | 12,371.8 µs (5.3 MB/s) | 14,818.5 µs (4.4 MB/s) | 10,495.6 µs (6.2 MB/s) | 9,936.0 µs (6.6 MB/s) | 9,812.4 µs (6.7 MB/s) | GPU 8w | 1.26 x |
| 256 KiB | 49,471.5 µs (5.3 MB/s) | 59,146.2 µs (4.4 MB/s) | 41,848.6 µs (6.3 MB/s) | 39,567.5 µs (6.6 MB/s) | 38,957.5 µs (6.7 MB/s) | GPU 8w | 1.27 x |
| 1 MiB | 197,875.7 µs (5.3 MB/s) | 236,495.4 µs (4.4 MB/s) | 167,276.0 µs (6.3 MB/s) | 158,113.8 µs (6.6 MB/s) | 155,535.4 µs (6.7 MB/s) | GPU 8w | 1.27 x |

### fill_rect

| Tamaño | CPU | GPU 1w | GPU 2w | GPU 4w | GPU 8w | mejor GPU | GPU / CPU |
|---|---:|---:|---:|---:|---:|---:|---:|
| 32 B | 9.1 µs (3.5 MB/s) | 49.1 µs (0.7 MB/s) | 57.1 µs (0.6 MB/s) | 75.9 µs (0.4 MB/s) | 116.4 µs (0.3 MB/s) | GPU 1w | 0.19 x |
| 64 B | 11.2 µs (5.7 MB/s) | 55.2 µs (1.2 MB/s) | 61.6 µs (1.0 MB/s) | 80.4 µs (0.8 MB/s) | 121.0 µs (0.5 MB/s) | GPU 1w | 0.20 x |
| 128 B | 15.4 µs (8.3 MB/s) | 64.3 µs (2.0 MB/s) | 72.3 µs (1.8 MB/s) | 89.5 µs (1.4 MB/s) | 131.2 µs (1.0 MB/s) | GPU 1w | 0.24 x |
| 256 B | 23.8 µs (10.7 MB/s) | 84.0 µs (3.0 MB/s) | 92.0 µs (2.8 MB/s) | 109.2 µs (2.3 MB/s) | 149.8 µs (1.7 MB/s) | GPU 1w | 0.28 x |
| 1 KiB | 76.6 µs (13.4 MB/s) | 214.6 µs (4.8 MB/s) | 161.4 µs (6.3 MB/s) | 173.4 µs (5.9 MB/s) | 215.1 µs (4.8 MB/s) | GPU 2w | 0.47 x |
| 4 KiB | 283.8 µs (14.4 MB/s) | 736.2 µs (5.6 MB/s) | 503.3 µs (8.1 MB/s) | 500.3 µs (8.2 MB/s) | 536.9 µs (7.6 MB/s) | GPU 4w | 0.57 x |
| 16 KiB | 1,130.0 µs (14.5 MB/s) | 2,820.1 µs (5.8 MB/s) | 1,866.8 µs (8.8 MB/s) | 1,808.8 µs (9.1 MB/s) | 1,825.9 µs (9.0 MB/s) | GPU 4w | 0.62 x |
| 64 KiB | 4,489.5 µs (14.6 MB/s) | 11,171.2 µs (5.9 MB/s) | 7,320.6 µs (9.0 MB/s) | 7,033.1 µs (9.3 MB/s) | 7,001.4 µs (9.4 MB/s) | GPU 8w | 0.64 x |
| 256 KiB | 17,942.5 µs (14.6 MB/s) | 44,570.0 µs (5.9 MB/s) | 29,140.2 µs (9.0 MB/s) | 27,950.5 µs (9.4 MB/s) | 27,688.6 µs (9.5 MB/s) | GPU 8w | 0.65 x |
| 1 MiB | 71,806.3 µs (14.6 MB/s) | 178,161.1 µs (5.9 MB/s) | 116,421.7 µs (9.0 MB/s) | 111,609.2 µs (9.4 MB/s) | 110,445.2 µs (9.5 MB/s) | GPU 8w | 0.65 x |

### blit

| Tamaño | CPU | GPU 1w | GPU 2w | GPU 4w | GPU 8w | mejor GPU | GPU / CPU |
|---|---:|---:|---:|---:|---:|---:|---:|
| 32 B | 13.4 µs (2.4 MB/s) | 55.7 µs (0.6 MB/s) | 64.0 µs (0.5 MB/s) | 83.5 µs (0.4 MB/s) | 127.8 µs (0.3 MB/s) | GPU 1w | 0.24 x |
| 64 B | 19.5 µs (3.3 MB/s) | 63.4 µs (1.0 MB/s) | 71.5 µs (0.9 MB/s) | 90.2 µs (0.7 MB/s) | 133.8 µs (0.5 MB/s) | GPU 1w | 0.31 x |
| 128 B | 31.5 µs (4.1 MB/s) | 77.0 µs (1.7 MB/s) | 85.2 µs (1.5 MB/s) | 104.8 µs (1.2 MB/s) | 149.0 µs (0.9 MB/s) | GPU 1w | 0.41 x |
| 256 B | 55.4 µs (4.6 MB/s) | 105.9 µs (2.4 MB/s) | 114.3 µs (2.2 MB/s) | 133.8 µs (1.9 MB/s) | 178.0 µs (1.4 MB/s) | GPU 1w | 0.52 x |
| 1 KiB | 204.1 µs (5.0 MB/s) | 297.4 µs (3.4 MB/s) | 227.6 µs (4.5 MB/s) | 236.3 µs (4.3 MB/s) | 280.6 µs (3.6 MB/s) | GPU 2w | 0.90 x |
| 4 KiB | 798.4 µs (5.1 MB/s) | 1,059.0 µs (3.9 MB/s) | 756.4 µs (5.4 MB/s) | 738.0 µs (5.6 MB/s) | 771.0 µs (5.3 MB/s) | GPU 4w | 1.08 x |
| 16 KiB | 3,171.4 µs (5.2 MB/s) | 4,114.2 µs (4.0 MB/s) | 2,870.7 µs (5.7 MB/s) | 2,744.6 µs (6.0 MB/s) | 2,744.6 µs (6.0 MB/s) | GPU 4w | 1.16 x |
| 64 KiB | 12,681.1 µs (5.2 MB/s) | 16,327.3 µs (4.0 MB/s) | 11,338.6 µs (5.8 MB/s) | 10,760.0 µs (6.1 MB/s) | 10,640.9 µs (6.2 MB/s) | GPU 8w | 1.19 x |
| 256 KiB | 50,711.6 µs (5.2 MB/s) | 65,181.7 µs (4.0 MB/s) | 45,208.0 µs (5.8 MB/s) | 42,829.9 µs (6.1 MB/s) | 42,234.3 µs (6.2 MB/s) | GPU 8w | 1.20 x |
| 1 MiB | 202,830.1 µs (5.2 MB/s) | 260,603.6 µs (4.0 MB/s) | 180,691.1 µs (5.8 MB/s) | 171,116.4 µs (6.1 MB/s) | 168,616.3 µs (6.2 MB/s) | GPU 8w | 1.20 x |

## Qué dicen

**1. La GPU solo gana en las operaciones que leen (`memcpy` y `blit`), y poco.**

| 1 MiB | CPU | mejor GPU | GPU / CPU |
|---|---:|---:|---:|
| `memcpy` | 5,3 MB/s | 6,7 MB/s (8 warps) | 1,27 x |
| `blit` | 5,2 MB/s | 6,2 MB/s (8 warps) | 1,20 x |
| `memset` | 15,0 MB/s | 10,4 MB/s (8 warps) | **0,70 x** |
| `fill_rect` | 14,6 MB/s | 9,5 MB/s (8 warps) | **0,65 x** |

La CPU escribe a 15 MB/s y copia a casi un tercio de eso, porque cada palabra cuesta
una lectura y una escritura. La GPU tiene un techo parecido para lo uno y lo otro
(~10 MB/s escribiendo y ~6,7 MB/s copiando). Por eso solo gana donde la CPU es mala,
que es leyendo.

**2. El coste fijo de lanzar es grande: unos 40 µs con un warp y casi 9 µs más por
cada warp adicional.** Con 32 B, la CPU tarda 7,6 µs en `memset` y la GPU 42,7 µs con
un warp y 104 µs con ocho. La pendiente, (104,1 - 42,7) / 7 = 8,8 µs por warp, es
lo que cuesta escribir el descriptor de cada uno: cinco accesos MMIO, unos 1,8 µs
cada acceso. Lanzar más warps de los que hacen falta cuesta, y no se recupera hasta
que la operación es grande.

**3. El punto de equilibrio está entre 1 y 4 KiB, y solo para `memcpy` y `blit`.**
`memcpy`: 0,96 x en 1 KiB, 1,15 x en 4 KiB. `blit`: 0,90 x en 1 KiB, 1,08 x en 4 KiB.
Para `memset` y `fill_rect` no hay punto de equilibrio en ninguno de los tamaños.

**4. Más warps ayudan poco y se saturan pronto.** De 1 a 2 warps el tiempo baja casi
un tercio en las operaciones grandes, y de 2 a 4 otro 4 a 6 %. Con 8 warps no
mejora a 4: el límite es la memoria, no el número de warps. En las operaciones pequeñas
(hasta 16 KiB) el mejor es 2 o 4 warps, porque cada warp de más cuesta 9 µs.

## Lo que sale de aquí para la política CPU / GPU

Hoy, en esta placa y con esta GPU:

- **`memset` y `fill_rect`: que los haga la CPU, siempre.** La GPU es más lenta para
  cualquier tamaño.
- **`memcpy` y `blit`: a la GPU desde unos 4 KiB, con 4 warps.** Eso fija, como valores
  iniciales, `GPU_THRESHOLD_MEMCPY` = 4096 y `GPU_MAX_WARPS_PER_JOB` = 4.
- La ganancia en tiempo es pequeña (1,2 a 1,3 x). Lo que sí aporta la GPU es dejar la
  CPU **libre** durante la operación: con la API asíncrona de §3, un `memcpy` de 1 MiB
  ocupa a la GPU 155 ms y a la CPU, solo el tiempo de lanzarlo.

## Lo que no se ha comprobado

- **Por qué el techo de la GPU es ~10 MB/s.** Con 8 warps, escribir 1 MiB son 65 536
  transacciones de 16 B en 100 ms: unos 38 ciclos de GPU (25 MHz) por transacción. El
  simulador de ciclos suponía 17. Hay dos hipótesis, sin medir: que la CPU, que sondea
  el MMIO de la GPU mientras espera, le quite tiempo al puente, o que la contienda en
  el fabric de seis puertos sea mayor de lo que modela el simulador. Se podría separar
  midiendo con la CPU sin sondear (esperar un tiempo fijo y leer `WARP_DONE` una sola vez).
- **Con el vídeo activo.** La lectura de pantalla compite con la GPU y con la CPU por
  la SDRAM. No se ha medido el efecto.
- Los kernels hacen una palabra por lane y vuelta con un bucle de siete instrucciones
  y no están optimizados (por ejemplo, desenrollados): si el límite estuviera en las
  instrucciones y no en la memoria, el techo de la GPU podría subir.
