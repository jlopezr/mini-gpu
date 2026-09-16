# MiniGPU: simulador microarquitectónico por ciclos

Implementación en Python del pipeline S/F/I/D/X/W, con una instrucción en
vuelo por warp y finalización en orden **por recurso**. LSU y X progresan
independientemente. W tiene prioridad fija ante colisiones de escritura RF;
un load mantiene su respuesta e `in_flight` hasta escribir el banco.

```powershell
# Desde la raíz del repositorio:
.\tools\test.ps1 --prototype 25 --quick
.\tools\gpusim-cycle.ps1 25.gpu-sim-cycle-uarch/examples/load_store.asm `
  --report 25.gpu-sim-cycle-uarch/reports/load_store.json `
  --trace 25.gpu-sim-cycle-uarch/reports/load_store.jsonl --trace-cycles 100
.\.venv\Scripts\python.exe x.tests/run_tests.py --backend gpu-simulator --version cycle x.tests/cases-gpu/memory
```

En Linux/macOS: `python tools/gpusim-cycle programa.asm`; el lanzador admite
`.asm`, `.bin`, `.hex`, configuración JSON de warps, límites de ciclos e
instrucciones, volcado de memoria y estado arquitectónico. `--help` muestra
las latencias configurables. `--imem-lines 0` activa fetch ideal.

Las pruebas normales incluyen 32 casos GPU existentes, diferencial de ALU
contra MiniCPU, regresiones temporales, colisiones RF, Plasma reducido y
Mandelbrot 16×8. Para repetir un frame **completo** de Plasma:

```powershell
$env:MINIGPU_FULL_PLASMA='1'
$env:MINIGPU_REPORT_DIR='25.gpu-sim-cycle-uarch/reports'
.\tools\test.ps1 --prototype 25 --quick
```

Los dos Mandelbrot completos de la suite original son pruebas largas opcionales
(`MINIGPU_FULL_CONFORMANCE=1`); no se ejecutan en la pasada normal. Los informes
temporales van en `reports/`, ignorado por Git en este repositorio.

Contrato de reloj, semántica de contadores, decisiones y discrepancias:
[DESIGN.md](DESIGN.md). Resultados medidos: [VALIDATION.md](VALIDATION.md).

## Dirección acordada del nuevo pipeline MiniCPU / MiniGPU

La idea es diseñar la nueva microarquitectura de MiniGPU de forma que el **datapath de ejecución de MiniISA pueda reutilizarse posteriormente en MiniCPU**, sin intentar compartir necesariamente toda la lógica de control.

### Pipeline del SM

El punto de partida para MiniGPU será un pipeline:

```text
S → F → I → D → X → W
```

donde `S` es el scheduler de warps. Se mantiene inicialmente la regla de **una sola instrucción en vuelo por warp**. Esto evita dependencias RAW entre instrucciones del mismo warp, ejecución especulativa y la necesidad de forwarding o flushes.

También se mantiene inicialmente **finalización en orden**: una operación larga bloquea las instrucciones posteriores cuando sea necesario, en vez de introducir todavía arbitraje de writeback o ejecución fuera de orden.

### Las lanes dejan de ser pequeñas CPUs

El diseño actual tiene una FSM en el SM y otra FSM dentro de cada `gpu_lane`, consecuencia de haber reutilizado el RTL de MiniCPU.

En el nuevo diseño no se pretende conservar esta estructura.

Las lanes pasan a ser principalmente **datapaths**, y las fases `D`, `X` y `W` del pipeline del SM sustituyen el trabajo que actualmente realizan estados como `DECODE`, `EXECUTE` y `RETIRE` dentro de la FSM de cada lane.

Las unidades que realmente necesiten varios ciclos —por ejemplo división o desplazamientos iterativos— pueden conservar estado interno, pero como **unidades funcionales multiciclo**, no como una segunda FSM de CPU.

### Reutilización con MiniCPU

El objetivo no es compartir el control completo entre CPU y GPU, sino compartir la implementación de la ejecución de MiniISA:

```text
                    ejecución MiniISA
                 D → X → W / datapath
                         ▲
                         │
              ┌──────────┴──────────┐
              │                     │
          MiniCPU                MiniGPU
       control escalar          control SIMT
       hazards/bypass           scheduler
       PC                       warps
                                máscaras/SIMT
```

MiniGPU puede explotar múltiples warps para mantener el pipeline ocupado manteniendo una sola instrucción en vuelo por warp.

MiniCPU, en cambio, necesitará posteriormente permitir varias instrucciones consecutivas dentro del pipeline y resolver los problemas clásicos de una CPU segmentada: RAW, stalls/forwarding y riesgos de control.

Por tanto, se pretende **compartir el datapath y las unidades funcionales MiniISA, no necesariamente las FSM ni la lógica de hazards**.

### Estrategia

Primero se construirá un **simulador cycle-accurate** de esta microarquitectura. Servirá como especificación ejecutable del futuro RTL y permitirá validar funcionalidad, stalls, ocupación del pipeline y CPI antes de implementar el nuevo SM.

La idea central es:

> **Una implementación común de ejecución MiniISA, con dos microarquitecturas de control: escalar para MiniCPU y SIMT para MiniGPU.**
