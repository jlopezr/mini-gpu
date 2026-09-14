# AGENTS.md

Infraestructura común del repositorio en `tools/`: resolución de prototipos, gestión de builds
(fondo/estado/logs/limpieza), lanzadores de simuladores/tests, informes y documentación generada.

**Tutorial completo con ejemplos: [`tools/README.md`](tools/README.md).** Léelo antes de escribir
un comando nuevo o de invocar algo a mano — es muy probable que ya exista un lanzador.

## Lo esencial para trabajar en este repo

```bash
export PATH="$PWD/tools:$PATH"
```

- `--prototype` acepta número, nombre completo o ruta (`resolve_prototype` en `tools/prototype.py`);
  usa `list-prototypes` si no recuerdas el nombre exacto de una carpeta.
- Para builds largos (síntesis FPGA), usa `build --prototype N --background` + `build-status`/`build-log --follow`
  en vez de bloquear una llamada a herramienta esperando a que termine. `build`/`build-sweep`/`test`
  son genéricos (cualquier prototipo con `apio.ini`), no hace falta copiar nada a su carpeta.
- `x.tests` (antes `x.cpu-tests`) tiene los backends de placa/simulador y el runner de casos
  (`run_tests.py`, antes `run_gpu_tests.py`); no dupliques esa lógica en `tools/`, solo añade
  lanzadores finos que la invoquen.
- `docs/resumen-prototipos.md` y `docs/mapa-de-memoria.md` están escritos a mano con mucho cuidado — no los
  regeneres ni los edites en bloque; `generate-docs` solo toca contenido entre marcadores
  `<!-- BEGIN/END GENERATED -->` que ya existan.
- La identidad de un prototipo (CPU/GPU, versión de monitor, reloj, capacidades) se lee del RTL
  directamente (`cpu.v`/`gpu_sm.v`, `monitor.v`, el PLL, `tools/capabilities.json`) — no hay
  ningún fichero central que registrar al añadir un prototipo. Ver `tools/prototype_report.py`.

## Estado y huecos conocidos

Implementado: resolución de prototipos, gestor de builds, lanzadores de simuladores, `run-tests`,
`build`/`test`/`lint`/`build-sweep` genéricos para cualquier prototipo con `apio.ini` (los cuatro
con `--background`, seguibles con `build-status`/`build-log`), `check` (los encadena y para en el
primer fallo), `list-prototypes`, `prototype-report`, `generate-docs`,
`run-board`/`board-info`/`board-upload`/`board-load` (reutilizan `x.tests/backends/board.py`;
`run-board` es la composición de los otros tres). Todos los lanzadores tienen `.ps1` para Windows,
y ninguno tiene lógica propia salvo `interface-diagram.ps1` (experimental, fuera de este sistema).
`seed-sweep.ps1` se retiró: lo sustituye `build-sweep`. `check.ps1` en 12/14/17 delega en
`test`/`lint`/`build` en vez de duplicar su lógica.

No queda ningún hueco de infraestructura pendiente en `tools/`. Detalle en
[`tools/README.md`](tools/README.md).
