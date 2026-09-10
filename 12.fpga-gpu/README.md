# MiniGPU FPGA: 8 warps × 8 lanes

Un SM para ULX3S-85F, con 64 threads residentes, 8 lanes físicas y memoria
unificada de 128 KiB. Incluye SIMT, LSU con ocho operaciones de warp pendientes,
monitor UART y pruebas contra `11.gpu-sim-func`.

El primer objetivo es una implementación multiciclo funcional a **25 MHz**.
No emite una instrucción en cada ciclo. La UART de esta versión usa **250000
baudios**, con divisor exacto para transmisión y recepción. El monitor se
identifica como **2.1** para distinguirlo del monitor escalar a 3 Mbaud.

## Organización

- `gpu_sm.v`: scheduler round-robin, PC y máscaras por warp, pila SIMT,
  workgroups, barreras, carga de contextos y arbitraje de escritura de registros.
- `gpu_lane.v`: máquina de estados de `6.fpga-cpu/cpu.v`, con PC de lanzamiento,
  thread ID y banco de registros externos. `derive_lane.py` reproduce la adaptación.
  Se conservan el multiplicador por productos parciales, divisor iterativo,
  shifter iterativo, decodificación y comparaciones del core.
- `gpu_register_file.v`: 256 registros de 32 bits por lane; 32 registros por
  warp, con dos lecturas síncronas. R0 es escribible. Un barrido de 256 ciclos
  inicializa los registros sin implementar el almacenamiento como flip-flops.
- `gpu_lsu.v`: ocho slots de warp, arbitraje de bancos y ensamblado de respuestas.
- `gpu_bram.v`: ocho bancos físicos de 4096 × 32 bits, con dos puertos.
- `gpu_system.v`: conexión entre SM, LSU, memoria, monitor y ventana de control.
- `top.v`, `monitor.v`, `uart.v`, `util.v`: integración física y monitor.

El fetch es único por instrucción de warp. La instrucción se distribuye a las
lanes activas, cuyos datapaths conservan su control multiciclo. No se instancian
64 CPUs ni se duplica la memoria de programa por lane.

Una instrucción aritmética ocupa las lanes hasta que todas las lanes activas
terminan. Una instrucción de memoria deposita su vector en la LSU y libera las
lanes para otro warp. Cada warp espera a su propia respuesta antes de emitir
otra instrucción; los demás warps listos siguen ejecutando. Las respuestas de
LOAD escriben el contexto de su warp en una frontera entre instrucciones,
evitando conflictos con la escritura aritmética.

La LSU puede aceptar **8 operaciones de warp, hasta 64 accesos de lane**, con
una operación pendiente por warp. Son capacidad de almacenamiento y concurrencia,
no una promesa de 64 accesos físicos simultáneos. En cada ronda se elige un warp y
se atiende una lane por banco; después se rota al siguiente warp pendiente.
Las colisiones de un warp se resuelven en varias rondas. Los ocho bancos pueden
aceptar en paralelo, pero la lógica de selección, respuesta y rotación añade ciclos.
Esta primera LSU espera a terminar la ronda antes de lanzar otra.

## Memoria y futuro backend SDRAM

| Propiedad | Valor |
|---|---|
| Direcciones válidas | `0x00000000–0x0001ffff` |
| Tamaño | 128 KiB, compartidos por código y datos |
| Banco | `address[4:2]` |
| Fila dentro del banco | `address[16:5]` |
| Palabra | 32 bits, little-endian, alineación de 4 bytes |
| Última palabra | `0x0001fffc` |
| Monitor | Accesos por byte; también permite leer y escribir código |

El puerto A de cada banco atiende a la LSU. El puerto B atiende fetch o monitor.
El monitor accede a memoria y configuración cuando la GPU está detenida y la
LSU ha terminado todas sus operaciones. Los accesos durante ejecución se rechazan.
RESET conserva RAM y reinicializa registros y control; aborta las transacciones
pendientes, sin revertir escrituras que ya hayan ocurrido.

La frontera preparada para SDRAM es **SM ↔ LSU**, documentada en
[`memory-interface.md`](memory-interface.md): petición vectorial y respuesta
independientes con `valid/ready`, tag de warp y error por lane, sin latencia fija.
Un backend SDRAM podrá sustituir `gpu_lsu`/`gpu_bram` conservando esos puertos del
SM. No se ha conectado aún el controlador SDRAM de `10.fpga-cpu-ram`.
El límite de 128 KiB y la selección por banco pertenecen a esta implementación
BRAM y deben cambiarse al añadir SDRAM. El fetch también tiene handshakes separados.

