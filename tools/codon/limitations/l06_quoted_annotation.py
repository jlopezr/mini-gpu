"""Una anotación entre comillas es el tipo `str`, no una referencia diferida.

En Python `"Video | None"` solo documenta; Codon toma las anotaciones como tipos
reales. Síntoma (0.20.5): `'Video[int]' does not match expected type 'str'`.
Rodeo: `Optional[Video]` sin comillas en los constructores de los simuladores.
Al resolverse: nada obligatorio; se podría volver a `"X | None"`.
"""
class Video:
    def __init__(self):
        self.n = 7
class Cpu:
    def __init__(self, video: "Video | None" = None):
        self.video = video
print("OK" if Cpu(Video()).video.n == 7 else "MAL")
