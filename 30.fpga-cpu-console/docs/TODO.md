# TODO: ideas para Fmax y CPI de la 30

Estado a 2026-09-29. Build actual: `sdram_clk` a **84,33 MHz** (semilla 15, objetivo 80),
CPI 8,199, **97,23 ns/instr**. Punto de partida del día: 81,29 MHz, CPI 8,213 y
101,03 ns/instr.

El reloj real está fijo a 80 MHz (divisor de la UART). Por eso un Fmax mayor solo da
margen y una proyección de ns/instr: la velocidad real depende del CPI mientras el
diseño cierre a 80.

**Protocolo de medida**, un cambio por experimento:

1. `.\tools\test.ps1 --prototype 30`
2. `build`, y `build-sweep` con 16 semillas (`--jobs`) y `--apply`. La semilla es
   propiedad de un netlist concreto: se rebarre tras cada cambio de RTL.
3. `board-upload`, y `test-board --measure --measure-label <etiqueta>`.
4. `measure-compare -p 30` y `timing-wall -p 30 --cross`.

Métrica de decisión: ns/instr = CPI / Fmax. Con 16 semillas, una mejora del máximo de
unos 0,3 MHz cae dentro del ruido; cuentan la mediana y el peor caso.

## Resuelto

| Idea | Origen | Objetivo | Resultado |
| --- | --- | --- | --- |
| 0. Un acierto del buffer cuesta ~1 ciclo | Original | Diagnóstico | Confirmada por lectura. Segmentar el acierto ya había empeorado el CPI un 8 % |
| 1. `cpu_dmem_adapter` en dos fases | Original | Fmax, con +1 ciclo por LOAD/STORE | **Descartada**: el muro ya no está ahí (`wb_data` llegó a 11,66 ns solo porque el colocador relajó) |
| 3. Salida registrada en `serial_port` (y `perf`) | Original | Fmax | **Hecha**: 82,00 MHz, ns/instr −1,0 % |
| Fabric: `response_data` sin cero por error | Nueva | Fmax | **Hecha**: 84,08 MHz, ns/instr −2,5 %. Cono de 128 destinos eliminado |
| A. Consola: lectura de `text_ram` y `palette_ram` adelantada | Nueva | Fmax | **Hecha**: 84,33 MHz, 16/16 semillas cumplen, mediana 81,80 (antes 80,50). ns/instr −0,3 % |
| Registrar la decodificación por dirección en `text_console` | Nueva | Fmax | **Revertida**: 71-75 MHz, 0 semillas cumplen (atacaba el dato equivocado) |
| 5. Registros en el pin (IOLOGIC) | Original | Robustez | Fuera del objetivo, no se ha tocado |
| Endurecer la restricción de frecuencia en el barrido | Nueva | Margen | **Aparcada**: sube la mediana unos 2 MHz, pero el reloj real está fijo a 80 MHz y aún no se sabe cómo fijarlo en un build normal |

## Pendiente

Ninguna cifra de "Potencial" está medida, salvo la proporción de MMIO y de Búsqueda,
que sale de la tabla de reparto de ciclos de la medida de referencia.

| Idea | Origen | Objetivo | Potencial | Riesgo |
| --- | --- | --- | --- | --- |
| 2. Prefetch secuencial en `instruction_buffer` | Original | Fmax y CPI | Poco claro: mantiene la latencia en un ciclo, y el buffer ya no es un cuello (10,56 ns) | Medio |
| 4. Solape de banco en `sdram_controller_128` | Original | Ancho de banda de vídeo/GPU | Solo indirecto sobre el CPI. No sube la frecuencia | Medio |
| **Esconder la espera de búsqueda** (pedir la instrucción siguiente mientras se ejecuta la actual) | Nueva | **CPI** | Cota superior −10 a −14 % (Búsqueda = 14,1 % en Mandelbrot; parte son fallos del buffer) | **Alto**: toca `cpu.v` |
| **Recortar los 2 ciclos extra por acceso MMIO** (`EXTRA_CYCLES`) | Nueva | **CPI** | MMIO pesa 27 % en `pacman` y 28,6 % en `video-registers`. Cuántos de esos ciclos son los 2 añadidos: no medido | Medio: puede costar el cierre a 80 |
| **Quitar `STATE_ALU_WRITE`** (empezando por las lógicas) | Nueva | **CPI** | 1 ciclo menos por instrucción ALU (de 7 a 6). Falta ver si el camino del sumador cabe | Medio |
| Quitar `STATE_DECODE` | Nueva | CPI | 1 ciclo por instrucción, con más riesgo de timing que el anterior | Medio-alto |
| B. Precalcular `loader_range_valid` en la consola | Nueva | Fmax | Ataca 122 destinos de `console_i` (11,2 ns), que ya no dominan | Bajo |
| C. Mux del decoder en AND-OR | Nueva | Fmax | Pequeño, no medido | Bajo |
| D. Espera variable solo para lecturas de consola | Nueva | Fmax | Casi sin coste de CPI, pero cambia el contrato del bus | Medio |
| Arreglos del muro plano: `dmem_adapter.wb_data`, `registers_i.fb_front`, `monitor_i` | Nueva | Fmax | Cada uno tiene de 10 a 128 destinos a 11,3-11,9 ns. Ganancia individual pequeña | Bajo cada uno |

## Orden propuesto

1. Medir cuántos ciclos de MMIO son los 2 añadidos por el bus segmentado (solo lectura).
2. Quitar `STATE_ALU_WRITE` en las instrucciones lógicas.
3. Esconder la espera de búsqueda, cuando haya un análisis previo de `cpu.v`.

## Contexto histórico

El reloj de esta familia se fue bajando según crecía el diseño: 120 → 100 → 80 MHz. A 80,
las carpetas 18, 19 y 21 cierran a 87-89 MHz; la 30, que es la mayor, a 84,33. Un barrido
con el objetivo endurecido (90, 100 y 125 MHz) dio medianas de unos 84 MHz y un mejor de
unos 88,5 en los tres: el techo estructural de este netlist ronda 88 MHz, y por encima
se satura. Ver `docs/resumen-prototipos.md` y `git show 5960ec3`.
