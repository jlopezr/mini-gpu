# Tests de Python de la infraestructura

Los `test_*.py` de `x.tests`, uno por módulo o herramienta que prueban, agrupados por tema. No son casos (esos están
en `cases-*` y los ejecuta `run_tests.py`): son pruebas de las herramientas, los backends, los simuladores y los
generadores, casi todas sin placa. Los tests de cada simulador viven junto a él (`2.cpu-sim-func`, `11.gpu-sim-func`,
`25.*`, `32.*`, `1.isa`...).

| Carpeta | Qué prueba | Tests |
|---|---|---|
| [backends](backends/) | Los backends de placa (`board`, `fpga-sys`, `fpga-gpu`), la parada por vídeo, `run-board`, el puerto serie y el protocolo del monitor | `board`, `gpu_core`, `gpu_fpga`, `video_stop`, `run_board`, `monitor_port`, `monitor_protocol` |
| [runner](runner/) | `run_tests.py`: capacidades, el modo diferencial, los generadores de datos, el reparto en procesos, la selección de versiones y `record_case.py` | `capabilities`, `differential`, `data_generators`, `gpu_runner`, `run_tests_parallel`, `run_tests_prototype`, `record_case` |
| [input](input/) | INPUT (teclado y ratón, mmio §25): el dispositivo, los guiones, el adaptador y su reproducción en placa | `sim_input`, `sim_input_script`, `board_input`, `board_script`, `input_adapter`, `input_board_script`, `host_input`, `input_vectors` |
| [sim](sim/) | Los simuladores funcionales: consola, pantalla, periféricos, `HALT_AT`, identidad (`SYSTEM_ID`) | `sim_console`, `sim_display`, `sim_interactive`, `sim_peripherals`, `sim_peripheral_cli`, `sim_video_halt`, `sysid_device` |
| [debugger](debugger/) | `mini-dbg`, con CPU sola y con CPU + GPU | `debugger`, `debugger_system` |
| [compiler](compiler/) | `mini-opt` y el arranque `crt0` | `mini_opt`, `crt0` |
| [build](build/) | Síntesis y RTL: `build`, los barridos de semillas, el muro de timing, el cableado de los tops, los informes, los fixtures y las identidades generadas | `build_report`, `build_runner`, `sweep_*`, `timing_wall`, `top_wiring`, `prototype_*`, `fixtures_report`, `make_rtl_fixtures`, `fullframe_fixture`, `sysid_params`, `test_all`, `test_runner` |
| [measure](measure/) | Medidas en placa: la tabla, el archivo, los contadores de rendimiento, el informe y `capture-frames` | `measure`, `measure_archive`, `perf_counters`, `perf_report`, `video_tools` |
| [tools](tools/) | Herramientas sueltas: trazabilidad, pantalla, el mapa MMIO, las fuentes de la consola y la referencia del fuego | `traceability`, `screen`, `mmio_map`, `fire_reference`, `font_patch`, `make_font` |

## Cómo se ejecutan

Todos los tests son paquetes (`unit/<tema>/test_*.py`) y se descubren desde `x.tests`, que tiene que estar en el
`sys.path` para que se encuentren `run_tests` y `backends`. La raíz del repo también (por `tools`):

```powershell
run-tests --quick                                   # todos (unos 50 s), desde cualquier carpeta
run-tests --quick --verbose

cd x.tests                                          # solo uno, o una carpeta
$env:PYTHONPATH = ".."                              # (la raíz del repo; `run-tests` ya lo pone)
python -m unittest unit.compiler.test_mini_opt
python -m unittest discover -s unit/debugger -t . -p "test_*.py"
python -m unittest discover -s unit -t . -p "test_sim_*.py"
```

`-t .` es lo que pone `x.tests` en el path; sin él, `discover -s unit/debugger` no encuentra los módulos como
paquetes.

## Al añadir un test

Va en la carpeta de lo que prueba, con `__init__.py` si es una carpeta nueva. Un test que necesite la raíz del
repo la saca de `Path(__file__).resolve().parents[3]` (`<tema>` → `unit` → `x.tests` → raíz). Si usa un fixture de
otro test, lo importa como paquete: `from unit.input.test_board_input import FakeBoard`.
