# Validación del monitor 2.1 y del runner GPU

Fecha: 2026-09-10.

- `python -m unittest discover -s x.cpu-tests -p 'test_*.py'`: 29 pruebas PASS.
  Cubren decodificación de estado real, lectura selectiva de registros,
  diagnóstico de fallos, actualización 2.0 a 2.1, selección por capacidades,
  rechazo antes de contactar hardware y comparación `gpu-both`.
- Suite funcional GPU sin los dos Mandelbrot: 32 casos PASS. Conserva las
  expectativas completas del simulador, incluidos los casos no compatibles
  con la FPGA.
- `./12.fpga-gpu/check.ps1 -Action Tests`: PASS. Siete pruebas Python del monitor
  y seis testbenches RTL (control, LSU, regiones, scheduler, sistema y UART).
- `gpu_system_tb.v`: 32 casos diferenciales PASS, comparando los 2048 registros,
  PC, máscaras, pilas vacías, 512 palabras de datos y los nuevos contadores
  por warp. Incluye memoria, BAR, EXIT y reconvergencia.
- `gpu_uart_tb.v`: PASS, comprueba la versión 2.1 por los pines UART.
- `./12.fpga-gpu/check.ps1 -Action Lint`: PASS, sin avisos de Verilator.

La selección automática actual contiene 26 casos compatibles con BRAM y
8 omisiones explícitas: 4 configuraciones SIMT distintas, 3 casos fuera de
BRAM y 1 caso que requiere atomicidad ante división por cero.

No se ha cargado esta revisión en una placa física. Las pruebas del backend
Python usan un monitor simulado; no sustituyen la ejecución de los 26 casos
en la placa.

La compilación física del monitor 2.1 está en curso; no debe confundirse un
bitstream anterior con el resultado de esta revisión.
