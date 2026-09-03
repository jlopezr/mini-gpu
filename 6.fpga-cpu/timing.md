# Temporización e integración de la MiniCPU

Este documento explica los registros añadidos al integrar la MiniCPU, el
monitor UART y las dos memorias EBR. No son un pipeline de instrucciones: la
CPU continúa ejecutando una sola instrucción cada vez mediante una máquina de
estados multiciclo.

## Objetivo

La placa trabaja con un reloj de 120 MHz generado por `pll_120.v`. El periodo
disponible para cada ruta síncrona es aproximadamente 8,33 ns.

La primera integración funcional alcanzaba solamente 75,28 MHz. Las
simulaciones pasaban porque una simulación RTL comprueba el comportamiento, no
los retardos físicos del FPGA. Además, `apio build` utiliza
`--timing-allow-fail`, por lo que puede generar un bitstream aunque nextpnr
muestre `FAIL at 120.00 MHz`. Hay que leer siempre la frecuencia indicada por
nextpnr.

Después de registrar las rutas descritas aquí, el place-and-route obtuvo:

| Magnitud                      |  Resultado |
|-------------------------------|-----------:|
| Frecuencia requerida          | 120,00 MHz |
| Frecuencia alcanzada          | 122,97 MHz |
| EBR `DP16KD`                  |         16 |
| Flip-flops `TRELLIS_FF`       |       1970 |
| Celdas lógicas `TRELLIS_COMB` |       4603 |

Estas cifras pertenecen a una ejecución concreta de nextpnr. El resultado
puede variar ligeramente con cambios de lógica o colocación, por lo que el
margen debe revisarse después de modificaciones relevantes.

## Propiedad de las memorias

`memory_map.v` contiene una única pareja de memorias físicas:

| Banco | Dirección global | Tamaño |
|-------|-----------------:|-------:|
| EBR 0 | `0x00000000–0x00003fff` | 16 KiB |
| EBR 1 | `0x00100000–0x00103fff` | 16 KiB |

CPU y monitor presentan esas mismas direcciones. Un router registrado dirige
cada petición `imem`, `dmem` o del monitor al banco seleccionado; ambos puertos
de CPU pueden llegar a ambos bancos. Los huecos producen error de bus.

La propiedad se decide con `cpu_halted`:

```text
cpu_halted = 1  -> el monitor puede leer y escribir ambas memorias
cpu_halted = 0  -> la CPU lee programa y ejecuta LOAD/STORE sobre datos
```

Un comando de memoria recibido mientras la CPU ejecuta termina con
`RSP_ERROR`. Así no existen dos escritores ni se cambia una instrucción a
mitad de su ejecución.

`RESET_CPU` reinicia solamente PC, registros y estado de control. No aplica
reset a `memory_map` ni borra las EBR, de modo que un test puede volver a
ejecutar el programa ya cargado.

## Registro de operandos

El banco de registros conserva dos puertos de lectura combinacionales. En la
implementación inicial, una instrucción `ADD` recorría en un solo ciclo:

```text
registro de instrucción -> decodificación -> mux 32:1 del banco
                         -> sumador de 32 bits -> registro de resultado
```

Esa fue la ruta crítica de 75,28 MHz. El estado `STATE_DECODE` captura
`operand_a` y `operand_b` antes de entrar en `STATE_EXECUTE`:

```text
STATE_DECODE   : banco de registros -> operand_a / operand_b
STATE_EXECUTE  : operandos registrados -> ALU -> resultado
```

Se añade un ciclo por instrucción, pero no se solapan instrucciones. Por eso es
una CPU multiciclo sin pipeline.

## Selección del segundo operando

En MiniISA, `ADD` obtiene el segundo operando del campo `Rb`, mientras que
`STORE` utiliza el campo `Rd` como registro fuente. Una selección combinacional
entre ambos campos delante del mux 32:1 volvió a formar una ruta larga.

`register_a_address` y `register_b_address` se calculan y registran al aceptar
la instrucción de memoria.
Cuando llega `STATE_DECODE`, la dirección del segundo puerto ya es estable y no
incluye decodificación de opcode en su ruta de datos. En aquella versión este
cambio elevó el resultado a 126,09 MHz; las cifras vigentes para el diseño
completo están en la tabla inicial.

## Registro de las solicitudes a EBR

