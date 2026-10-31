"""No hay tipado pato entre clases distintas: una tupla o un retorno de varias
clases no tiene tipo.

Los simuladores recorrían `(self.video, self.serial, self.input, self.sysid)` y
devolvían el que respondía. Síntoma (0.20.5): `'Optional[Video]' does not match
expected type 'Optional[Serial]'`.
Rodeo: `_device()` devuelve un índice y `device_read`/`device_write`/
`device_validate` despachan con una cadena de `if`.
Al resolverse (protocolos o uniones): volver a devolver el dispositivo.
"""
class Video:
    def contains(self, address: int) -> bool:
        return address == 1
class Serial:
    def contains(self, address: int) -> bool:
        return address == 2
devices = (Video(), Serial())
def device_for(address: int):
    for device in devices:
        if device.contains(address):
            return device
    return None
print("OK" if device_for(2) is devices[1] else "MAL")
