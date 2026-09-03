# Bring-up de FPGA

Primer proyecto APIO para la ULX3S-85F. `blinky.v` permite comprobar la placa,
el reloj de 25 MHz, las restricciones de pines, la síntesis y la programación
antes de añadir UART o CPU.

```powershell
apio build
apio upload
```

[`fpga.md`](fpga.md) recoge la arquitectura prevista y
[`documentacion.md`](documentacion.md) contiene notas del flujo inicial. Esta
carpeta es un hito mínimo; los diseños funcionales posteriores se encuentran
en las carpetas 4–10.
