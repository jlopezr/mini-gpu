# MiniCPU con memorias EBR

Integración de la MiniCPU multiciclo, el monitor UART y dos memorias EBR de
16 KiB. Es la versión FPGA `ebr` utilizada por `x.cpu-tests` y responde como
monitor 1.6. Esta revisión implementa `MUL` con tres bloques DSP y conserva
los 32 bits bajos del producto.

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
