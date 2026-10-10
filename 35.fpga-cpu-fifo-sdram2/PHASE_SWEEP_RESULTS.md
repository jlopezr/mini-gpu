# Barrido dinámico de fase de la SDRAM

Fecha del experimento: 2026-10-10. Prototipo: `35.fpga-cpu-fifo-sdram2`,
ULX3S ECP5-85F con SDRAM de 16 bits.

## Objetivo

Separar los fallos de SDRAM causados por la relación temporal entre el reloj
externo y los datos de los causados por la implantación de una semilla concreta.
Para ello se añadió una salida `CLKOS` de 100 MHz al PLL de memoria y se barrió
su fase en tiempo de ejecución, sin cambiar la fase de `CLKOP`, que sigue siendo
la realimentación fija del PLL.

El PLL ECP5 ofrece 48 posiciones por vuelta. Con VCO a 600 MHz, cada paso
equivale aproximadamente a 208,33 ps. El controlador utiliza exclusivamente
retrasos (`PHASEDIR=0`), porque el avance puede introducir glitches.

## Implementación probada

- `pll_mem.v` mantiene `CLKOP` fijo y genera `sdram_clk` mediante `CLKOS`.
- `pll_phase_ctl.v` implementa los pulsos del protocolo dinámico, posición
  módulo 48, guardas y reinicialización exclusiva del controlador SDRAM.
- `phase_mmio.v` cruza la petición por toggle y devuelve posición Gray y estado
  sincronizado. El bloque experimental local ocupa `0x8002_0000`.
- Mientras se cambia la fase se impiden peticiones nuevas y se espera a que el
  tráfico anterior haya drenado. Después se reinicia solamente el controlador
  SDRAM y se espera de nuevo a `init_done`.
- `monitor.py` incorpora `phase-status` y `phase-step`.
- `phase_sweep.py` programa varios bitstreams, recorre las 48 posiciones,
  conserva resultados parciales y genera JSONL, JSON, CSV y Markdown.

No se modificó la lógica interna de `sdram_controller_128.v`.

## Metodología

Se probaron las semillas 1, 2, 3, 4 y 10. Las cinco cumplen timing con las
mismas opciones de `nextpnr` (`--tmg-ripup` y
`--placer-heap-timingweight 30`).

En cada una de las 48 fases se probaron 64 KiB desde `0x0010_0000`, con dos
repeticiones de estos cuatro patrones:

1. `0x00`.
2. `0xff`.
3. Byte de dirección XOR `0xa5`.
4. Alternancia `0x55/0xaa`.

Eso supone 512 KiB escritos y 512 KiB leídos por fase, aproximadamente 120 MiB
en cada sentido para el conjunto de cinco semillas. La CPU permaneció parada.
La zona probada se sobrescribe deliberadamente.

## Resultados

| Semilla | CPU conseguida | Memoria conseguida | Fases válidas |
|---:|---:|---:|:---|
| 1  | 82,75 MHz | 103,38 MHz | 2–18 |
| 2  | 82,38 MHz | 102,40 MHz | 0–18 |
| 3  | 81,14 MHz | 104,05 MHz | 2–17 |
| 4  | 81,73 MHz | 100,99 MHz | 1–18 |
| 10 | 82,74 MHz | 105,94 MHz | 2–17 |

La intersección válida de las cinco implantaciones es **2–17**, equivalente a
unos **+417 ps a +3542 ps**. Los bordes se desplazan uno o dos pasos según la
semilla, pero la zona central es estable.

La fase estática original, posición 0, es marginal: pasa con la semilla 2,
pero falla con 1, 3, 4 y 10. Fuera de la ventana aparecen desde unos pocos
errores cerca del borde hasta cientos de miles en el centro de la región mala.
Esto descarta que el síntoma sea solamente un CDC interno o una semilla mala y
señala como causa dominante la relación de fase del reloj externo de SDRAM.

## Decisión recomendada

El centro geométrico de la ventana común está entre las fases 9 y 10. Se
recomienda usar **fase 10**, unos **+2083 ps**, como valor fijo común para todas
las semillas. La fase 12, usada durante las primeras pruebas, también está
dentro de la ventana de todas las implantaciones, pero queda menos centrada.

La selección no debe hacerse por semilla: conviene mantener un valor común y
conservar el barrido dinámico como herramienta experimental para comprobar
margen en futuros cambios de RTL, placa, frecuencia o constraints.

## Artefactos

- `reports/20261010-phase-sweep-full.{json,jsonl,csv,md}`: semillas 2, 3, 4 y 10.
- `reports/20261010-phase-sweep-seed1.{json,jsonl,csv,md}`: semilla 1.
- `reports/20261010-phase-sweep-smoke.*`: validación corta del automatismo.
- `reports/20261010-014518-480446-phase-runtime-check2/`: síntesis base y
  barridos de implantación.

El respaldo previo `reports/20261010-seed10-rf-ram-buena/` no se modificó.

## Reproducción

Ejemplo para dos bitstreams; se pueden repetir argumentos `--bitstream` para
añadir más semillas:

```powershell
.\.venv\Scripts\python.exe 35.fpga-cpu-fifo-sdram2\phase_sweep.py `
  --port COM3 `
  --bitstream "seed3=RUTA\seed-3\hardware.bit" `
  --bitstream "seed10=RUTA\seed-10\hardware.bit" `
  --length 0x10000 `
  --repetitions 2 `
  --restore-phase 10 `
  --output 35.fpga-cpu-fifo-sdram2\reports\phase-sweep `
  --yes
```

Sin `--yes` el script se niega a programar. `--dry-run` valida rutas y muestra
el plan sin abrir el puerto serie.