LOAD/STORE mantienen el orden dentro de cada warp. `BAR` espera también a las
operaciones de memoria anteriores de los warps participantes. No hay cachés.
El orden entre warps depende de disponibilidad; los programas con carreras no
tienen por qué reproducir el orden round-robin instantáneo del simulador.
Para modificar código desde la GPU, completar las escrituras y sincronizar con
BAR antes de ejecutarlo. Una lectura y escritura simultáneas de la misma palabra
por puertos distintos tienen resultado de lectura no especificado.

## SIMT e ISA

Implementa la ISA del simulador: NOP, MOVI, MOVHI, ADD, SUB, MUL, MULFX, DIV,
AND/OR/XOR, SHL/SHR/SAR, ADDI/ANDI/ORI/XORI, LOAD, STORE, los seis saltos
condicionales, BRA, GETTID, SSY, BAR, EXIT, TRAP y HALT.
GETTID devuelve `warp_id * 8 + lane_id`.

Cada warp tiene PC, `active_mask`, `live_mask`, workgroup de 32 bits y dos
pilas SIMT independientes: **8 regiones y 8 caminos** por defecto.
`SIMT_REGION_DEPTH` y `SIMT_PATH_DEPTH` son parámetros de `gpu_sm` y
`gpu_system`; `SIMT_DEPTH` se conserva como valor por defecto de la profundidad
de regiones para compatibilidad.

SSY abre una región con su PC de apertura, join, máscara original y base de
caminos. Repetir el SSY de la región más interna la reutiliza sin perder lanes
aparcadas ni caminos pendientes, incluso con la pila de regiones llena.
Un SSY distinto abre otra región aunque comparta join. Cambiar el destino de
un SSY reutilizado produce error SIMT.

Una región admite varias divergencias. Si ninguno de los destinos es el join,
se ejecuta primero el fall-through y se apila el camino tomado. Si un destino
es el join, sus lanes se aparcan sin ocupar un camino y continúa el otro destino.
La reconvergencia consume los caminos de la región en orden LIFO antes de
restaurar su máscara original filtrada por `live_mask`.

EXIT y HALT retiran las lanes activas y nunca las reactivan. Al terminar las
últimas lanes se vacían ambas pilas y se conserva el PC siguiente a EXIT/HALT.
La normalización también termina antes de una pausa STEP/HALT y no incrementa
el contador de instrucciones retiradas. Véase la
[semántica compartida](../11.gpu-sim-func/ssy-reusable-regions-design.md).

BAR exige que estén activas todas las lanes vivas del warp. Participan los warps
vivos de su workgroup y deben coincidir en PC y generación de barrera. Un warp
terminado deja de participar. No hay timeout automático para un programa cuyos
warps vivos nunca lleguen a la barrera; el monitor puede solicitar HALT.

El primer error observado se conserva y se deja de emitir trabajo. La memoria
ya aceptada se drena. **No hay rollback ni commit atómico de ocho lanes**:
pueden quedar registros o memoria parcialmente actualizados. RUN/STEP se rechazan
tras un error; RESET permite empezar de nuevo. Los códigos 01–05 son los del
core; 06 corresponde a SIMT/pila y 07 a barrera inválida. El diagnóstico incluye
PC, warp y lane cuando corresponde. No se conserva la dirección efectiva fallida.

## Lanzamiento y monitor

Tras reset, los **8 warps** tienen **PC=0**, **máscara=0xff** y **workgroup=0**.
La GPU queda detenida al terminar de inicializar registros. RUN empieza o
reanuda la ejecución; después de finalizar todas las lanes hace falta RESET o
reconfiguración para relanzarlas. STEP emite una instrucción de un warp elegido
por el scheduler y espera a que termine su memoria antes de quedar detenido.
HALT solicitado por el monitor conserva los contextos para reanudar.

Desde esta carpeta, con el bitstream de esta versión cargado:

```powershell
../.venv/Scripts/python.exe monitor.py write-block 0 examples/vector.bin --port COM3
../.venv/Scripts/python.exe monitor.py reset --port COM3
../.venv/Scripts/python.exe monitor.py run --port COM3
../.venv/Scripts/python.exe monitor.py status --port COM3
../.venv/Scripts/python.exe monitor.py read-register 5 --warp 3 --lane 5 --port COM3
../.venv/Scripts/python.exe monitor.py registers --warp 3 --lane 5 --port COM3
../.venv/Scripts/python.exe monitor.py registers --all --port COM3
../.venv/Scripts/python.exe monitor.py read-block 0x1000 256 output.bin --port COM3
```

El ejemplo escribe los valores `100..163` en las 64 palabras desde `0x1000`,
y cada thread lee de vuelta su valor en R5. Warp 3/lane 5 devuelve 129.
`examples/simt.asm` ejercita divergencia anidada y BAR; en R3 quedan
`12,12,22,22,31,31,31,31` por warp.

Para un lanzamiento específico, cargar primero el programa y después:

