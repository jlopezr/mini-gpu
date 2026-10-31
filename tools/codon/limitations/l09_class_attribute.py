"""Un atributo de clase desactiva la inferencia de campos desde `__init__`.

Pasa con `profile = None`, con constantes (`BASE = 0x80000000`) y con `ClassVar`.
Síntoma (0.20.5): `'Device' object has no attribute 'value'`.
Rodeo: declarar todos los campos en la clase (`value: int`), que además documenta.
Al resolverse: las declaraciones pueden quedarse (son Python válido) o quitarse.
"""
class Device:
    BASE = 0x80000000
    def __init__(self, value: int):
        self.value = value
print("OK" if Device(5).value + (Device.BASE >> 31) == 6 else "MAL")
