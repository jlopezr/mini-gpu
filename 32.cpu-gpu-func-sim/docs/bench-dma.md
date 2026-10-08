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

## ¿El sondeo de la CPU frena a la GPU? No

El benchmark dejó una pregunta: la GPU escribe a ~10 MB/s, unos 38 ciclos de GPU por
transacción de 16 B, y el simulador de ciclos suponía 17. Una hipótesis era que la CPU,
que mientras espera lee sin parar `STATUS` y `WARP_DONE` del MMIO de la GPU, le quitara
tiempo al puente entre los dos relojes.

`examples/dma/poll_exp_board.asm` (código en `poll_exp.inc`) la pone a prueba. Lanza
`memset` y `memcpy` de 256 KiB con 1, 2, 4 y 8 warps y espera de tres maneras: sondeando
sin parar (como `gpu_run`), sondeando con una pausa de unos 40 µs entre lecturas, y sin
tocar el MMIO de la GPU durante unos 275 ms para leerlo una sola vez cuando ya ha
terminado. Se mide con los contadores de rendimiento **de la propia GPU** (`CYCLES`,
`LSU_TX`, `STALL_MEM`, en `0x82030000`), que solo avanzan con la GPU corriendo y por tanto
no dependen de cómo espere la CPU. Para repetirlo:

```text
run-board --prototype 36 --port COM3 --program 32.cpu-gpu-func-sim/examples/dma/poll_exp_board.asm
python 32.cpu-gpu-func-sim/examples/dma/poll_exp_report.py
```

| Operación | Warps | Modo de espera | Ciclos GPU | Transacciones | Ciclos GPU por transacción | Instrucciones de warp | Ciclos por instrucción | Fallos IMEM | Espera de memoria | MB/s (reloj de la GPU) | Ciclos CPU |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| memset | 1 | sondeo continuo | 994,916 | 16,389 | 60.7 | 49,167 | 20.2 | 5 | 0 % | 6.59 | 3,186,136 |
| memset | 1 | sondeo con pausa | 994,793 | 16,389 | 60.7 | 49,167 | 20.2 | 5 | 0 % | 6.59 | 3,188,075 |
| memset | 1 | sin sondear | 994,767 | 16,389 | 60.7 | 49,167 | 20.2 | 5 | 0 % | 6.59 | 22,002,616 |
| memset | 2 | sondeo continuo | 662,985 | 16,394 | 40.4 | 49,182 | 13.5 | 5 | 0 % | 9.88 | 2,124,308 |
| memset | 2 | sondeo con pausa | 662,858 | 16,394 | 40.4 | 49,182 | 13.5 | 5 | 0 % | 9.89 | 2,124,998 |
| memset | 2 | sin sondear | 662,939 | 16,394 | 40.4 | 49,182 | 13.5 | 5 | 0 % | 9.89 | 22,002,843 |
| memset | 4 | sondeo continuo | 635,157 | 16,404 | 38.7 | 49,212 | 12.9 | 5 | 0 % | 10.32 | 2,035,592 |
| memset | 4 | sondeo con pausa | 635,406 | 16,404 | 38.7 | 49,212 | 12.9 | 5 | 0 % | 10.31 | 2,039,844 |
| memset | 4 | sin sondear | 635,151 | 16,404 | 38.7 | 49,212 | 12.9 | 5 | 0 % | 10.32 | 22,003,322 |
| memset | 8 | sondeo continuo | 628,113 | 16,424 | 38.2 | 49,272 | 12.7 | 5 | 0 % | 10.43 | 2,014,076 |
| memset | 8 | sondeo con pausa | 627,783 | 16,424 | 38.2 | 49,272 | 12.7 | 5 | 0 % | 10.44 | 2,013,748 |
| memset | 8 | sin sondear | 628,072 | 16,424 | 38.2 | 49,272 | 12.7 | 5 | 0 % | 10.43 | 22,004,240 |
| memcpy | 1 | sondeo continuo | 1,478,299 | 32,773 | 45.1 | 65,551 | 22.6 | 6 | 0 % | 4.43 | 4,732,956 |
| memcpy | 1 | sondeo con pausa | 1,478,256 | 32,773 | 45.1 | 65,551 | 22.6 | 6 | 0 % | 4.43 | 4,733,504 |
| memcpy | 1 | sin sondear | 1,478,303 | 32,773 | 45.1 | 65,551 | 22.6 | 6 | 0 % | 4.43 | 22,002,604 |
| memcpy | 2 | sondeo continuo | 1,045,636 | 32,778 | 31.9 | 65,566 | 15.9 | 6 | 0 % | 6.27 | 3,348,654 |
| memcpy | 2 | sondeo con pausa | 1,045,707 | 32,778 | 31.9 | 65,566 | 15.9 | 6 | 0 % | 6.27 | 3,350,496 |
| memcpy | 2 | sin sondear | 1,045,700 | 32,778 | 31.9 | 65,566 | 15.9 | 6 | 0 % | 6.27 | 22,002,838 |
| memcpy | 4 | sondeo continuo | 988,537 | 32,788 | 30.1 | 65,596 | 15.1 | 6 | 0 % | 6.63 | 3,166,506 |
| memcpy | 4 | sondeo con pausa | 988,429 | 32,788 | 30.1 | 65,596 | 15.1 | 6 | 0 % | 6.63 | 3,166,260 |
| memcpy | 4 | sin sondear | 988,656 | 32,788 | 30.2 | 65,596 | 15.1 | 6 | 0 % | 6.63 | 22,003,300 |
| memcpy | 8 | sondeo continuo | 972,935 | 32,808 | 29.7 | 65,656 | 14.8 | 6 | 0 % | 6.74 | 3,117,491 |
| memcpy | 8 | sondeo con pausa | 972,861 | 32,808 | 29.7 | 65,656 | 14.8 | 6 | 0 % | 6.74 | 3,117,612 |
| memcpy | 8 | sin sondear | 972,859 | 32,808 | 29.7 | 65,656 | 14.8 | 6 | 0 % | 6.74 | 22,004,246 |

