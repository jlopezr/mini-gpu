# MiniCPU con SDRAM y monitor UART

> **Backport de `R0` cableado a cero.** Esta carpeta recibio el cambio despues
> de cerrarse: `R0` vale siempre cero y descarta las escrituras, que es una
> regla de la MiniISA y no una extension opcional. Ver
> [`1.isa/isa.md`](../1.isa/isa.md) seccion 1.
>
> **Este monitor responde ahora 3.10.** Subio con el renumerado a juego de comandos (mayor) y numero de carpeta (menor), sin cambiar
> ni un byte del protocolo: es lo unico que el PC puede preguntar para saber que
> bitstream tiene delante, y un programa que use `R0` como registro general no
> para con error en el bitstream viejo, da otro resultado en silencio.
>
> El texto que sigue es anterior al backport. Los numeros de version que
> menciona mas abajo son historicos; los de hoy estan en
> [`resumen-prototipos.md`](../docs/resumen-prototipos.md).
>
> Y un aviso que salio al probar esta carpeta con el backport: **la 10 no
> implementa `MUL`, `MULFX` ni `DIV`.** Es un hueco anterior a todo esto y el
> unico core al que le pasa: son instrucciones BASE de la ISA, la 6 --que es
> previa-- las tiene y la 16 --posterior-- tambien.
>
> Se probo el port, que es literalmente copiar el `cpu.v` de la 6 porque
> resulto ser un superconjunto estricto de este. Funciona: las cinco suites
> pasan a la primera. Lo que no pasa es la temporizacion --de SEIS de ocho
> semillas cumpliendo 120 MHz a UNA, al +2,4%-- y bajar el reloj arrastraria el
> baudio, porque 120 MHz / 40 = 3 Mbaud exacto y a 100 MHz el divisor saldria
> 33,33. El razonamiento completo esta en [`cpu.v`](cpu.v).
>
> **Ese segundo argumento ya no vale**: el reloj bajo a 100 MHz igualmente, por
> `WRITE_WORD`, y el baudio con el —a 1 Mbaud—. Si alguien quiere reabrir el
> port de MUL/DIV, lo que tiene que medir es el barrido de HOY, no aquel.
>
> Lo que si se hizo fue **quitar los tres `localparam`**: el `cpu.v` los
> declaraba y validaba su encoding sin implementarlos, o sea que aparentaba
> soportarlos. `x.tests` lo declara ahora como la capacidad `mul_div`, que
> esta es la unica version en no tener, y `cases/alu/multiply` se omite aqui con
> un SKIP en vez de fallar.


Este proyecto integra la MiniCPU de `6.fpga-cpu` con el controlador SDRAM de
`9.fpga-ram-param`. Todo el datapath principal funciona en un único dominio de
**100 MHz** —fueron 120 hasta el 18/09/2026, ver
[`pll_100.v`](pll_100.v)—. El monitor UART conserva los comandos de ejecución y
depuración de la carpeta 6, responde como versión **1.5** y trabaja a **1
Mbaud**. Esa versión
permite que `x.tests --version sdram` distinga este bitstream SDRAM del
bitstream EBR 1.4.

## Mapa de memoria

La CPU y el monitor ven el mismo espacio físico unificado de 32 MiB:

| Recurso | Dirección global |
|---|---:|
| SDRAM | `0x00000000`–`0x01ffffff` |

Los puertos `imem`, `dmem` y monitor utilizan esas direcciones sin sumar bases
ni seleccionar implícitamente una mitad. Como convención común, el programa
empieza en `0x00000000`, los datos básicos en `0x00100000` y la región desde
`0x01000000` queda disponible para gráficos, pero el hardware no impone esas
funciones. Un `LOAD` puede leer código y el fetch puede ejecutar cualquier
palabra alineada de la SDRAM.

Las instrucciones y los accesos `LOAD`/`STORE` deben estar alineados a cuatro
bytes. Una palabra de CPU se realiza mediante dos operaciones SDRAM BL1 de 16
bits, en orden little-endian. No se utilizan bursts todavía.

El monitor es propietario de la SDRAM mientras la CPU está detenida. Durante
la ejecución, los comandos de memoria del monitor reciben `ff`. La CPU es
multiciclo y no presenta a la vez una petición de instrucciones y otra de
datos, aunque el frontend da prioridad explícita al fetch.

## Uso

```powershell
python monitor.py write-block 0 fpga_smoke_test.bin --port COM3
python monitor.py verify 0 fpga_smoke_test.bin --port COM3
python monitor.py reset --port COM3
python monitor.py run --port COM3
python monitor.py status --port COM3
```

Prueba destructiva de SDRAM, por ejemplo sobre 128 KiB:

```powershell
python monitor.py memory-test 0 0x20000 --port COM3
```

`memory-test` escribe y verifica cuatro patrones (`00`, `ff`, dirección XOR
`a5` y `55/aa`). La CPU debe estar detenida y el contenido del intervalo se
sobrescribe. CPU y monitor usan exactamente la misma dirección para
inspeccionar cualquier dato.

## Verificación

```powershell
apio test sdram_system_adapter_tb.v
apio test cpu_sdram_system_tb.v
apio test cpu_tb.v
apio test monitor_tb.v
apio test sdram_controller_tb.v
apio build
```

`cpu_sdram_system_tb.v` comprueba el flujo completo: carga mediante el puerto
del monitor, fetch desde SDRAM, `STORE`, `LOAD` y `HALT`.

La explicación detallada de registros, rutas críticas y latencias está en
[`timing.md`](docs/timing.md).

## Timing

El place-and-route actual alcanza **130,67 MHz** para una restricción de
120 MHz. Las operaciones ALU registran primero su resultado en
`STATE_ALU_WRITE`, por lo que `ADD`, `SUB`, `AND`, `OR`, `XOR` y sus variantes
inmediatas tardan un ciclo adicional. Esta etapa evita que el sumador termine
directamente en la entrada de escritura del banco de registros.

La recepción de bloques del monitor también separa captura de longitud,
cálculo de la dirección final y validación. Esos ciclos son despreciables
frente al tiempo de transmisión UART y evitan una ruta combinacional desde el
byte recibido hasta el siguiente estado del monitor.
