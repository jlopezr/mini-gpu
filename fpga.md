# Implementación en FPGA

## 1. Objetivo

La primera implementación física será una MiniCPU multiciclo, sin pipeline,
sobre una ULX3S-85F. El rendimiento no es un objetivo inicial: se priorizan la
claridad del diseño, la facilidad de depuración y la equivalencia con el
simulador funcional.

No es necesario construir previamente un simulador a ciclos completo. El
testbench VHDL y la comparación contra el simulador funcional actuarán como
referencia durante esta etapa.

## 2. Plataforma

La placa elegida es la **ULX3S-85F**, equipada con un Lattice ECP5
`LFE5U-85F-6BG381C`.

Recursos relevantes:

- reloj integrado de 25 MHz;
- aproximadamente 84K LUT;
- 208 bloques EBR de 18 Kbit, 3744 Kbit en total —unos 468 KiB—;
- 156 multiplicadores de 18 × 18 bits;
- FTDI FT231XS conectado a USB1 para JTAG y UART;
- SDRAM externa;
- flash SPI, tarjeta micro-SD y salida de vídeo GPDI.

Referencias:

- [Proyecto y esquema de ULX3S](https://github.com/emard/ulx3s)
- [Recursos de la familia ECP5](https://www.latticesemi.com/Products/FPGAandCPLD/ECP5?ActiveTab=Data+Sheet)
- [Manual de ULX3S](https://github.com/emard/ulx3s/blob/master/doc/MANUAL.md)

## 3. Decisiones iniciales

| Elemento | Decisión |
|---|---|
| Arquitectura | MiniCPU multiciclo mediante FSM |
| Pipeline | No |
| Frecuencia inicial | 25 MHz, sin PLL |
| Memoria de programa | EBR interna cargable por el monitor UART |
| Memoria de datos | EBR interna |
| Framebuffer | EBR interna, una palabra de 32 bits por píxel |
| SDRAM externa | No usar inicialmente |
| Multiplicación | Unidad compartida para `MUL` y `MULFX`, preferiblemente con DSP |
| División | Divisor signed iterativo, aproximadamente 32 ciclos |
| Comunicación | UART a través del FTDI de USB1 |
| Depuración | Monitor UART, testbench y LEDs de estado |
| Vídeo GPDI | Etapa posterior |

La organización física inicial será Harvard: una memoria de instrucciones y
otra de datos. La ISA conserva direcciones de 32 bits y no expone esta separación
como un detalle arquitectónico.

```text
                 ┌──────────────────┐
monitor UART ───►│ RAM instrucciones│
                 └────────┬─────────┘
                          │
                    ┌─────▼─────┐
25 MHz ────────────►│ MiniCPU   │
                    │ multiciclo│
                    └─────┬─────┘
                          │
                 ┌────────▼─────────┐
monitor UART ◄──►│ RAM / framebuffer│
                 └──────────────────┘
```

## 4. Memoria y framebuffer

El framebuffer actual ocupa:

```text
320 × 240 × 4 bytes = 307 200 bytes = 300 KiB
```

Cabe en los aproximadamente 468 KiB de EBR del ECP5-85F y deja alrededor de
168 KiB teóricos para programa y otros datos. El margen real será menor por la
granularidad y configuración de los bloques EBR, por lo que se deberá comprobar
la ocupación durante la síntesis.

La SDRAM externa queda fuera de la primera versión. Así se evitan inicialmente
el controlador, el refresco, el arbitraje y las latencias variables.

Mapa preliminar heredado del simulador:

```text
0x00000000  programa
0x00100000  framebuffer de 320 × 240 palabras
```

El mapa definitivo y el tamaño máximo del programa siguen abiertos.

## 5. MiniCPU multiciclo

La CPU ejecutará una sola instrucción cada vez mediante estados explícitos:

```text
FETCH → DECODE → EXECUTE → MEMORY → WRITEBACK → FETCH
```

No todas las instrucciones necesitan recorrer todos los estados. Las operaciones
de varias latencias tendrán estados propios:

```text
MUL_START → MUL_WAIT → MUL_WRITEBACK
DIV_START → DIV_ITERATE → DIV_WRITEBACK
```

La primera versión no tendrá hazards, forwarding, caché, scoreboard ni lógica de
pipeline. Cada instrucción deberá producir exactamente el mismo estado
arquitectónico que `2.cpu-sim-func/minicpu_sim.py`.

## 6. Monitor UART

Se implementará primero un monitor UART en RTL independiente de la CPU. Esto
permite cargar programas y diagnosticar memoria incluso cuando la MiniCPU todavía
no funciona.

El monitor proporcionará:

- carga de programas sin regenerar el bitstream;
- lectura y escritura de memoria;
- descarga del framebuffer;
- reset, arranque, parada y ejecución paso a paso de la CPU;
- lectura del PC, registros y estado de ejecución;
- información de versión y configuración del sistema.

El monitor será inicialmente hardware dedicado. En una etapa posterior podrá
sustituirse o complementarse con un bootloader escrito en MiniISA.

### 6.1. Protocolo

Se utilizará un protocolo binario con framing explícito, en lugar de interpretar
comandos ASCII dentro de la FPGA:

```text
magic | comando | secuencia | dirección | longitud | payload | checksum
```

Características previstas:

- magic fijo para recuperar la sincronización;
- longitud explícita;
- número de secuencia para asociar petición y respuesta;
- CRC16 o CRC32 para transferencias;
- respuestas `ACK`, `ERROR` y `BUSY`;
- timeout y reintentos en la herramienta del PC.

Conjunto mínimo de comandos:

| Código | Comando      | Función                          |
|-------:|--------------|----------------------------------|
| `0x01` | `PING`       | Comprueba el enlace              |
| `0x02` | `INFO`       | Devuelve versión y configuración |
| `0x10` | `MEM_READ`   | Lee una región de memoria        |
| `0x11` | `MEM_WRITE`  | Escribe una región de memoria    |
| `0x20` | `CPU_RESET`  | Reinicia y detiene la CPU        |
| `0x21` | `CPU_RUN`    | Inicia o continúa la ejecución   |
| `0x22` | `CPU_HALT`   | Solicita la parada de la CPU     |
| `0x23` | `CPU_STEP`   | Ejecuta una instrucción          |
| `0x24` | `CPU_STATUS` | Consulta estado y PC             |
| `0x25` | `REG_READ`   | Lee registros arquitectónicos    |

Los códigos y el formato binario exactos deberán congelarse antes de implementar
el parser RTL y su cliente para PC.

### 6.2. Propiedad de la memoria

Para evitar un árbitro complejo, la primera versión usará esta regla:

```text
CPU en reset o detenida → el monitor controla las memorias
CPU ejecutándose       → la CPU controla las memorias
```

El monitor podrá recuperar el control y descargar el framebuffer después de
`HALT`. Los comandos de escritura de memoria se rechazarán con `BUSY` mientras la
CPU se encuentre ejecutando.

## 7. Secuencia de implementación

### Hito 1: comunicación con la placa

1. bitstream mínimo y LED de estado;
2. UART RX/TX a 25 MHz;
3. echo de cada byte recibido;
4. comandos `PING` e `INFO`.

Este hito valida la toolchain, constraints, carga del bitstream, reloj, reset,
USB1, FTDI y UART.

### Hito 2: memoria interna

1. conectar el monitor a una EBR pequeña, por ejemplo de 4 KiB;
2. implementar `MEM_WRITE` y `MEM_READ`;
3. crear un cliente Python;
4. escribir patrones aleatorios, leerlos y compararlos byte a byte;
5. ampliar después las memorias hasta el tamaño requerido.

### Hito 3: núcleo mínimo

1. implementar reset, PC, registros y fetch;
2. ejecutar `MOVI`, `ADD` y `HALT`;
3. añadir `CPU_RUN`, `CPU_STATUS`, `CPU_STEP` y `REG_READ`;
4. comparar cada instrucción con el simulador funcional.

### Hito 4: MiniISA para Mandelbrot

1. completar ALU, branches y `LOAD/STORE`;
2. implementar `MUL` y `MULFX`;
3. implementar el divisor iterativo;
4. cargar `mandelbrot.bin` mediante UART;
5. ejecutar hasta `HALT`;
6. descargar el framebuffer;
7. convertirlo a `.iter` y compararlo bit a bit con el golden model Q16.16.

### Hitos posteriores

- bootloader o monitor escrito en MiniISA;
- uso de SDRAM externa si la memoria interna deja de ser suficiente;
- salida de vídeo GPDI;
- simulador funcional y posterior implementación SIMT de MiniGPU;
- pipeline únicamente si aparece un objetivo de rendimiento.

## 8. Flujo de uso previsto

```text
mandelbrot.asm
      ↓ miniisa_asm.py
mandelbrot.bin
      ↓ MEM_WRITE por UART
RAM de instrucciones
      ↓ CPU_RUN
MiniCPU ejecuta hasta HALT
      ↓ MEM_READ por UART
framebuffer.raw
      ↓ raw_to_iter.py
mandelbrot.iter
      ↓ comparación / visor
resultado validado
```

## 9. Decisiones todavía abiertas

- Formato definitivo y checksum del protocolo UART.
- Baud rate inicial y mecanismo de timeout.
- Mapa completo de memoria y registros de control.
- Tamaño reservado para programa y datos no gráficos.
- Implementación exacta y latencia de `MUL`/`MULFX`.
- Comportamiento de `CPU_HALT` cuando hay una instrucción en curso.
- Mecanismo de traps y reporte de errores.
- Toolchain concreta de síntesis, place-and-route y programación.
- Estrategia de testbench y comparación automática con el simulador.
