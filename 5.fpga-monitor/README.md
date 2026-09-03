# Monitor UART con EBR

Monitor binario para leer y escribir una memoria EBR de 16 KiB sin integrar
todavía la CPU. Funciona a 120 MHz y comunica por UART a 3 Mbaud.

Operaciones disponibles: `PING`, versión 1.0, lectura y escritura de bytes y
transferencias de bloques de hasta 256 bytes. El cliente de PC es `monitor.py`.

```powershell
apio test monitor_tb.v
apio build
python monitor.py --help
python monitor.py ping --port COM3
```

Esta etapa valida el protocolo y la carga de memoria. La carpeta 6 amplía el
monitor con control y depuración de la CPU.
