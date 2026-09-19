# MiniCPU con memorias EBR

> **Backport de `R0` cableado a cero.** Esta carpeta recibio el cambio despues
> de cerrarse: `R0` vale siempre cero y descarta las escrituras, que es una
> regla de la MiniISA y no una extension opcional. Ver
> [`1.isa/isa.md`](../1.isa/isa.md) seccion 1.
>
> **Este monitor responde ahora 3.6.** Subio con el renumerado a juego de comandos (mayor) y numero de carpeta (menor), sin cambiar
> ni un byte del protocolo: es lo unico que el PC puede preguntar para saber que
> bitstream tiene delante, y un programa que use `R0` como registro general no
> para con error en el bitstream viejo, da otro resultado en silencio.
>
> El texto que sigue es anterior al backport. Los numeros de version que
> menciona mas abajo son historicos; los de hoy estan en
> [`resumen-prototipos.md`](../docs/resumen-prototipos.md).


Integración de la MiniCPU multiciclo, el monitor UART y dos memorias EBR de
16 KiB. Es la versión FPGA `ebr` utilizada por `x.tests` y responde como
monitor 3.6. Esta revisión implementa `MUL`, `MULFX` y `DIV`. `MUL` conserva
los 32 bits bajos; `MULFX` opera en signed Q16.16 mediante cuatro productos
parciales de 16 bits, y `DIV` usa un divisor signed iterativo de 32 pasos.

Mapa unificado visible por la CPU y el monitor:

| Banco          |        Dirección global |
|----------------|------------------------:|
| EBR 0          | `0x00000000–0x00003fff` |
| EBR 1          | `0x00004000–0x00007fff` |
| Huecos y resto |            error de bus |

Los puertos `imem` y `dmem` pueden acceder a cualquiera de los dos bancos.
Así, un `LOAD` puede leer código, un `STORE` puede modificarlo y el fetch puede
ejecutar desde la EBR 1. Normalmente el programa se carga en la EBR 0 y los
datos se colocan en la EBR 1.

El monitor controla ambas memorias mientras la CPU está detenida. Durante la
ejecución, la CPU lee instrucciones y realiza `LOAD`/`STORE`; los accesos de
memoria del monitor se rechazan.

## Temporización: 100 MHz, con el margen justo

El diseño corría a 120 MHz y **la semilla de nextpnr decidía si cumplía**: de
ocho, cerraban cuatro. Con `WRITE_WORD` dentro del monitor no cierra ninguna
—barrido de 85,92 a 99,40 MHz—, así que **desde el 18/09/2026 va a 100 MHz**,
como ya hicieron la 16 (120 → 100) y la 18 (100 → 80) cuando les pasó lo mismo.
Ver [`pll_100.v`](pll_100.v) y [`../docs/unificacion-mmio.md`](../docs/unificacion-mmio.md).

A 100 cumple **una** semilla de ocho: la 4, con 104,41 MHz (+4,4 %), y es la que
fija `apio.ini`. Sigue siendo el caso en que la semilla decide si el diseño
funciona, no cuánto margen sobra, así que **cualquier cambio de RTL obliga a
rebarrer**. Esto es distinto del 15, donde la semilla sólo elige margen porque
todas cumplen.

Bajar el reloj arrastró el baudio: 120/40 daban 3 Mbaud exactos y a 100 MHz no
hay divisor que los dé. El puerto queda en **1 Mbaud** con divisor 100, el mismo
que 16, 18, 19 y 21.

El camino crítico que queda no está en la CPU ni en el monitor, sino en
`mem_address → sysid_ready → memory_map_i.release_wait`: 1,2 ns de lógica y más
de 4 de rutado. Esta carpeta ocupa el 7 % del chip y el emplazador la dispersa,
de modo que aquí ya no se gana acortando lógica.

Llegar ahí costó partir en dos los dos caminos que terminan escribiendo el banco
de registros. Los dos eran la misma forma de fallo —mucha lógica combinacional
desembocando en el multiplexor de `register_write_data`, que sirve a la ALU, a
los saltos, a los desplazamientos y a los `LOAD`— y los dos se arreglan igual,
metiendo un ciclo por medio:

| Estado            | Qué separa                                                | Coste                             |
|-------------------|-----------------------------------------------------------|-----------------------------------|
| `STATE_MUL_SIGN`  | el arreglo de signo (negación de 32 bits) de la escritura | +1 ciclo en `MUL`, `MULFX`, `DIV` |
| `STATE_ALU_WRITE` | la suma `operand_a + operand_b` de la escritura           | +1 ciclo en las ALU               |

El segundo no es nuevo: es el mismo estado que ya tenía
[`../10.fpga-cpu-ram`](../10.fpga-cpu-ram), que se añadió allí por este mismo
motivo. Esta carpeta no lo tenía porque `MUL`/`MULFX`/`DIV` se añadieron sobre
una base anterior, y los cinco estados que traen llenaban los 16 de un registro
de 4 bits. Con los dos arreglos son 18 estados y `state` pasa a `[4:0]`.

Las latencias exactas las comprueban `cpu_tb.v` (memoria de un ciclo) y
`cpu_memory_map_tb.v` (memoria real, tres ciclos más), así que un cambio que
añada o quite ciclos no pasa desapercibido.

Coste en área: 5 467 → 5 650 LUT y 2 391 → 2 466 biestables. `MUL` y `MULFX`
usan 4 `MULT18X18D` de los 156 disponibles.

Regresiones principales:

```powershell
apio test cpu_tb.v
apio test cpu_program_system_tb.v
apio test cpu_memory_map_tb.v
apio test register_file_tb.v
apio test monitor_tb.v
apio build
```

Uso físico:

```powershell
python monitor.py write-block 0 fpga_smoke_test.bin --port COM3
python monitor.py reset --port COM3
python monitor.py run --port COM3
python monitor.py status --port COM3
```

[`instruction-status.md`](docs/instruction-status.md) resume las instrucciones
implementadas y [`timing.md`](docs/timing.md) documenta la microarquitectura y el
cierre de timing. La versión equivalente con SDRAM está en
[`../10.fpga-cpu-ram`](../10.fpga-cpu-ram).
