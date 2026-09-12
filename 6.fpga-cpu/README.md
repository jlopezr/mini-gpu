# MiniCPU con memorias EBR

Integración de la MiniCPU multiciclo, el monitor UART y dos memorias EBR de
16 KiB. Es la versión FPGA `ebr` utilizada por `x.cpu-tests` y responde como
monitor 1.6. Esta revisión implementa `MUL`, `MULFX` y `DIV`. `MUL` conserva
los 32 bits bajos; `MULFX` opera en signed Q16.16 mediante cuatro productos
parciales de 16 bits, y `DIV` usa un divisor signed iterativo de 32 pasos.

Mapa unificado visible por la CPU y el monitor:

| Banco | Dirección global |
|---|---:|
| EBR 0 | `0x00000000–0x00003fff` |
| EBR 1 | `0x00100000–0x00103fff` |
| Huecos y resto | error de bus |

Los puertos `imem` y `dmem` pueden acceder a cualquiera de los dos bancos.
Así, un `LOAD` puede leer código, un `STORE` puede modificarlo y el fetch puede
ejecutar desde la EBR 1. Normalmente el programa se carga en la EBR 0 y los
datos se colocan en la EBR 1.

El monitor controla ambas memorias mientras la CPU está detenida. Durante la
ejecución, la CPU lee instrucciones y realiza `LOAD`/`STORE`; los accesos de
memoria del monitor se rechazan.

## Temporización: 120 MHz, con el margen justo

El diseño corre a 120 MHz y **la semilla de nextpnr decide si cumple**: de ocho,
cierran cuatro, entre 109,90 y 124,39 MHz. Por eso `apio.ini` fija `--seed 3`,
que da 124,39 (+3,7 %). Esto es distinto del 15, donde la semilla sólo elige
margen porque todas cumplen.

Llegar ahí costó partir en dos los dos caminos que terminan escribiendo el banco
de registros. Los dos eran la misma forma de fallo —mucha lógica combinacional
desembocando en el multiplexor de `register_write_data`, que sirve a la ALU, a
los saltos, a los desplazamientos y a los `LOAD`— y los dos se arreglan igual,
metiendo un ciclo por medio:

| Estado | Qué separa | Coste |
|---|---|---|
| `STATE_MUL_SIGN` | el arreglo de signo (negación de 32 bits) de la escritura | +1 ciclo en `MUL`, `MULFX`, `DIV` |
| `STATE_ALU_WRITE` | la suma `operand_a + operand_b` de la escritura | +1 ciclo en las ALU |

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

[`instruction-status.md`](instruction-status.md) resume las instrucciones
implementadas y [`timing.md`](timing.md) documenta la microarquitectura y el
cierre de timing. La versión equivalente con SDRAM está en
[`../10.fpga-cpu-ram`](../10.fpga-cpu-ram).
