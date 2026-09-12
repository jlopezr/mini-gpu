# Validación de la GPU con SDRAM

Validación realizada el 11 de septiembre de 2026.

## Simulación y lint

- 8 pruebas Python del monitor: configuración, validación antes de modificar
  hardware, límites de transferencia y PC en la última palabra de SDRAM.
- 32 casos diferenciales del simulador funcional, ejecutados con el controlador
  SDRAM real y el modelo funcional del bus. Fixtures regenerados sin diferencias.
- Control de GPU: errores, STEP, halt/resume, barreras, acceso exclusivo del host
  y conservación de memoria tras reset.
- Fetch desde `0x00100000` y STORE/LOAD sobre `0x01fffffc` mediante la GPU.
- Regiones SIMT y scheduler conservan sus pruebas de 12.
- LSU: ocho tags ocupados, 64 lanes, resultados por tag/lane, respuesta retenida
  mientras progresa el auxiliar, máscara vacía, errores por lane, alineación,
  último word, máscaras de bytes y refresco.
- Reset de LSU antes/después de aceptar cada mitad, sin reiniciar el controlador:
  no aparecen respuestas de la operación cancelada en la siguiente petición.
- UART del top a 250000 baudios: carga y ejecución, configuración de warp,
  registros, reset, bloques en la última palabra y rechazo al cruzar los 32 MiB.
- `apio lint`: correcto, sin avisos.

Comandos ejecutados desde la raíz:

```powershell
.venv/Scripts/python.exe 14.fpga-gpu-ram/make_fixtures.py
.venv/Scripts/python.exe -m unittest discover -s 14.fpga-gpu-ram -p test_*.py -v
.venv/Scripts/apio.exe test -p 14.fpga-gpu-ram
.venv/Scripts/apio.exe test -p 14.fpga-gpu-ram gpu_uart_tb.v
.venv/Scripts/apio.exe test -p 14.fpga-gpu-ram gpu_lsu_tb.v
.venv/Scripts/apio.exe lint -p 14.fpga-gpu-ram
.venv/Scripts/apio.exe build -p 14.fpga-gpu-ram
```

Las dos pruebas individuales comprueban las últimas ampliaciones de cobertura
tras la regresión completa. Los logs locales son `tests.log`, `uart-tests.log`,
`lsu-tests.log`, `lint.log` y `build.log` (ignorados por Git).

## Síntesis y timing

Bitstream final generado correctamente para ULX3S-85F. `check.ps1 Build`
verifica el informe de nextpnr y confirma **33.49 MHz ≥ 25 MHz**.
El diseño funciona a 25 MHz; la frecuencia alcanzada es la estimación del informe.

| Recurso | Usado | Disponible |
|---|---:|---:|
| TRELLIS_COMB | 31540 | 83640 |
| TRELLIS_FF | 9016 | 83640 |
| DP16KD | 16 | 208 |
| MULT18X18D | 32 | 156 |

Los 16 bloques DP16KD se destinan a los registros de la GPU; código/datos
se almacenan en SDRAM. Yosys emite su aviso habitual sobre soporte limitado de
triestados para `sdram_d`; nextpnr y ecppack completan la generación.

Bitstream: [`_build/default/hardware.bit`](../_build/default/hardware.bit)
(807884 bytes). SHA-256:
`61685eaf2a2bc18d90d23181abbdee3b28d748588e0aec511e2155dec8996f23`.

## Alcance

El modelo de SDRAM decodifica comandos, filas, bancos, columnas y DQM en el bus;
no es un modelo de temporización del fabricante. El cierre de timing comprueba
el dominio interno de 25 MHz; no demuestra los márgenes eléctricos de la SDRAM.
No se ha programado ni probado la placa física en esta sesión.
