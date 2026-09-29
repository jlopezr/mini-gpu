# Temporización de la MiniCPU con SDRAM

Este documento describe los registros introducidos para integrar la MiniCPU,
el monitor UART y la SDRAM en un único dominio de reloj de 120 MHz. No se ha
añadido un pipeline de instrucciones: la CPU continúa siendo multiciclo y solo
ejecuta una instrucción cada vez.

## Resultado

El periodo disponible a 120 MHz es aproximadamente 8,33 ns. El
place-and-route final obtiene:

| Magnitud | Resultado |
|---|---:|
| Frecuencia requerida | 120,00 MHz |
| Frecuencia alcanzada | 130,67 MHz |
| `TRELLIS_COMB` | 4.976 |
| `TRELLIS_FF` | 2.249 |
| `DP16KD` | 0 |

Las cifras corresponden a una ejecución concreta de nextpnr y pueden variar
ligeramente con cambios de lógica o colocación. `apio build` utiliza
`--timing-allow-fail`, por lo que siempre debe comprobarse que no aparece el
aviso `FAIL at 120.00 MHz` aunque se genere un bitstream.

## Frontera UART-monitor

`top.v` genera el reset posterior al PLL con un registro de desplazamiento de
16 ciclos. Esto evita que la detección combinacional del final de un contador
alimente directamente la red de reset de alto fanout. El controlador SDRAM
mantiene después su propio tiempo de inicialización JEDEC.

`top.v` registra `uart_rx_data` y `uart_rx_strobe` antes de entregarlos al
monitor. El byte y su strobe se retrasan juntos un ciclo, por lo que el
protocolo no cambia.

```text
UART RX -> monitor_rx_data / monitor_rx_strobe -> monitor
```

El adaptador captura por separado la dirección, el dato y el tipo de petición
del monitor. `STATE_VALIDATE_MONITOR` comprueba el rango en el ciclo siguiente
y solo entonces prepara la solicitud SDRAM. Así la comparación de los siete
bits altos no queda encadenada con los registros de dirección y datos SDRAM.

Esta frontera evita que el desplazador de recepción UART y la máquina de
estados completa del monitor formen una sola ruta combinacional.

El puerto de memoria del monitor también está registrado en ambas direcciones:

```text
monitor -> registros de petición -> adaptador SDRAM
monitor <- registros de respuesta <- adaptador SDRAM
```

La UART es varios órdenes de magnitud más lenta que el reloj interno, por lo
que estos ciclos adicionales no afectan de forma apreciable al rendimiento
del enlace.

## Validación registrada de transferencias por bloques

La primera integración validaba el último byte de la longitud, el rango y el
final de la transferencia en el mismo ciclo:

```text
rx_data -> longitud -> suma dirección+longitud -> comparación -> estado
```

Esta fue la ruta crítica inicial. Además, la comprobación todavía contenía los
dos rangos de 16 KiB usados por las EBR de `6.fpga-cpu`, en lugar del rango
físico completo de la SDRAM.

El monitor divide ahora el trabajo en tres estados:

```text
STATE_BLOCK_LENGTH_LOW
    captura el byte bajo y la longitud completa

STATE_CALCULATE_BLOCK_END
    registra mem_address + block_length

STATE_VALIDATE_BLOCK
    comprueba longitud, dirección inicial y dirección final
```

El intervalo válido del monitor es `0x00000000`–`0x01ffffff`. La dirección
final es exclusiva: una transferencia de un byte iniciada en `0x01ffffff`
termina en `0x02000000` y es válida.

Al registrar la suma, `rx_data` deja de atravesar el sumador y la lógica de
siguiente estado en un único periodo. Los dos ciclos añadidos son
insignificantes comparados con la recepción de un byte UART a 3 Mbaud.

## Resultado ALU registrado

Después de corregir el monitor, la ruta crítica pasó a la CPU:

```text
operand_a -> sumador ADDI -> register_write_data
```

El resultado alcanzaba 119,15 MHz, muy cerca pero todavía por debajo del
objetivo. `cpu.v` incorpora ahora los registros `alu_result` y
`alu_destination` y el estado `STATE_ALU_WRITE`:

```text
STATE_EXECUTE   : operandos -> ALU -> alu_result
STATE_ALU_WRITE : alu_result -> puerto de escritura del banco
STATE_RETIRE    : retirada de la instrucción
```

Se aplica a estas operaciones:

- `ADD`, `SUB`, `AND`, `OR`, `XOR`;
- `ADDI`, `ANDI`, `ORI`, `XORI`.

Estas instrucciones tardan un ciclo más, pero su semántica y el protocolo de
retirada no cambian. `MOVI`, `MOVHI`, `GETTID`, branches, desplazamientos y
operaciones de memoria conservan sus caminos específicos.

En el test aislado de CPU, las operaciones ALU registradas pasan de seis a
siete ciclos contados desde `STATE_FETCH_REQUEST` hasta `STATE_RETIRE`. La
latencia de los accesos SDRAM continúa siendo variable y queda gobernada por
el contrato `valid/ready`.

## Adaptador SDRAM y protocolo `valid/ready`

`sdram_system_adapter.v` convierte cada acceso CPU de 32 bits en dos accesos
SDRAM BL1 de 16 bits. La palabra se ensambla en orden little-endian. `imem`,
`dmem` y el monitor usan directamente el mismo rango físico
`0x00000000–0x01ffffff`; ya no existe selección implícita de una mitad según
el puerto que originó la petición.

Después de activar `ready`, el adaptador entra en `STATE_RELEASE` y espera a
que el propietario retire `valid`. Esto impide aceptar dos veces una misma
petición cuando emisor y receptor actualizan sus registros en el mismo flanco.

## Comprobación

Las regresiones relevantes son:

```powershell
apio test cpu_tb.v
apio test sdram_system_adapter_tb.v
apio test cpu_sdram_system_tb.v
apio test monitor_tb.v
apio test sdram_controller_tb.v
apio build
```

`cpu_tb.v` comprueba el ciclo adicional de las instrucciones ALU.
`cpu_sdram_system_tb.v` comprueba el flujo carga por monitor, fetch desde
SDRAM, `STORE`, `LOAD` y `HALT`.
