# LCC optimization audit probes

Material reproducible de análisis para `docs/lcc-optimization-audit.md`.
No forma parte del compilador ni modifica MiniABI.

## Contenido

| Ruta | Qué es |
|---|---|
| `probes/*.c` | Los 11 casos: `args8`, `arrays_escape`, `calls`, `control`, `leaf`, `locals`, `opt_patterns`, `pressure`, `recursive`, `volatile`, `wide`. |
| `measure.py` | Compila cada probe con `rcc`, lo ensambla, lo pasa por `mini-opt` (`mini_opt.optimize`) y lo ejecuta en el simulador funcional de CPU, antes y después. Comprueba que `R1` coincide. |
| `metrics.csv` | Una fila por caso: instrucciones estáticas y dinámicas (sin y con `mini-opt`), accesos a memoria y a pila, marco máximo, guardados de callee-saved y llamadas. |
| `out/*.s`, `out/*.opt.s` | El ensamblador generado por lcc y su versión optimizada. Es lo que cita la auditoría y se lee sin compilar nada. `out/*.bin` y `out/*.i` no se versionan. |

La tabla de la sección 11 de la auditoría sale de `metrics.csv`. «Mem» cuenta
loads y stores de datos (no el fetch de instrucciones); «pila» cuenta los que
usan R30 como base. El simulador funcional no modela ciclos, así que no hay
cifras de ciclos.

## Regenerar

Necesita `cl` y el `rcc` de 32 bits (`y.lcc/build/rcc.exe`), en la misma
llamada, como la suite de `y.lcc`:

```powershell
.\y.lcc\build-mini.ps1 rebuild          # dentro de vcvars32.bat
python analysis\lcc-audit\measure.py
```

Escribe `out/` y `metrics.csv` y hace fallar la ejecución si la salida
optimizada cambia el resultado.

## Estado de los datos

`metrics.csv` y `out/*.s` son la **línea base de la auditoría** (9 de octubre
de 2026, superproyecto `192dca5`, `y.lcc` `895f564`), anterior a la promoción
de locales a temporales en hojas (`mini.md:local`) y a la LICM de cargas.
Volver a ejecutar `measure.py` sobrescribe esa línea base con lo que genera el
compilador actual: las cifras de la sección 11 de la auditoría y los
fragmentos de ensamblador que cita dejarían de coincidir con los ficheros.
Para medir el compilador actual conviene hacerlo en una copia, o actualizar a
la vez la auditoría.

La medida del compilador actual sobre toda la suite (166 casos) no sale de
aquí sino de `tools/mini-lcc-test.ps1 --simulate --compare-optimizer`:
23.601 → 19.980 instrucciones (−15,3 %, con `invert`, `boolean`, `deadsaves` y `forward`).