```powershell
../.venv/Scripts/python.exe monitor.py configure launch.example.json --port COM3
../.venv/Scripts/python.exe monitor.py run --port COM3
../.venv/Scripts/python.exe monitor.py warp-status --port COM3
```

`configure` usa la validación JSON del simulador, reinicia registros y programa
los ocho slots; los omitidos se deshabilitan. No modifica la RAM ni ejecuta RUN.
Admite PC, active_mask, enabled y workgroup_id por warp. El hardware tiene ocho
lanes fijas; workgroup_id debe caber en 32 bits. `warp-status` requiere parada.
`registers` muestra los 32 registros del lane elegido en una tabla compacta;
con `--all` recorre los 8 warps y sus 8 lanes. La GPU debe estar parada.

## Ventana de control del monitor

No forma parte de la memoria de la ISA: solo es accesible desde el monitor.
Las palabras de control se transfieren little-endian mediante READ/WRITE_BYTE
o READ/WRITE_BLOCK. La dirección del comando UART conserva el formato big-endian
del monitor anterior. `READ_REG` lee el contexto seleccionado.

| Dirección | Contenido |
|---|---|
| `0x80000000 + 16*w` | PC del warp, lectura/escritura |
| `0x80000004 + 16*w` | Lectura: active[7:0], live[15:8]. Escribir el byte bajo fija ambas máscaras |
| `0x80000008 + 16*w` | workgroup_id, lectura/escritura |
| `0x8000000c + 16*w` | Solo lectura: regiones [7:0], caminos [15:8], WAIT_MEM bit 16, WAIT_BAR bit 17 |
| `0x80000100` | Selección: lane[2:0], warp[5:3] |
| `0x80000104` | Slots LSU ocupados [7:0], solo lectura |
| `0x80000108` | Instrucciones de warp retiradas, contador de 32 bits |
| `0x8000010c` | lane[2:0], warp[5:3], lane_valid bit 6, error_code[15:8] |
| `0x80000110` | PC del primer error |
| `0x80000114` | Instrucciones retiradas del warp seleccionado en `0x80000100` |

El monitor 2.1 distingue las regiones reutilizables y añade el contador por warp.
RESET borra todos los contadores; reconfigurar un warp borra su contador local,
sin modificar el contador global. Reconvergencia y liberación de BAR no cuentan
como instrucciones adicionales.

Modificar la configuración de un warp borra ambas pilas y estado de barrera. Para
reanudar un programa pausado sin alterar SIMT, usar RUN sin reconfiguración.
El acceso directo por bytes no valida de forma transaccional un lanzamiento;
para ello usar `configure`, que valida el JSON antes de escribir.

## Verificación

```powershell
./check.ps1 -Action Tests
./check.ps1 -Action Lint
./check.ps1 -Action Build
```

`Tests` regenera las referencias con el simulador funcional y ejecuta Apio.
Los testbenches tienen watchdog y `$fatal` ante discrepancias:

- `gpu_system_tb.v`: 32 programas diferenciales, todos los 2048 registros,
  PC finales y 512 palabras de datos por caso. Incluye memoria unificada y código
  modificado tras BAR, límites de RAM, conflictos, aritmética y SIMT.
- `gpu_lsu_tb.v`: ocho slots llenos, colisiones, errores de dirección, ocho
  bancos aceptando simultáneamente, backend lento y backpressure en ambos sentidos.
- `gpu_scheduler_tb.v`: ocho LOAD pendientes; progreso de un warp aritmético
  mientras los otros siete esperan; escritura de respuestas en el contexto correcto.
- `gpu_regions_tb.v`: capacidades independientes, overflow, reutilización con la
  pila llena, prioridad de errores y normalización durante STEP.
- `gpu_control_tb.v`: errores de ISA, memoria, división, pila y barreras;
  STEP, HALT/RUN, rechazo de memoria del monitor en ejecución y reset sin borrar RAM.
- `gpu_uart_tb.v`: ruta serie completa desde los pines de `top`, incluyendo
  carga del programa, lanzamiento por defecto y lectura por warp/lane.

[`validation.md`](validation.md) registra el resultado de simulación y de la
implementación física. Generar un bitstream no sustituye comprobar timing;
Apio puede permitir un fallo de timing durante place-and-route.

## Suite en placa

Desde la raíz del repositorio:

```powershell
.\.venv\Scripts\python.exe .\x.cpu-tests\run_gpu_tests.py --backend gpu-fpga --version bram --port COM3 --yes --durations
```

El runner requiere monitor 2.1 y carga el proyecto cuando la placa responde con
otra versión. Ejecuta 26 casos GPU compatibles y explica los 8 omitidos por
capacidades; véase [el runner](../x.cpu-tests/README.md).