**Los ciclos de GPU son los mismos con los tres modos de espera**, con diferencias de
0,03 % o menos, y las transacciones también. El sondeo no frena a la GPU: la hipótesis
es falsa. Lo que sale de la tabla, además:

- **Las transacciones son las esperadas.** 256 KiB son 16 384 de 16 B y se miden 16 389:
  las cinco de más son las lecturas de los cinco argumentos del kernel. La coalescencia
  funciona exactamente como se diseñó: ocho palabras seguidas de un warp son dos
  transacciones.
- **`STALL_MEM` vale 0 siempre, y no dice nada.** Cuenta los ciclos en que la LSU tiene una
  petición y la interfaz no la acepta (`lsu_valid && !lsu_ready`), y la LSU acepta y espera la
  respuesta por dentro. No sirve para ver si la GPU espera a la memoria.
- **Ciclos por transacción.** Con la memoria saturada (4 u 8 warps) son 38 a 39 ciclos de
  GPU por transacción de 16 B en `memset` y 30 en `memcpy`, el doble de los 17 del modelo.
  Con un solo warp son 61 y 45. La sección siguiente explica de dónde sale.

## Qué limita de verdad a la GPU: el ritmo de instrucciones, no la memoria

Con el sondeo descartado quedaban la LSU y la SDRAM. `examples/dma/lat_exp_board.asm`
(código en `lat_exp.inc`) mide la latencia de UN acceso: un warp con una sola lane
activa hace N accesos dependientes uno detrás de otro, con separaciones entre
direcciones de 0 a 64 KiB, y se compara con el mismo bucle sin acceso. Para repetirlo:

```text
run-board --prototype 36 --port COM3 --program 32.cpu-gpu-func-sim/examples/dma/lat_exp_board.asm
python 32.cpu-gpu-func-sim/examples/dma/lat_exp_report.py
```

