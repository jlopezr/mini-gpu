# MiniCPU con SDRAM y monitor UART

Este proyecto integra la MiniCPU de `6.fpga-cpu` con el controlador SDRAM de
`9.fpga-ram-param`. Todo el datapath principal funciona en un único dominio de
120 MHz. El monitor UART conserva los comandos de ejecución y depuración de la
carpeta 6 y trabaja a 3 Mbaud.

## Mapa de memoria

La CPU mantiene dos espacios Harvard locales de 16 MiB. El monitor ve la SDRAM
como un único espacio físico de 32 MiB:

| Uso | Dirección CPU | Dirección del monitor |
|---|---:|---:|
| Programa | `0x00000000`–`0x00ffffff` | `0x00000000`–`0x00ffffff` |
| Datos | `0x00000000`–`0x00ffffff` | `0x01000000`–`0x01ffffff` |

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

Para inspeccionar datos escritos por la CPU se usa la base física
`0x01000000`. Por ejemplo, la dirección local de datos `4` se lee desde
`0x01000004` con el monitor.

## Verificación

```powershell
apio test sdram_system_adapter_tb.v
apio test cpu_sdram_system_tb.v
apio test monitor_tb.v
apio test sdram_controller_tb.v
apio build
```

`cpu_sdram_system_tb.v` comprueba el flujo completo: carga mediante el puerto
del monitor, fetch desde SDRAM, `STORE`, `LOAD` y `HALT`.

## Estado del timing

La integración es funcional en simulación, pero el place-and-route actual no
cierra todavía la restricción de 120 MHz. La mejor colocación medida alcanza
118,64 MHz y la ejecución predeterminada queda alrededor de 116 MHz. `apio
build` genera el bitstream porque usa `--timing-allow-fail`; no debe tratarse
como bitstream validado a 120 MHz hasta eliminar ese aviso de nextpnr.
