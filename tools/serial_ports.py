"""Puertos serie de la placa, compartido por los `monitor.py` de los prototipos.

Por que esta aqui y no en cada monitor
--------------------------------------
Los trece `monitor.py` llevaban esta funcion COPIADA palabra por palabra. Eso
no se noto mientras funciono, y se noto mucho cuando dejo de funcionar: coger
`comports()[0]` da el primer puerto del SISTEMA, que no tiene por que ser la
placa. Con la ULX3S desenchufada, esa lista empezaba por el puerto serie de la
placa base y dos enlaces Bluetooth; el codigo abria uno de ellos tan campante y
el fallo salia mucho despues, como un timeout de escritura -- un sintoma que se
parece bastante a "la FPGA no tiene monitor" y nada a "no has enchufado nada".

Filtrar por fabricante (el puente USB de la ULX3S es un FTDI) es lo unico
estable: el numero de COM cambia solo con desenchufar y volver a enchufar.

Sobre la copia de x.tests/backends/board.py
-------------------------------------------
Alli vive la misma logica, y se queda. `x.tests` NO depende de `tools/` a
proposito (la dependencia va de aqui hacia alla, ver `tools/run_board.py`), y
ademas `board.py` recibe el `monitor.py` del prototipo como modulo: si el
monitor importara de x.tests habria un ciclo. Son dos copias de quince lineas
en vez de trece, y `x.tests/test_monitor_port.py` comprueba que no divergen.
"""
from __future__ import annotations

from serial.tools import list_ports

# El puente USB-serie de la ULX3S. Mismo valor que backends.board.FTDI_VENDOR_ID.
FTDI_VENDOR_ID = 0x0403


class PortError(RuntimeError):
    """No se puede saber con que puerto hablar."""


def ftdi_ports() -> list:
    """Los puertos que son de un adaptador FTDI, en el orden del sistema."""
    return [p for p in list_ports.comports() if p.vid == FTDI_VENDOR_ID]


def available_ports() -> str:
    """Listado para mensajes de error, senalando cual es la placa.

    Marcar el FTDI importa: el caso que hace perder el rato es ver tres puertos
    y creer que alguno es la placa cuando ninguno lo es.
    """
    ports = list(list_ports.comports())
    if not ports:
        return "No serial ports detected"

    return "Available ports: " + ", ".join(
        f"{p.device} (FTDI)" if p.vid == FTDI_VENDOR_ID else p.device
        for p in ports
    )


def detect_port() -> str:
    """El puerto de la placa, o un error que dice que hacer."""
    ports = ftdi_ports()
    if not ports:
        raise PortError(
            "No encuentro ningun adaptador FTDI: la placa no esta conectada "
            "(o esta alimentada por bateria). " + available_ports()
        )
    if len(ports) > 1:
        names = ", ".join(p.device for p in ports)
        raise PortError(f"Hay varios adaptadores FTDI ({names}); di cual con --port.")
    return ports[0].device