| Kernel | Stride | N | Ciclos GPU | Ciclos por vuelta | Instrucciones | Ciclos por instrucción | Fallos IMEM | Transacciones | Latencia del acceso (ciclos) | (ns) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| sin acceso (línea base) | 0 | 2000 | 144,181 | 72.1 | 10,006 | 14.4 | 4 | 3 | - | - |
| sin acceso (línea base) | 16 | 2000 | 144,181 | 72.1 | 10,006 | 14.4 | 4 | 3 | - | - |
| sin acceso (línea base) | 64 | 2000 | 144,181 | 72.1 | 10,006 | 14.4 | 4 | 3 | - | - |
| sin acceso (línea base) | 256 | 2000 | 144,181 | 72.1 | 10,006 | 14.4 | 4 | 3 | - | - |
| sin acceso (línea base) | 1024 | 2000 | 144,183 | 72.1 | 10,006 | 14.4 | 4 | 3 | - | - |
| sin acceso (línea base) | 4096 | 2000 | 144,181 | 72.1 | 10,006 | 14.4 | 4 | 3 | - | - |
| sin acceso (línea base) | 16384 | 512 | 37,045 | 72.4 | 2,566 | 14.4 | 4 | 3 | - | - |
| sin acceso (línea base) | 65536 | 128 | 9,397 | 73.4 | 646 | 14.5 | 4 | 3 | - | - |
| load | 0 | 2000 | 172,242 | 86.1 | 10,006 | 17.2 | 4 | 2,003 | 14.0 | 561 |
| load | 16 | 2000 | 172,240 | 86.1 | 10,006 | 17.2 | 4 | 2,003 | 14.0 | 561 |
| load | 64 | 2000 | 172,242 | 86.1 | 10,006 | 17.2 | 4 | 2,003 | 14.0 | 561 |
| load | 256 | 2000 | 172,256 | 86.1 | 10,006 | 17.2 | 4 | 2,003 | 14.0 | 561 |
| load | 1024 | 2000 | 172,236 | 86.1 | 10,006 | 17.2 | 4 | 2,003 | 14.0 | 561 |
| load | 4096 | 2000 | 172,243 | 86.1 | 10,006 | 17.2 | 4 | 2,003 | 14.0 | 561 |
| load | 16384 | 512 | 44,231 | 86.4 | 2,566 | 17.2 | 4 | 515 | 14.0 | 561 |
| load | 65536 | 128 | 11,192 | 87.4 | 646 | 17.3 | 4 | 131 | 14.0 | 561 |
| store | 0 | 2000 | 172,299 | 86.1 | 10,008 | 17.2 | 4 | 2,003 | 14.1 | 562 |
| store | 16 | 2000 | 172,336 | 86.2 | 10,008 | 17.2 | 4 | 2,003 | 14.1 | 563 |
| store | 64 | 2000 | 172,313 | 86.2 | 10,008 | 17.2 | 4 | 2,003 | 14.1 | 563 |
| store | 256 | 2000 | 172,276 | 86.1 | 10,008 | 17.2 | 4 | 2,003 | 14.0 | 562 |
| store | 1024 | 2000 | 172,324 | 86.2 | 10,008 | 17.2 | 4 | 2,003 | 14.1 | 563 |
| store | 4096 | 2000 | 172,278 | 86.1 | 10,008 | 17.2 | 4 | 2,003 | 14.0 | 562 |
| store | 16384 | 512 | 44,255 | 86.4 | 2,568 | 17.2 | 4 | 515 | 14.1 | 563 |
| store | 65536 | 128 | 11,224 | 87.7 | 648 | 17.3 | 4 | 131 | 14.3 | 571 |

**1. La separación entre direcciones no importa: la SDRAM y sus filas quedan descartadas.**
Un `load` y un `store` cuestan 14 ciclos más que la misma vuelta sin acceso (560 ns),
igual con 0 B que con 64 KiB de separación. Un acceso aislado ni siquiera es caro.

**2. Lo que sí es caro es cada instrucción.** El bucle sin ningún acceso, con cinco
instrucciones, tarda 72 ciclos por vuelta: **14,4 ciclos de GPU por instrucción de warp
retirada**, con un solo warp y sin fallos de búfer de instrucciones (4 en total). Un
warp no puede lanzar una instrucción detrás de otra: tarda unos 14 ciclos en completarla.

