# MiniCPU con SDRAM y salida HDMI

Fusión de la CPU con SDRAM de `10.fpga-cpu-ram` y la cadena DVI de `13.hdmi`,
sobre ULX3S-85F. El plan por fases está en [`docs/planning.md`](docs/planning.md)
y la arquitectura de destino en
[`docs/gpu_educativa_arquitectura.md`](docs/gpu_educativa_arquitectura.md).

Estado: **hito A completado**. Hay imagen por HDMI y la CPU sigue funcionando,
pero **todavía no se comunican**: el patrón de vídeo lo genera lógica, no se lee
ni un byte de SDRAM.

## Escalera de hitos

| Hito | Contenido | Estado |
|---|---|---|
| A | Fusión: CPU de 10 intacta + 640×480p60 con patrón generado por lógica | **hecho** |
| B | Line buffer / FIFO asíncrona alimentada por un generador falso | pendiente |
| C | Scanout real: la CPU escribe el framebuffer en SDRAM y se ve | pendiente |
| D | Escalado 2× desde 320×240 y registro `FB_BASE` | pendiente |

La separación importa: si en el hito C la pantalla sale negra, A y B ya han
descartado el pinout, los PLL, la codificación TMDS y el cruce de dominios.

## Qué hay en el hito A

Dos subsistemas independientes en la misma FPGA, sin más recurso compartido que
el cristal de 25 MHz:

```text
clk_25mhz ─┬─ pll_120 ──── 120 MHz ── CPU + monitor UART + SDRAM
           │
           └─ clock2_gen ─┬─ 125,0 MHz ── serializador TMDS
                          └─  25,0 MHz ── simple_480p → video_pattern → DVI → gpdi
```

La mitad de CPU es byte a byte la de 10: mismo mapa de memoria unificado de
32 MiB, mismos comandos de monitor, mismos cinco bancos de prueba. Lo único que
cambia es la **versión del monitor, ahora 1.7**, para que
`run_gpu_tests.py --backend cpu-fpga --version hdmi` distinga este bitstream del
1.5 de 10 y del 1.6 de 6.

### Modo de vídeo

640×480p60 con polaridad negativa en ambos sincronismos
([`simple_480p.sv`](simple_480p.sv)). El PLL entrega 125,0 y 25,0 MHz desde un
VCO de 625 MHz; los 25,0 MHz son un 0,7 % más lentos que los 25,175 nominales,
aproximación equivalente a la que hacía 13 con 74 frente a 74,25 MHz para 720p.

Bajar de 720p a 480p no es un capricho: el reloj serie TMDS pasa de 370 a
125 MHz, y con él desaparece el margen ajustado que obligaba a 13 a fijar la
semilla de nextpnr por el vídeo. Aquí sobra: 395 MHz alcanzados sobre 125
exigidos.

### Lo que se ve

Ocho barras verticales de 80 px, una banda blanca que baja cuatro líneas por
frame y una rejilla de puntos cada 64 px. La banda distingue una imagen viva de
una congelada; la rejilla revela recortes o sobreescaneo del monitor.

## Temporización: el dato incómodo del hito A

| Dominio | Restricción | 10.fpga-cpu-ram | 15 (este) |
|---|---:|---:|---:|
| CPU + SDRAM | 120 MHz | 130,67 MHz | 123,32 MHz |
| Pixel | 25 MHz | — | 160,28 MHz |
| TMDS 5× | 125 MHz | — | 395,10 MHz |

**El dominio de CPU pierde en torno a un 6 % de fmax solo por convivir con el
vídeo**, aunque no haya ninguna conexión lógica entre ambos: es presión de
colocación y congestión de routing, no un camino crítico nuevo. Y la dispersión
entre semillas es del mismo orden que el margen. Medido sobre cinco semillas:

```text
114,55   118,37   118,68   120,66   123,32 MHz
```

Dos de las cinco **no cumplen** los 120 MHz. Por eso `apio.ini` fija
`--seed 4`, igual que hacía 13. Hay que rebarrer semillas tras cualquier cambio
de RTL:

```powershell
(Get-Content _build/default/hardware.pnr -Raw | ConvertFrom-Json).fmax
```

Esto es una advertencia para el hito C: el scanout añadirá un tercer cliente
dentro del dominio de 120 MHz, y el margen actual no da para regalarlo. Si se
estrecha más, la salida razonable es bajar la restricción de la CPU en lugar de
perseguir semillas.

## Uso y comprobaciones

Desde esta carpeta:

```powershell
..\.venv\Scripts\apio.exe test cpu_sdram_system_tb.v
..\.venv\Scripts\apio.exe test cpu_tb.v
..\.venv\Scripts\apio.exe test monitor_tb.v
..\.venv\Scripts\apio.exe test sdram_controller_tb.v
..\.venv\Scripts\apio.exe test sdram_system_adapter_tb.v
..\.venv\Scripts\apio.exe build
```

Los cinco bancos son los de 10 y pasan sin cambios; el único ajuste es la
versión esperada en `monitor_tb.v`. Ninguno simula el subsistema de vídeo: el
hito A se verifica enchufando un monitor.

La suite completa de CPU contra esta placa:

```powershell
..\.venv\Scripts\python.exe ..\x.cpu-tests\run_gpu_tests.py --backend cpu-fpga --version hdmi --port COM3
```

Es la comprobación que de verdad importa del hito A: que meter el vídeo no ha
roto la CPU.

## Notas de integración

- `pll_120.v`, `clock2_gen.v` y `dvi_generator.sv` envuelven sus primitivas
  (`EHXPLLL`, `ODDRX1F`) en `` `ifdef SYNTHESIZE ``. Apio define ese símbolo al
  sintetizar y al lintar, pero no al simular, e iverilog compila **todas** las
  fuentes del proyecto para cada testbench: sin la guarda, los bancos de la CPU
  no elaborarían. Fuera de síntesis los relojes pasan a ser el de entrada y la
  serialización DDR se reduce a `D0`, así que una simulación de `top` no
  reproduce el subsistema de vídeo.
- `ulx3s.lpf` es el de 10 más los cuatro pares GPDI de `13.hdmi/ulx3s_v20.lpf`.
  Solo se restringe el pin positivo: con `IO_TYPE=LVCMOS33D` el complementario
  queda implícito y el top no declara `gpdi_dn`.
- El reset del dominio de píxel no cruza desde los 120 MHz: se sincroniza
  `btn_pwr_n` dentro del dominio de píxel y se combina con `clk_pix_locked`.
- `video_pattern.sv` expone el mismo interfaz (`sx`, `sy`, `de` → `r`, `g`, `b`)
  que tendrá el scanout del hito C, para que sustituirlo sea un cambio local.
