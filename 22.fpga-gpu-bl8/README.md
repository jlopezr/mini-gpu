# MiniGPU sobre fabric de 4 puertos y SDRAM BL8

Prototipo en construcción. Parte de `17.fpga-gpu-ram-v2` (la GPU) y de
`21.fpga-cpu-hdmi-alu` (el camino de memoria de 128 bits), con una LSU nueva
que coalesce por línea de 16 bytes en vez de servir una lane por acceso.

| Documento | De qué va |
| --- | --- |
| [`lsu-v2.md`](lsu-v2.md) | La LSU con coalescencia: diseño, medidas, y los pasos que **no** funcionaron |
| [`video-scanout.md`](video-scanout.md) | Lo que cuesta el scanout, medido, y `VIDEO_CTRL` |
| [`mmio.md`](mmio.md) | Por qué se abrió la ventana MMIO a la GPU y cómo está hecha |
| [`profiling.md`](profiling.md) | **Dónde se va el tiempo**, con los contadores de `0x80000300` |
| [`sm-pipeline.md`](sm-pipeline.md) | Propuesta para segmentar el cauce del SM (diseño, sin implementar) |

Para medir en placa sin simular: `python profile.py --port COM3 --program examples/plasma.asm`.

## Estado

| Pieza | Estado |
| --- | --- |
| `gpu_lsu2.v` — LSU v2.0, coalescencia por línea de 16 bytes | `gpu_lsu2_tb.v` pasa |
| `gpu_aux_adapter_128.v` — host/monitor → fabric | `gpu_aux_adapter_128_tb.v` pasa |
| `gpu_imem_buffer.v` — `instruction_buffer` de 21 tras el `imem` de `gpu_sm` | Integrado |
| `gpu_system_bl8.v` + `top_bl8.v` — sistema completo | 32 casos diferenciales pasan, sintetiza |
| Segmentación (v2.1: `pending_spec`, preparación en la sombra) | Diseñada, sin escribir |

### Resultados

| | Ciclos (32 casos) | Fmax | COMB |
| --- | --- | --- | --- |
| `default` — base heredada de 17 (LSU v1, BL1) | 139 533 | 44,14 MHz | 31 076 |
| `bl8` — LSU v2 + buffer de instrucciones + fabric | **80 491** | 36,57 MHz | 31 012 |

**x1,44 de rendimiento neto** (−42% de ciclos, −17% de Fmax, misma área). El
detalle de cómo se llegó ahí, incluidos los pasos que NO funcionaron, está en
[`lsu-v2.md`](lsu-v2.md). Resumen: la ganancia es casi toda del buffer de
instrucciones, no de la LSU — el fetch mueve ~1600× más tráfico que los
accesos vectoriales.

El camino crítico del chip está ahora dentro de `gpu_lsu2` (`grp_line` →
`n_lanes`), así que es ahí donde toca seguir si se quiere recuperar Fmax.

`gpu_system.v`, `top.v` y `gpu_lsu.v` son la copia sin tocar de 17: son la
línea base contra la que se compara, no se usan en el diseño nuevo.

## Cómo reproducir las medidas de ciclos

```powershell
$env:PATH="C:\Users\j_lop\.apio\packages\oss-cad-suite\bin;C:\Users\j_lop\.apio\packages\oss-cad-suite\lib;$env:PATH"
cd 22.fpga-gpu-bl8
# Base (BL1)
iverilog -g2005-sv -o base.out gpu_system_tb.v gpu_system.v gpu_lsu.v `
    sdram_controller.v gpu_sm.v gpu_lane.v gpu_register_file.v util.v
vvp base.out
# Sistema BL8
iverilog -g2005-sv -o bl8.out gpu_system_bl8_tb.v gpu_system_bl8.v gpu_lsu2.v `
    gpu_aux_adapter_128.v gpu_imem_buffer.v instruction_buffer.v `
    memory_fabric_4.v sdram_controller_128.v sdram_model.v `
    gpu_sm.v gpu_lane.v gpu_register_file.v util.v
vvp bl8.out
```