**3. Y con más warps no baja del todo: unos 12,7 ciclos por instrucción.** Con `memset`,
que mide los ciclos y las instrucciones retiradas con los contadores de la propia GPU:

| Warps | Ciclos GPU | Instrucciones de warp | Ciclos por instrucción | Ciclos por transacción |
|---:|---:|---:|---:|---:|
| 1 | 994 916 | 49 167 | 20,2 | 60,7 |
| 2 | 662 985 | 49 182 | 13,5 | 40,4 |
| 4 | 635 157 | 49 212 | 12,9 | 38,7 |
| 8 | 628 113 | 49 272 | 12,7 | 38,2 |

El número de instrucciones es el mismo (el trabajo es el mismo); lo que cambia es lo que
tarda cada una. Con un warp son 20,2 ciclos: los 14 de la instrucción más lo que espera
a memoria. Con dos o más warps se tapa la espera y se llega a un suelo de ~12,7 ciclos
por instrucción de warp **que no baja con más warps**: el SM retira una instrucción cada
12,7 ciclos como mucho, con independencia de cuántos warps haya listos.

**Y eso explica el techo de ~38 ciclos por transacción.** El bucle de `memset` son seis
instrucciones por dos transacciones (una instrucción `STORE` de ocho lanes es una
escritura de 32 B, dos de 16 B): tres instrucciones por transacción, 3 x 12,7 = 38,2. El de
`memcpy` son ocho instrucciones por cuatro transacciones: dos por transacción, 2 x 12,7 =
25,5 (se miden 29,7). El techo de ~10 MB/s no lo pone la memoria, sino que hay
demasiadas instrucciones por cada byte movido.

También explica por qué el modelo de ciclos de la 25 subestimaba el código con cálculo:
suponía una instrucción por ciclo en la etapa X y la placa tarda unos 13. Los 46 564
instrucciones de warp de un fotograma del plasma v2 a 12,7 ciclos son 23,7 ms, y se
midieron 19,6; el modelo daba 8,4.

**Qué implica.** El rendimiento de la GPU es, hoy, **~2 millones de instrucciones de warp
por segundo** (25 MHz entre 12,7), es decir, unos 16 millones de operaciones de lane por
segundo con las ocho lanes activas. La CPU hace unos 10 millones de instrucciones por
segundo (80 MHz entre unos 7,5 ciclos por instrucción, el CPI medido en el plasma). Con
las ocho lanes activas, la GPU solo es 1,5 veces más rápida que la CPU en operaciones por
segundo. Lo que ganan los demos de `race` por encima de eso viene de que la CPU paga
más en sus instrucciones lentas (un desplazamiento cuesta 7 + n ciclos y una
multiplicación 11) y de que la GPU las comparte entre ocho lanes.
Hay dos caminos para mejorarlo:

- **En el RTL del SM:** que una instrucción de warp no tarde 12 o 14 ciclos. Es lo que
  limita todo lo demás.
- **En los kernels, sin tocar el RTL:** menos instrucciones por transacción. Desenrollar el
  bucle de `memset` para que una vuelta haga cuatro `STORE` con desplazamientos
  inmediatos deja una instrucción por transacción, tres veces menos que ahora. Con eso la GPU
  pasaría de 10 MB/s a unos 30 MB/s, por encima de los 15 de la CPU. No se ha probado.

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

- **Con el vídeo activo.** La lectura de pantalla compite con la GPU y con la CPU por
  la SDRAM. No se ha medido el efecto.
- **Si desenrollar los kernels sube de verdad el techo.** La cuenta dice que sí, de unos 10
  MB/s a unos 30 en `memset`, pero no se ha escrito ni medido. Si la cuenta es cierta, la
  política de arriba (`memset` y `fill_rect` siempre por la CPU) cambia.
- **De dónde salen los ~12,7 ciclos por instrucción** (si son las lanes en serie, la
  profundidad del cauce o la falta de bypass del SM, que es lo que dice el comentario
  de `gpu_perf_counters.v` sobre este prototipo). Eso es una pregunta para el RTL, no
  para los kernels.
