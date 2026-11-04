"""Un `X | None` no se convierte a su clase base al añadirlo a una lista.

Con herencia Codon admite usar una subclase como su base (polimorfismo), y
también devolver un `Video | None` desde una función anotada `-> Device | None`.
Pero tras `if video is not None`, `video` sigue siendo `Optional[Video]`, y
`devices.append(video)` en una `list[Device]` falla. Síntoma (0.20.5): `bad cast!`
en `force_cast(obj: Optional[Video], D: Device)`.
Rodeo: ninguno hace falta hoy. Los núcleos no guardan listas de dispositivos:
`CPU._device` y `System.device_for` los miran uno por uno y los devuelven.
Si alguna vez hiciera falta, un `present(x)` en `tools/codon_compat` (identidad en
Python; `x.__val__()` en Codon) lo resuelve.
Al resolverse: se podría volver a un bucle sobre una lista de dispositivos.
"""
class Device:
    def read(self) -> int:
        return 0
class Video(Device):
    def read(self) -> int:
        return 7
devices: list[Device] = []
video: Video | None = Video()
if video is not None:
    devices.append(video)
print("OK" if devices[0].read() == 7 else "MAL")
