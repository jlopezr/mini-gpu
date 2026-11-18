# mini-gpu

Proyecto educativo para construir una GPU sencilla desde cero, comenzando por
una ISA y una CPU escalar verificable. El repositorio avanza mediante etapas
independientes: modelos de Mandelbrot, ensamblador, simulador funcional,
bring-up de la ULX3S, monitor UART, CPU en FPGA y memoria SDRAM externa.

![MiniGPU](./1.isa/minigpu.png)

El repositorio incluye CPU y GPU funcionales y RTL, sistemas integrados y
una CPU segmentada con FP32 en
[`38.fpga-cpu-pipelined`](38.fpga-cpu-pipelined/README.md). La integración
CPU/GPU se desarrolla en [`37.fpga-cpu-gpu-mk2`](37.fpga-cpu-gpu-mk2/README.md)
y en el [simulador integrado](32.cpu-gpu-func-sim/README.md). El estado de
capacidades, timing y pruebas en placa se consulta en cada prototipo y en el
[resumen de implementaciones](docs/resumen-prototipos.md).

**`R0` cableado a cero es la única corrección que ha tenido la MiniISA**, frente
a un puñado de extensiones que son aditivas. No es opcional ni depende de la
carpeta: lo deben cumplir todas las implementaciones conformes y sus simuladores.
El backport corrigió los diseños históricos y actualizó sus versiones de monitor. Está en [`1.isa/isa.md`](1.isa/isa.md) §1.

La diferencia con una extensión importa: las demás se detectan solas, porque un
bitstream que no las tenga para con opcode inválido. Con `R0` general no hay
parada, hay otro resultado en silencio, y por eso no podía convivir con su
ausencia en el resto del repositorio.

**[`docs/resumen-prototipos.md`](docs/resumen-prototipos.md) pone en una tabla qué sabe hacer cada
implementación, cuánta memoria ve y a qué frecuencia cierra.** Es lo que evita
tener que abrir cinco `README.md` para saber si una instrucción está en un
bitstream concreto.

## Principios de diseño

MiniCPU y MiniGPU comparten la ISA escalar; la GPU añade ejecución SIMT, con
registros por thread, máscaras y planificación de warps. La ISA define el
comportamiento visible del programa; pipeline, latencias, lanes físicos y
scheduler pertenecen a la microarquitectura. Primero se valida el resultado
funcional contra un modelo de referencia y después se miden ciclos, área y
frecuencia. Cada etapa debe poder contrastarse con la anterior. La claridad y
la trazabilidad guían las optimizaciones, manteniendo explícitas las capabilities.

