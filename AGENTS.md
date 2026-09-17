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
- `docs/resumen-prototipos.md` y `docs/mapa-de-memoria.md` están escritos a mano: edítalos como
  cualquier otro texto del repo, pero **respeta los marcadores `<!-- BEGIN/END GENERATED -->`**.
  `generate-docs` sobrescribe lo que haya entre ellos —lo que escribas ahí dentro se pierde— y no
  toca nada fuera. Lo que no hay que hacer es regenerarlos enteros, no editarlos.
- La identidad de un prototipo (CPU/GPU, versión de monitor, reloj, capacidades) se lee del RTL
  directamente (`cpu.v`/`gpu_sm.v`, `monitor.v`, el PLL, `tools/capabilities.json`) — no hay
  ningún fichero central que registrar al añadir un prototipo. Ver `tools/prototype_report.py`.
- Identidad en toda carpeta con juego de comandos; dispositivos donde haya algo que mapear.
  `SYS_ID` también existe en 6 y 10, por el camino del monitor: no necesitan una ventana
  MMIO de periféricos para identificarse.
- No añadas scripts de build o check dentro de un prototipo: `build`/`test`/`lint`/`check` ya son
  genéricos para cualquier carpeta con `apio.ini`, y los que había se retiraron por redundantes.
  La única excepción, deliberada, es `13.hdmi/check_timing.ps1`: 13 no es un prototipo sino una
  prueba independiente multi-env, y ese script barre semillas y las fija en su `apio.ini`.
- Cada lanzador tiene su `.ps1` para Windows y ninguno lleva lógica propia, salvo
  `interface-diagram.ps1` (experimental, fuera de este sistema).
