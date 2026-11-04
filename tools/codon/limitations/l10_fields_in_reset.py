"""Solo se infieren los campos asignados directamente en `__init__`.

Si `__init__` llama a `reset()` y es `reset()` quien los crea, no existen.
Síntoma (0.20.5): `'Lane' object has no attribute 'regs'`.
Rodeo: declarar los campos en la clase (`regs: list[int]`); `Warp` y la lane de
minigpu_sim.py.
Al resolverse: las declaraciones pueden quedarse o quitarse.
"""
class Lane:
    def __init__(self):
        self.reset()
    def reset(self):
        self.regs = [0] * 4
print("OK" if len(Lane().regs) == 4 else "MAL")