Mandelbrot es el workload conductor inicial: sus modelos float y Q16.16 permiten
separar el error de cuantización de un fallo de implementación. El
[flujo de validación y formato .iter](0.mandelbrot/README.md#flujo-de-validación)
está documentado junto a los modelos.

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
| [`11.gpu-sim-func`](11.gpu-sim-func)               | Simulador funcional de la MiniGPU: un SM, varios warps y SIMT.           |
| [`12.fpga-gpu`](12.fpga-gpu)                       | Un SM sobre FPGA, con 64 threads residentes y 8 lanes en EBR.            |
| [`13.hdmi`](13.hdmi)                               | Salida DVI/TMDS sobre los pares GPDI, de donde sale la cadena de vídeo.  |
| [`14.fpga-gpu-ram`](14.fpga-gpu-ram)               | El SM de 12 con memoria unificada sobre 32 MiB de SDRAM.                 |
| [`15.isa-v2`](15.isa-v2)                           | Solo documentación: arquitectura de la GPU, plan por fases y 3D.         |
| [`16.fpga-cpu-hdmi`](16.fpga-cpu-hdmi)             | CPU con SDRAM más salida HDMI y doble framebuffer con swap en vblank.    |
| [`17.fpga-gpu-ram-v2`](17.fpga-gpu-ram-v2)         | Copia de 14 dedicada a subir la frecuencia sin cambiar funcionalidad.    |
| [`18.fpga-cpu-hdmi-bl8`](18.fpga-cpu-hdmi-bl8)     | La 16 con el camino de memoria en ráfagas BL8 y contadores de ciclos.    |
| [`19.fpga-cpu-hdmi-ls`](19.fpga-cpu-hdmi-ls)       | La 18 más accesos de 8 y 16 bits, llamadas y puerto serie MMIO.         |
| [`20.forth`](20.forth)                             | Un Forth con intérprete y compilador, sobre la consola serie de la 19.   |
| [`21.fpga-cpu-hdmi-alu`](21.fpga-cpu-hdmi-alu)     | La 19 más `MULHI`/`DIVU`/`REM`/`REMU`, shifts inmediatos y `R0` a cero.  |
| [`t.tests`](t.tests)                       | Casos comunes para simulador y distintas versiones FPGA.                 |
| [`u.lcc`](u.lcc)                                   | Submodulo del compilador C experimental lcc con backend MiniISA.         |
| [`pruebas`](pruebas)                               | Artefactos históricos conservados como referencia.                       |

Las carpetas numeradas representan hitos de aprendizaje y se conservan aunque
una etapa posterior sustituya parte de su implementación. No debe asumirse que
la carpeta con el número más alto reemplaza la documentación técnica de las
anteriores.

Dentro de cada una, la documentación de apoyo vive en `docs/` y los programas en
`examples/`, de forma que en la raíz de la carpeta solo queda el `README.md`
junto al código. Las dos carpetas de ISA —[`1.isa`](1.isa) y
[`15.isa-v2`](15.isa-v2)— son la excepción: ahí los `.md` no acompañan a un
código, son el contenido.

`tools/check-links.py` comprueba que los enlaces relativos de todos los `.md`
apuntan a algo que existe, que es lo que evita que mover un fichero deje
referencias colgando:

```powershell
.venv/Scripts/python.exe tools/check-links.py
```

## Arquitectura CPU con SDRAM (prototipo 10)

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
el mismo mapa global que el monitor. La versión EBR implementa dos bancos de
16 KiB contiguos, `0x00000000–0x00007fff`; la versión SDRAM respalda directamente
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
python tools/setup
apio install
```

`tools/setup` instala `requirements.txt` y, si `uv` está disponible, PyPy (`uv python install pypy@3.11`), que
acelera el simulador.

## Primeros pasos

Ejecutar todos los casos sobre el simulador:

```powershell
cd t.tests
python run_tests.py --backend sim-cpu
```

Inicializar el compilador C experimental MiniISA/lcc:

```bash
git submodule update --init --recursive u.lcc
```

Ejecutar su validacion compilando y simulando los tests de `mini-lcc`:

```bash
mkdir -p u.lcc/build
python3 u.lcc/run-mini-tst.py --simulate
# o, con tools/ en PATH:
mini-lcc-test
```

La idea es usar ese submodulo para generar programas `.asm`, `.bin` o `.json`
desde C y reutilizarlos despues en la validacion de simuladores y RTL.
La ABI canonica de Mini-GPU esta en [`1.isa/abi.md`](1.isa/abi.md).

Para ejecutar esos casos desde la infraestructura de `t.tests`:

```bash
python3 t.tests/run-mini-lcc-tests.py --backend sim-cpu
```

Ejecutarlos sobre la CPU con EBR de la carpeta 6:

```powershell
python run_tests.py --backend fpga-cpu --version ebr --port COM3
```

Ejecutarlos sobre la CPU con SDRAM de la carpeta 10:

```powershell
python run_tests.py --backend fpga-cpu --version sdram --port COM3
```

El backend consulta `GET_VERSION` antes de modificar la memoria. La versión EBR
responde como monitor 3.6 y la versión SDRAM como 3.10: el mayor es el juego de
comandos y el menor, el número de carpeta. Ver
[`docs/resumen-prototipos.md`](docs/resumen-prototipos.md).

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
[`10.fpga-cpu-ram/timing.md`](10.fpga-cpu-ram/docs/timing.md).

## Estado y alcance

El repositorio contiene CPU y GPU, modelos funcionales y de ciclos, diseños
multiciclo y segmentados, y sistemas CPU/GPU con memoria y periféricos compartidos.
Cada backend ofrece un subconjunto explícito de capabilities; el número de
carpeta no basta para inferir soporte ni validación en placa.

La [ISA vigente y sus ampliaciones compatibles](1.isa/isa.md) se mantienen
separadas de la [propuesta v0.4](1.isa/propuesta-v0.4.md), cuyo encoding aún
no está implementado. El [índice vigente](1.isa/isa.md#3-mapa-de-opcodes), el
[resumen de prototipos](docs/resumen-prototipos.md) y los README de cada etapa
indican soporte y validación. Las tareas abiertas están en [`TODO.md`](TODO.md).
