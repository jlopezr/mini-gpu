# MiniGPU — Plan de optimización de `dma_engine_v2`

**Estado:** pendientes de implementar y medir.  
**Configuración de referencia:** 2 canales, `TAG_DEPTH=8`, síntesis `synth_ecp5` con Yosys.  
**Objetivo:** reducir recursos de FPGA manteniendo la interfaz MMIO, el protocolo del fabric y el comportamiento de los testbenches.

## 1. Punto de partida

| Versión / cambio | LUT4 | FF (`TRELLIS_FF`) | CCU2C | Validación |
|---|---:|---:|---:|---|
| `dma_engine.v` original, 2 canales | 3.486 | 1.372 | 220 | Stress TB: PASS |
| V2: escrituras MMIO por canal estático | 2.896 | 1.373 | 220 | Stress TB: PASS |
| V2: sumador de avance por dirección | 2.343 | 1.373 | 164 | Stress TB: PASS |
| **V2 actual: contadores ajustados** | **2.376** | **1.357** | **152** | **Stress TB: PASS** |

Reducción acumulada respecto a V1: **−31,8 % LUT4**, **−1,1 % FF** y **−30,9 % CCU2C**.

Última prueba funcional observada (2 canales): **PASS**; 1.922 solicitudes, 1.922 respuestas, 641 lecturas, 1.281 escrituras, pico de 5 pendientes y 1.369 cambios de canal.

> Las cifras son de síntesis, no de *place & route*. Una reducción de LUT4 no garantiza mejor frecuencia, congestión o empaquetado.

## 2. Optimizaciones pendientes

| # | Optimización | Qué cambiar / investigar | Ahorro esperado (cualitativo) | Dificultad | Riesgo | Prioridad |
|---|---|---|---|---|---|---|
| 1 | **Compartir sumadores entre canales** | Mover el cálculo de `src_next` y `dst_next` al canal seleccionado, conservando estado por canal y sin cambiar la semántica de emisión | Alto en CCU2C; LUT incierto | Media | Medio | **Muy alta** |
| 2 | **Simplificar el scheduler** | Sustituir accesos `busy[candidate]`, `rows_left[candidate]`, etc. por selecciones estáticas, revisar round-robin y prioridad | Medio-alto en LUT | Media | Medio | **Alta** |
| 3 | **Optimizar selección de datos de 128 bits** | Revisar multiplexores de `read_buffer[chosen]`, `pattern[chosen]` y carga de `slot_data` | Medio en LUT / multiplexores | Media | Medio | **Alta** |
| 4 | **Eliminar o sustituir `src_row` / `dst_row`** | Estudiar incremento de fin de fila usando `cur`, `stride` y `width`, sin multiplicadores y preservando el avance 2D | FF posible; LUT incierto | Alta | Medio-alto | Media |
| 5 | **Compartir aritmética de `bytes_done` y progreso** | Revisar contadores e incrementos para evitar sumadores redundantes | Bajo-medio en CCU2C | Media | Medio | Media |
| 6 | **Optimizar actualización de respuestas y estado** | Revisar `read_pending`, `data_valid`, `writes_pending`, errores, cancelaciones y `DONE`, usando decodificación por canal | Medio en LUT | Media | Alto | Media |
| 7 | **Reducir duplicación configuración/ejecución** | Evaluar solapamientos entre registros MMIO (`src`, `dst`, `width`, `height`) y estado operativo | Medio en FF | Alta | Alto | Baja |
| 8 | **Simplificar FIFO de etiquetas** | Revisar almacenamiento y acceso a `tags_ch` / `tags_read`, punteros y contadores | Bajo en LUT/FF | Baja-media | Medio | Baja |
| 9 | **Explorar distributed RAM para estado/buffers** | Valorar alternativas a FF para arrays concretos; comprobar coste de lectura y escritura | Incierto; posible ahorro FF | Alta | Medio-alto | Baja |
| 10 | **Datapath totalmente compartido** | Rediseñar la ejecución para centralizar cálculos y transferencias entre todos los canales | Potencialmente alto en LUT/CCU2C | Muy alta | Alto | Último recurso |

