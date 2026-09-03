# Monitor UART para la SDRAM de ULX3S

Este proyecto expone los 32 MiB de SDR SDRAM W9825G6KH como un espacio de
memoria direccionado por bytes mediante el monitor UART. Es la unión del
monitor de `5.fpga-monitor`, las direcciones de 32 bits de `6.fpga-cpu` y el
controlador SDRAM de `8.ulx3s_w9825g6kh_test`.

Todo el diseño funciona inicialmente con `clk_25mhz`. La UART trabaja a
625000 baudios (`25 MHz / 40`), con 8 bits, sin paridad y un bit de parada.

## Mapa y protocolo

El rango válido es `0x00000000`–`0x01ffffff`. Las direcciones y longitudes se
envían primero por el byte más significativo:

| Petición                     | Respuesta  | Operación            |
|------------------------------|------------|----------------------|
| `01`                         | `81`       | PING                 |
| `02`                         | `82 02 00` | Versión 2.0          |
| `10 AA AA AA AA DD`          | `90`       | Escribir byte        |
| `11 AA AA AA AA`             | `91 DD`    | Leer byte            |
| `20 AA AA AA AA LL LL DD...` | `a0`       | Escribir 1–256 bytes |
| `21 AA AA AA AA LL LL`       | `a1 DD...` | Leer 1–256 bytes     |

Las operaciones fuera de rango responden `ff`.

## Adaptación a SDRAM y DQM

La interfaz física usa palabras de 16 bits y burst length 1. El adaptador
convierte la dirección de byte en `address >> 1`. Para escrituras pares activa
solo `wmask[0]`; para impares, solo `wmask[1]`. El controlador aplica la
inversión requerida por los pines activos en alto de máscara:

```text
sdram_dqm = ~req_wmask
```

Así, escribir un byte no modifica su vecino. Los bloques del monitor siguen
siendo secuencias de accesos BL1 independientes; todavía no se emplean bursts.

## Pruebas

```powershell
apio test monitor_tb.v
apio test sdram_byte_adapter_tb.v
apio build
```

Prueba física equivalente a los patrones de la carpeta 8, controlada desde el
PC (128 KiB en este ejemplo):

```powershell
python monitor.py memory-test 0 0x20000 --port COM3
```

También están disponibles `ping`, `get-version`, `write-byte`, `read-byte`,
`write-block`, `read-block` y `verify`. Use `python monitor.py --help` para ver
los argumentos.

## LEDs

| LED | Significado                             |
|-----|-----------------------------------------|
| 0   | Inicialización SDRAM terminada          |
| 1   | Monitor ocupado                         |
| 2   | Controlador SDRAM ocupado               |
| 3   | Error de acceso durante el pulso actual |
| 7:4 | Cuatro bits bajos del último comando    |

La futura integración con la CPU añadirá un frontend 32→16. Una palabra CPU
de 32 bits requerirá inicialmente dos transacciones BL1; los bursts quedan
fuera del alcance de esta etapa.
