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

| Magnitud | Resultado |
|---|---:|
| Frecuencia requerida | 120,00 MHz |
| Frecuencia alcanzada | 126,09 MHz |
| EBR `DP16KD` | 16 |
| Flip-flops `TRELLIS_FF` | 1767 |
| Celdas lógicas `TRELLIS_COMB` | 3687 |

Estas cifras pertenecen a una ejecución concreta de nextpnr. El resultado
puede variar ligeramente con cambios de lógica o colocación, por lo que el
margen debe revisarse después de modificaciones relevantes.

## Propiedad de las memorias

`memory_map.v` contiene una única pareja de memorias físicas:

| Memoria | Dirección del monitor | Dirección local de la CPU | Tamaño |
|---|---:|---:|---:|
| Programa | `0x00000000` | `0x00000000` | 16 KiB |
| Datos | `0x00100000` | `0x00000000` | 16 KiB |

La diferencia de direcciones de datos es deliberada. La CPU tiene dos espacios
Harvard independientes que comienzan en cero; el monitor necesita un único
espacio global y utiliza `0x00100000` para distinguir la RAM de datos.

La propiedad se decide con `cpu_halted`:

```text
cpu_halted = 1  -> el monitor puede leer y escribir ambas memorias
cpu_halted = 0  -> la CPU lee programa y ejecuta LOAD/STORE sobre datos
```

Un comando de memoria recibido mientras la CPU ejecuta termina con
`RSP_ERROR`. Así no existen dos escritores ni se cambia una instrucción a
mitad de su ejecución.

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

`register_b_address` se calcula y registra al aceptar la instrucción de memoria.
Cuando llega `STATE_DECODE`, la dirección del segundo puerto ya es estable y no
incluye decodificación de opcode en su ruta de datos. Este cambio llevó el
resultado final a 126,09 MHz.

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