Los ahorros son **hipótesis**, no estimaciones numéricas confirmadas. Algunos cambios pueden aumentar recursos o latencia.

## 3. Secuencia recomendada

### Etapa A — Lógica combinacional

**Experimentos 1 → 2 → 3.** Priorizar compartir los sumadores entre canales, después scheduler y selección de datos de 128 bits. Medir en cada paso LUT4, CCU2C, PFUMX, L6MUX21 y FF.

### Etapa B — Estado y contadores

**Experimentos 4 → 5.** No eliminar registros de comienzo de fila sin demostrar que el nuevo cálculo mantiene las direcciones en COPY/FILL2D, especialmente con strides mayores que `width`.

### Etapa C — Ajustes estructurales

**Experimentos 6 → 10.** Reservar rediseños importantes para cuando la síntesis y el *place & route* indiquen cuellos de botella reales.

## 4. Procedimiento para cada experimento

1. Guardar checkpoint de `dma_engine_v2.v` y anotar métricas anteriores.
2. Aplicar **un cambio funcional o estructural cada vez**.
3. Ejecutar `dma_engine_stress_tb` contra V2 (2 canales); comprobar datos, recuentos, errores y ausencia de bloqueos.
4. Repetir con 4 canales si el cambio afecta a la parametrización, selección o scheduler.
5. Sintetizar bajo las mismas opciones Yosys; comparar recursos.
6. Registrar resultado y conservar o revertir según ahorro y corrección.
7. Antes de integrar en `top.v`, verificar timing y congestión con *place & route* sobre el dispositivo real.

### Síntesis de dos canales

```bash
~/.apio/packages/oss-cad-suite/bin/yosys -p \
'read_verilog -sv dma_engine_v2.v; hierarchy -top dma_engine_v2 -chparam NUM_CHANNELS 2; synth_ecp5 -top dma_engine_v2; stat' \
> dma_v2_2ch.log

tail -35 dma_v2_2ch.log
```

### Testbench de estrés con V2

```bash
sed 's/dma_engine #(/dma_engine_v2 #(/' \
  dma_engine_stress_tb.v > /tmp/dma_engine_v2_stress_tb.v

~/.apio/packages/oss-cad-suite/bin/iverilog \
  -g2012 -s dma_engine_stress_tb \
  -o /tmp/dma_v2_stress.out \
  dma_engine_v2.v /tmp/dma_engine_v2_stress_tb.v

~/.apio/packages/oss-cad-suite/bin/vvp /tmp/dma_v2_stress.out
```

Para la variante de 4 canales, añadir `-DDMA_CHANNELS=4` a Icarus si el testbench emplea esa macro, y sintetizar con `-chparam NUM_CHANNELS 4`.

## 5. Precauciones

- No confundir **solicitudes pendientes** con canales simultáneos: el motor tiene un único puerto de memoria, pero admite varias operaciones en vuelo.
- Preservar la estabilidad `req_valid`/datos/dirección hasta `req_ready`.
- Mantener respuestas ordenadas mediante etiquetas y comprobar errores en lecturas y escrituras.
- `DONE` debe anunciarse solo cuando no queden operaciones relevantes pendientes.
- La comparación de 2 frente a 4 canales requiere **cargas equivalentes**; los totales de los testbenches anteriores no son una medida directa de rendimiento.
- Para decisiones finales usar también recursos de empaquetado, frecuencia máxima y congestión tras *place & route*.

## 6. Próximo experimento

**#1: compartir `src_next` y `dst_next` entre canales.** Primero comprobar que cada ciclo solo actualiza el canal cuya escritura se acepta (`issue_write`), sin alterar el ritmo de emisión. A continuación medir las diferencias respecto al punto de partida **2.376 LUT4 / 1.357 FF / 152 CCU2C**.
