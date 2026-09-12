# MiniGPU con SDRAM v2: 8 warps × 8 lanes

Copia de `14.fpga-gpu-ram` dedicada a subir la frecuencia máxima sin cambiar la
funcionalidad. El registro de cambios, medidas y caminos críticos está en
`optimizacion.md`; `timing.ps1` resume el informe de temporización tras cada
`check.ps1 Build` y `sweep.ps1` mide el fmax sobre varias semillas, porque una
sola tiene aquí un 17 % de dispersión. Todo lo demás de este documento describe
el diseño heredado.

A su vez copia del RTL de `12.fpga-gpu` con memoria unificada de **32 MiB de SDRAM**
en lugar de los ocho bancos EBR de 128 KiB. Destino: ULX3S-85F,
**25 MHz**, UART **250000 baudios**, monitor **2.2**.

Responde 2.2 y no 2.1 porque comparte todos los comandos con 12: es la versión
la que permite a `x.cpu-tests --version sdram` distinguir este bitstream del de
BRAM, igual que 1.5 y 1.6 separan las dos revisiones de CPU.

Código, LOAD/STORE y monitor comparten `0x00000000–0x01ffffff`.
Las palabras son de 32 bits little-endian, alineadas a cuatro bytes;
la última comienza en `0x01fffffc`. El monitor conserva sus accesos por byte
y las ventanas de configuración/depuración de 12 en `0x80000000` y `0x80000100`.
Los registros de la GPU siguen usando EBR; se sustituye la RAM de código/datos.

## Integración

- `gpu_lane.v` y `gpu_register_file.v` proceden de 12; las etapas de control
  añadidas en `gpu_sm.v` se documentan en `optimizacion.md`.
- `gpu_lsu.v` conserva el contrato vectorial SM↔LSU y los ocho slots de warp.
  Atiende una lane cada vez y rota entre warps después de cada palabra.
  Alterna con el puerto auxiliar de fetch/monitor cuando ambos tienen trabajo.
  Las respuestas vectoriales retenidas no bloquean el fetch.
- `gpu_system.v` conecta el SM, la LSU y el monitor. El monitor accede a memoria
  cuando la GPU está detenida y ha drenado sus operaciones.
- `sdram_controller.v` procede de 10 (idéntico al de 9), parametrizado desde
  `top.v` a 25 MHz. Solo se explicitan extensiones de ancho de contadores para lint.
  Cada palabra requiere dos accesos BL1 de 16 bits; no hay caché ni coalescencia.
  Las máscaras DQM preservan los bytes no escritos por el monitor.
- `top.v` conecta los pines SDRAM usando el LPF de 12, que ya incluía su pinout.

Se esperan `init_done` y la aceptación real de cada petición. Una respuesta STORE
solo se publica después de recibir `done` para ambas mitades de todas las lanes.
Las direcciones desalineadas o fuera de rango generan errores por lane activa.
Una máscara vacía responde sin tocar memoria.

El reset del monitor reinicia la GPU y descarta sus transacciones pendientes,
pero **no reinicia el controlador SDRAM**: continúa el refresco y se conserva RAM.
Una transferencia ya aceptada puede terminar; las escrituras parciales no se
revierten. La siguiente petición espera la disponibilidad del controlador y
no recoge una finalización antigua. El reset global sí inicializa el controlador.

## Uso y comprobaciones

Desde la raíz del repositorio:

```powershell
./17.fpga-gpu-ram-v2/check.ps1 Tests
./17.fpga-gpu-ram-v2/check.ps1 Lint
./17.fpga-gpu-ram-v2/build.ps1 -Label context-pc
.venv/Scripts/python.exe 17.fpga-gpu-ram-v2/monitor.py --help
```

Se conservan los ejemplos, el generador de fixtures y las 32 pruebas diferenciales
contra `11.gpu-sim-func`. Las pruebas de sistema y UART usan el controlador real
con un modelo funcional del bus SDRAM (`sim/sdram_model.vh`). La inicialización
se acorta solo en las pruebas de sistema; el top conserva los 200 µs del controlador.
El modelo verifica datos/direcciones/máscaras, pero no sustituye una prueba física
ni un modelo de temporización del fabricante. Véase `validation.md`.

## Builds con historial de timing

`build.ps1` ejecuta **una sola vez** `apio build --verbose-pnr`. La opción
`--detailed-timing-report` está en `apio.ini`, así que no hace falta volver a
enrutar para obtener el detalle. `check.ps1 Build` utiliza también este script.

La consola muestra el progreso nativo de nextpnr: iteraciones de colocación y
tabla de arcos enrutados, reintentados y pendientes. Los pendientes pueden subir
durante los reintentos; no representan un porcentaje ni una ETA lineales.
La frecuencia tras la colocación es provisional: interesa la final, tras routing.

Cada ejecución conserva `reports/<fecha>-<etiqueta>/` (ignorado por Git):

- `build.log`: salida completa, progreso e histogramas de slack de nextpnr.
- `routing_progress.csv` y `slack_histograms.txt`: esas tablas extraídas del log.
  El histograma usa picosegundos y conserva las cuentas aproximadas del original.
- `hardware.pnr`: JSON con timing detallado por net y caminos críticos.
- `summary.json` y `summary.txt`: frecuencias, recursos, extremos y segmentos
  de los caminos críticos, con retardos de lógica y routing separados.
- `sources.zip` y `metadata.json`: copia de fuentes, hashes, comando y duración.
  Las fuentes se comprimen para que Apio no descubra los LPF archivados como
  constraints adicionales del proyecto.
- Netlist, configuración y bitstream, para conservar la implementación medida.

El historial sobrevive a `apio clean`. No se elimina automáticamente: cada build
conserva también el netlist y puede ocupar decenas de MB o más con timing detallado.
En Apio 1.5.1, **`--verbose-pnr` fuerza el routing incluso sin cambios**; el modo
normal sirve para medir una nueva pasada y ver su progreso. Para aprovechar la
caché sin pedir progreso ni histogramas en el log, utiliza:

```powershell
./17.fpga-gpu-ram-v2/build.ps1 -Label comprobacion -Incremental
```

El JSON detallado sigue habilitado en ambos modos. Cambiar entre modo normal e
incremental también puede invalidar la acción de routing en SCons una vez,
porque cambia la línea de comando. Para archivar sin ejecutar nada, usa
`-ArchiveOnly`.

La comparación con el informe anterior es de una pasada; no sustituye un barrido
de semillas. El script devuelve error si falla Apio, falta el informe/reloj, o
algún dominio no alcanza su constraint (mínimo 25 MHz).

`./17.fpga-gpu-ram-v2/build.ps1 -Label anterior -ArchiveOnly` conserva resultados
existentes sin sintetizar. En este modo la copia de fuentes es la actual y no
demuestra qué fuentes produjeron el informe antiguo.