Las señales de entrada de cada EBR no proceden directamente del arbitraje. Los
registros `program_request_*` y `data_request_*` capturan:

- propietario de la memoria;
- dirección de palabra;
- dato y byte enables de escritura;
- habilitación de lectura.

Esto separa en dos ciclos la selección y el acceso físico:

```text
CPU/monitor -> arbitraje y validación -> registros de solicitud
registros de solicitud -> EBR
```

Sin esta frontera, la validación de dirección y el mux CPU/monitor formaban
parte del camino hasta `CEA`, el clock enable interno de `DP16KD`.

## Registro de las salidas EBR

La salida `DOA` de una EBR tiene un retardo clock-to-output significativo. No
conviene conectarla en el mismo ciclo a toda la lógica de selección y escritura
de la CPU.

Las respuestas destinadas a la CPU pasan por:

- `routed_cpu_imem_read_data` y `routed_cpu_imem_ready`;
- `routed_cpu_dmem_read_data`, `routed_cpu_dmem_ready` y
  `routed_cpu_dmem_error`.

El monitor también registra por separado las palabras procedentes de programa
y datos. La selección entre ambas se realiza después de esos registros. Esto
evita la ruta:

```text
DOA de programa/datos -> mux de memoria -> selección de byte -> monitor
```

La señal `ready` se retrasa junto con el dato. Por tanto, el consumidor nunca
observa una respuesta antes de que el dato registrado sea válido.

## Puerto de depuración del banco de registros

La CPU necesita lecturas rápidas para ejecutar instrucciones, pero el monitor
UART no necesita una lectura combinacional inmediata. El puerto de depuración
registra primero la dirección y después el dato:

```text
ciclo 1 -> debug_address_registered
ciclo 2 -> debug_data
```

El monitor espera esos ciclos en `STATE_WAIT_REGISTER_1` y
`STATE_WAIT_REGISTER_2` antes de construir la respuesta `READ_REGISTER`. Los
dos puertos utilizados por la CPU siguen siendo combinacionales.

## Latencia y protocolo `valid/ready`

Los registros anteriores aumentan la latencia, pero no cambian el contrato:

1. el emisor presenta dirección, operación y `valid`;
2. mantiene esas señales mientras espera;
3. el receptor registra la solicitud y accede a la EBR;
4. registra el dato de salida;
5. activa `ready` con el dato válido;
6. la CPU consume la respuesta y retira la instrucción cuando corresponde.

La CPU no presupone una latencia fija. Esto permite añadir registros o sustituir
la EBR por una memoria más lenta sin modificar la semántica de `LOAD`, `STORE`
o del fetch de instrucciones.

## Desplazamientos iterativos

`SHL`, `SHR` y `SAR` desplazan un bit por ciclo. Un barrel shifter combinacional
de 32 bits elevó notablemente el uso de LUT y provocó congestión suficiente para
perder el cierre de timing a 120 MHz. La unidad iterativa conserva el operando,
el tipo y un contador de cinco bits; tarda entre cero y 31 ciclos internos antes
de escribir el resultado. La instrucción se retira una sola vez y la semántica
arquitectónica no cambia.

## Branches registrados

Los branches condicionales usan campos de registro distintos a las operaciones
R-type. Sus dos direcciones de lectura se resuelven al aceptar la instrucción,
antes de `STATE_DECODE`. En `STATE_EXECUTE` se registran por separado el
destino relativo y una resta común de 33 bits. `STATE_BRANCH_COMPARE` deriva de
esa resta igualdad, signo o borrow, y `STATE_BRANCH_COMMIT` modifica después el
PC. Esta separación evita que seis comparadores independientes formen una red
de 10 ns y también evita encadenar comparación, suma del offset y escritura del
PC dentro de un solo periodo de reloj.

## Ciclos por instrucción en la FPGA

La siguiente tabla cuenta desde `STATE_FETCH_REQUEST` hasta
`STATE_RETIRE`, ambos incluidos. Incluye la latencia real del camino registrado
de la EBR de programa usado por `memory_map.v`. Un ciclo a 120 MHz dura unos
8,33 ns.

