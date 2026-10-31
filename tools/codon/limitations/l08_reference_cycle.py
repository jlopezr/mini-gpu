"""Dos clases no pueden apuntarse mutuamente (ciclo de referencias).

Ni con campos inferidos, ni declarados, ni con anotaciones entre comillas.
Síntoma (0.20.5): `cannot typecheck 'self'` / `name 'Child' is not defined`.
Rodeo: nadie guarda a su padre. En la GPU, `System -> SM -> Warp -> lane` solo
apuntan hacia abajo y `system` (y `warp`, para GETID) baja como argumento.
Al resolverse: podría volver `self.warp`/`self.sm`/`self.system` si se quisiera;
no es necesario.
"""
class Parent:
    def __init__(self):
        self.children = [Child(self, i) for i in range(3)]
class Child:
    def __init__(self, parent, n: int):
        self.parent = parent
        self.n = n
    def value(self) -> int:
        return self.n + len(self.parent.children)
print("OK" if sum(c.value() for c in Parent().children) == 12 else "MAL")
