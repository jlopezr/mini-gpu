# MiniCPU en ULX3S-85F

## Decisiones

- Placa: ULX3S con Lattice ECP5 `LFE5U-85F-6BG381C`.
- HDL: **Verilog**.
- Entorno principal: Windows.
- Gestión del proyecto: APIO, usando la placa `ulx3s-85f`.
- Toolchain subyacente: Yosys, nextpnr-ecp5, Project Trellis y ecppack.
- Programación de la placa: APIO/openFPGALoader mediante USB1.
- Reloj inicial: 25 MHz, sin PLL.
- Primera CPU: multiciclo mediante FSM, sin pipeline.
- Programa y datos: memorias EBR internas; no usar SDRAM inicialmente.
- Framebuffer: 320 × 240 palabras de 32 bits en EBR.
- `MUL` y `MULFX`: unidad compartida, preferiblemente inferida en DSP.
- `DIV`: unidad signed iterativa.
- Vídeo GPDI: se deja para una etapa posterior.

El rendimiento no es un objetivo de la primera versión. Se priorizan un diseño
fácil de comprender, la depuración y la equivalencia con el simulador funcional.

## Arquitectura inicial

```text
PC ──USB/UART──► monitor RTL
                     │
                     ├── RAM de instrucciones
                     ├── RAM de datos / framebuffer
                     └── control reset/run/halt/step
                                      │
                                MiniCPU multiciclo
```

La organización física será inicialmente Harvard: una EBR para instrucciones y
otra memoria para datos. Esta separación es una decisión de microarquitectura y
no modifica la ISA.

## Monitor UART

Antes de integrar la CPU se implementará un monitor UART en Verilog,
independiente del procesador. Permitirá comprobar el setup de la FPGA y después
servirá como herramienta de carga y depuración.

Funciones previstas:

- `PING` e información de versión;
- lectura y escritura de memoria;
- carga de programas sin regenerar el bitstream;
- descarga del framebuffer;
- reset, arranque, parada y ejecución paso a paso;
- consulta de PC, registros y estado de la CPU.

Se utilizará un protocolo binario con magic, comando, secuencia, dirección,
longitud, payload y checksum. Mientras la CPU esté ejecutándose controlará las
memorias; cuando esté detenida o en reset, las controlará el monitor.

## Orden de implementación

1. Crear el proyecto APIO para `ulx3s-85f`.
2. Verificar build y upload con un LED.
3. Implementar UART RX/TX y echo.
4. Añadir `PING` e `INFO`.
5. Probar `MEM_WRITE` y `MEM_READ` sobre una EBR pequeña.
6. Crear el cliente Python y verificar patrones aleatorios.
7. Implementar la MiniCPU mínima: `MOVI`, `ADD` y `HALT`.
8. Añadir ejecución paso a paso e inspección de registros.
9. Completar branches, memoria, `MUL`, `MULFX` y `DIV`.
10. Cargar Mandelbrot, ejecutarlo y comparar el `.iter` con el golden model.

## Flujo previsto

```text
mandelbrot.asm
      ↓ miniisa_asm.py
mandelbrot.bin
      ↓ monitor UART
RAM de instrucciones
      ↓ CPU_RUN
MiniCPU ejecuta hasta HALT
      ↓ MEM_READ
framebuffer.raw
      ↓ raw_to_iter.py
mandelbrot.iter
      ↓ comparación
golden model Q16.16
```

## Pendiente de concretar

- Versión de APIO y paquetes que se fijará para builds reproducibles.
- Revisión exacta de la placa y fichero de constraints correspondiente.
- Baud rate y formato definitivo del protocolo UART.
- Mapa de memoria y registros de control.
- Tamaño de las memorias de programa y datos.
- Latencias exactas de multiplicación y división.
- Política de traps y errores.