Se suman los `cycles=` de las líneas `EXEC differential case`. El banco BL8
imprime además el reparto de tráfico por puerto del fabric al terminar.

**Cuidado con el modelo de SDRAM:** el camino BL8 necesita `sdram_model.v` (el
de 21, con ráfagas y puerto `dq`), no el `sim/sdram_model.vh` de 17, que es
funcional BL1 y devuelve basura ante una ráfaga.

## `READ_DELAY_CYCLES`: calibración de placa, derivada del reloj

El parámetro que dice cuántos ciclos esperar de más antes de muestrear DQ
**ya no es un número fijo**: `sdram_controller_128.v` lo deriva de
`CLK_FREQ_HZ`. El retardo de ida y vuelta al chip es físico y constante
(~18 ps×10³ según la única calibración que hay: 1 ciclo a 80 MHz en 21), pero
los *ciclos* que ocupa dependen del reloj — 0 a 25 MHz, 1 hasta 111 MHz, 2
hasta 166 MHz.

Esto importa porque es lo que hizo que la primera prueba en placa fallara con
`ERROR_INVALID_ENCODING` en PC=0: el valor por defecto de 1, heredado de 21 (que
corre a 80 MHz), hacía muestrear un ciclo tarde a 25 MHz y las instrucciones
volvían desplazadas una palabra de 16 bits.

**Una simulación no puede detectar esto.** El modelo tiene el mismo parámetro,
así que controlador y modelo se ponen de acuerdo en el valor que sea y el banco
pasa igual. Por eso `sim/system_memory_bl8.vh` calcula `BOARD_READ_DELAY` con la
misma fórmula: el modelo representa la *placa*, no lo que le convenga al
controlador. Lo aviso porque es fácil "arreglar" un fallo de placa tocando el
modelo y creer que está resuelto.

Hay **dos puntos medidos en placa**: 80 MHz → 1 (en 21, en producción) y
25 MHz → 0 (aquí; con 1 la primera instrucción daba `ERROR_INVALID_ENCODING`,
con 0 el programa corre y para en el `HALT` con el mismo PC que la simulación).
Lo que la fórmula predice para otros relojes sigue siendo inferencia.

## Cómo medir la LSU sola

Los envs `lsu2-timing` y `lsu1-timing` sintetizan cada LSU sola en un chip
vacío, con envoltorios gemelos (`lsu_timing_top.v` / `lsu1_timing_top.v`) que
alimentan las entradas anchas con un LFSR y reducen las salidas a los LED.

```powershell
cd 22.fpga-gpu-bl8
..\.venv\Scripts\apio.exe build -e lsu2-timing
..\.venv\Scripts\apio.exe build -e lsu1-timing
```

Y el número sale de `_build/<env>/hardware.pnr`:

```powershell
(Get-Content _build\lsu2-timing\hardware.pnr -Raw | ConvertFrom-Json).fmax
```

**El Fmax de estos envs no es comparable con el del sistema completo**: sin el
SM alrededor no hay competencia por rutado ni fanout, así que es optimista por
construcción. Sirve para comparar v1 contra v2 entre sí, y para descartar que
una lógica sea catastróficamente lenta. El Fmax de verdad sale del build del
sistema y de la lectura de su camino crítico, como en
`17.fpga-gpu-ram-v2/docs/optimizacion.md`.

## Simular la LSU sin apio

```powershell
$env:PATH="C:\Users\j_lop\.apio\packages\oss-cad-suite\bin;C:\Users\j_lop\.apio\packages\oss-cad-suite\lib;$env:PATH"
iverilog -g2005-sv -o lsu2.out gpu_lsu2.v gpu_lsu2_tb.v
vvp lsu2.out
```