| Familia de instrucciones                                 |   Ciclos | Tiempo aproximado |
|----------------------------------------------------------|---------:|------------------:|
| `NOP`, `HALT`                                            |        9 |           75,0 ns |
| `ADD`, `SUB`, `AND`, `OR`, `XOR`                         |        9 |           75,0 ns |
| `MOVI`, `ADDI`, `ANDI`, `ORI`, `XORI`, `MOVHI`, `GETTID` |        9 |           75,0 ns |
| `BRA`                                                    |       10 |           83,3 ns |
| `BEQ`, `BNE`, `BLT`, `BGE`, `BLTU`, `BGEU`               |       11 |           91,7 ns |
| `LOAD`, `STORE` con la EBR actual                        |       14 |          116,7 ns |
| `SHL`, `SHR`, `SAR` con desplazamiento `n`               | `10 + n` |     83,3–341,7 ns |

En los shifts, `n = Rb[4:0]`, por lo que varía entre 0 y 31. Las latencias de
`LOAD` y `STORE` son las de la memoria EBR integrada actual; la interfaz
`valid/ready` permite sustituirla por una memoria de latencia distinta. El
router unificado añade un registro tras cada salida EBR: una instrucción normal
gana un ciclo y `LOAD`/`STORE` ganan dos, uno en fetch y otro en datos.

`cpu_memory_map_tb.v` mide estas latencias sobre el camino usado en la FPGA,
las imprime como `FPGA CYCLES` y falla si cambian accidentalmente. `cpu_tb.v`
también mide el núcleo con su modelo simplificado de memoria de instrucciones:

| Familia                 | Ciclos en `cpu_tb.v` |
|-------------------------|---------------------:|
| Instrucción ordinaria   |                    6 |
| `BRA`                   |                    7 |
| Branch condicional      |                    8 |
| Shift de `n` posiciones |              `7 + n` |

Estas cifras describen latencia, no throughput: no hay instrucciones solapadas
porque la CPU todavía no tiene pipeline.

## Parada y diagnóstico de errores

La MiniCPU no implementa vectores de excepción, handlers ni reanudación. Un
error coloca `halted = 1`, `error = 1`, guarda la causa en `error_code` y hace
que el PC observable vuelva a la dirección de la instrucción causante. Durante
fetch el PC ya se ha incrementado en cuatro, por lo que las rutas de error de
`STATE_EXECUTE` y `STATE_MEMORY_WAIT` realizan `pc <= pc - 4`.

Esta elección evita añadir un registro `error_pc` y evita cambiar el tamaño de
la respuesta `GET_STATUS`: el monitor existente devuelve directamente el PC
útil para diagnóstico. `HALT` es distinto; se retira normalmente y detiene la
CPU con `error = 0`. `TRAP` no se retira y detiene la CPU con el código `0x03`.

La comprobación de campos reservados se calcula a partir del registro de
instrucción y se captura en `instruction_encoding_valid_registered` durante
`STATE_DECODE`. `STATE_EXECUTE` consume únicamente ese bit registrado. La
primera implementación conectaba la validación combinacional directamente al
control de ejecución y el place-and-route bajó a 119,01 MHz. Registrar el
resultado recuperó el cierre de timing. La cifra vigente figura al inicio.

Los errores definidos son:

| Código | Causa |
|-------:|-------|
| `0x01` | Opcode reservado, desconocido o todavía no implementado |
| `0x02` | Acceso de memoria inválido |
| `0x03` | Instrucción `TRAP` explícita |
| `0x04` | División por cero; se usará al implementar `DIV` en FPGA |
| `0x05` | Opcode conocido con campos reservados distintos de cero |

Las rutas de error terminan antes de `STATE_RETIRE`, por lo que la instrucción
problemática no activa `instruction_retired`. El testbench comprueba además que
`TRAP`, opcode inválido y encoding inválido conservan el PC causante.

## Cómo verificarlo

Prueba del flujo compartido completo:

```powershell
apio test cpu_memory_map_tb.v
```

Regresiones principales:

```powershell
apio test cpu_tb.v
apio test cpu_program_system_tb.v
apio test register_file_tb.v
apio test monitor_tb.v
```

Implementación física:

```powershell
apio build
```

Hay que comprobar que nextpnr no imprima una advertencia `FAIL at 120.00 MHz`.
El testbench `cpu_memory_map_tb.v` verifica además el flujo:

```text
monitor carga programa -> RUN -> CPU ejecuta LOAD/STORE -> HALT
                        -> monitor lee el resultado
```
