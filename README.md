# mini-gpu

Proyecto educativo para construir una GPU sencilla desde cero, comenzando por
una ISA y una CPU escalar verificable. El repositorio avanza mediante etapas
independientes: modelos de Mandelbrot, ensamblador, simulador funcional,
bring-up de la ULX3S, monitor UART, CPU en FPGA y memoria SDRAM externa.

El diseño más completo está actualmente en
[`10.fpga-cpu-ram`](10.fpga-cpu-ram): una MiniCPU multiciclo conectada al
monitor UART y a los 32 MiB de SDRAM de la ULX3S, con cierre de timing a
120 MHz.

## Recorrido del repositorio

| Carpeta                                            | Contenido                                                                |
|----------------------------------------------------|--------------------------------------------------------------------------|
| [`0.mandelbrot`](0.mandelbrot)                     | Modelos de referencia float y Q16.16, comparación y visor de resultados. |
| [`1.isa`](1.isa)                                   | Especificación MiniISA, ensamblador y programas iniciales.               |
| [`2.cpu-sim-func`](2.cpu-sim-func)                 | Simulador funcional de MiniCPU y sus pruebas.                            |
| [`3.fpga`](3.fpga)                                 | Bring-up mínimo de la ULX3S mediante un LED.                             |
| [`4.fpga-uart`](4.fpga-uart)                       | UART a 3 Mbaud y ejemplo serie sobre FPGA.                               |
| [`5.fpga-monitor`](5.fpga-monitor)                 | Monitor UART con una memoria EBR de 16 KiB.                              |
| [`6.fpga-cpu`](6.fpga-cpu)                         | MiniCPU, monitor y memorias EBR de programa y datos.                     |
| [`7.ulx3s_w9825g6kh_test`](7.ulx3s_w9825g6kh_test) | Prueba autónoma inicial de la SDRAM a 25 MHz.                            |
| [`8.fpga-ram`](8.fpga-ram)                         | SDRAM accesible mediante el monitor UART a 25 MHz.                       |
| [`9.fpga-ram-param`](9.fpga-ram-param)             | Controlador SDRAM parametrizado y monitor a 120 MHz.                     |
| [`10.fpga-cpu-ram`](10.fpga-cpu-ram)               | Integración de CPU, monitor UART y SDRAM a 120 MHz.                      |
| [`x.cpu-tests`](x.cpu-tests)                       | Casos comunes para simulador y distintas versiones FPGA.                 |
| [`pruebas`](pruebas)                               | Artefactos históricos conservados como referencia.                       |

Las carpetas numeradas representan hitos de aprendizaje y se conservan aunque
una etapa posterior sustituya parte de su implementación. No debe asumirse que
la carpeta con el número más alto reemplaza la documentación técnica de las
anteriores.

## Arquitectura actual

```text
                            UART 3 Mbaud
PC ───────────────────────────────┐
                                  ▼
                         monitor / depuración
                                  │
                           arbitraje de memoria
                                  │
MiniCPU ── imem 32 bits ──────────┤
        └─ dmem 32 bits ──────────┤
                                  ▼
                         adaptador 32 → 16
                                  │
                         SDRAM 32 MiB, 120 MHz
```

La CPU conserva puertos separados para instrucciones y datos, pero ambos usan
el mismo mapa global que el monitor. La versión EBR implementa dos ventanas de
16 KiB en `0x00000000` y `0x00100000`; la versión SDRAM respalda directamente
todo `0x00000000–0x01ffffff`. No existen traslaciones ocultas de direcciones.

## Requisitos

- Python 3.10 o posterior;
- dependencias de [`requirements.txt`](requirements.txt): Pillow, APIO y
  pyserial;
- toolchain ECP5 instalada mediante APIO para sintetizar los proyectos FPGA;
- ULX3S-85F para las pruebas físicas.

Preparación habitual en PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
apio install
```

## Primeros pasos

Ejecutar todos los casos sobre el simulador:

```powershell
cd x.cpu-tests
python run_cpu_tests.py --backend sim
```

Ejecutarlos sobre la CPU con EBR de la carpeta 6:

```powershell
python run_cpu_tests.py --backend fpga --version ebr --port COM3
```

Ejecutarlos sobre la CPU con SDRAM de la carpeta 10:

```powershell
python run_cpu_tests.py --backend fpga --version sdram --port COM3
```

El backend consulta `GET_VERSION` antes de modificar la memoria. La versión
EBR responde como monitor 1.6 y la versión SDRAM como 1.5. Las revisiones
anteriores 1.2 y 1.3 corresponden al mapa con traducción de direcciones.

## Construcción del diseño actual

Desde `10.fpga-cpu-ram`:

```powershell
apio test cpu_tb.v
apio test sdram_system_adapter_tb.v
apio test cpu_sdram_system_tb.v
apio test monitor_tb.v
apio test sdram_controller_tb.v
apio build
```

Aunque APIO puede generar un bitstream con `--timing-allow-fail`, hay que
comprobar siempre que nextpnr no muestre `FAIL at 120.00 MHz`. Los detalles de
latencia y rutas registradas están en
[`10.fpga-cpu-ram/timing.md`](10.fpga-cpu-ram/timing.md).

## Estado y alcance

MiniISA, el ensamblador y el simulador implementan más operaciones que la CPU
RTL. La tabla vigente de instrucciones está en
[`6.fpga-cpu/instruction-status.md`](6.fpga-cpu/instruction-status.md). La CPU
FPGA actual es multiciclo, sin pipeline de instrucciones ni ejecución SIMT;
la evolución hacia MiniGPU sigue siendo trabajo futuro.

Las decisiones de diseño generales están recogidas en
[`1.isa/proyecto.md`](1.isa/proyecto.md) y las tareas abiertas en
[`TODO.md`](TODO.md).
