# UART en FPGA

Segunda etapa de bring-up de la ULX3S. Añade PLL a 120 MHz y una UART conectada
al FTDI de la placa. `hello.v` implementa una demostración serie a 3 Mbaud y
muestra actividad mediante los LEDs.

```powershell
apio build
apio upload
```

Configuración serie: 3.000.000 baudios, 8 bits, sin paridad y un bit de parada.
Los módulos `uart.v` y `util.v` se reutilizan después en el monitor y en las
versiones con CPU.
