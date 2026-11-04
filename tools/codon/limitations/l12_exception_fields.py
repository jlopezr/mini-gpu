"""Una excepción sin campos declarados es genérica: `except` no conoce sus tipos.

Síntoma (0.20.5): `unsupported operand type(s) for +: 'int' and 'NoneType'`; en
el simulador, peor: la excepción no se capturaba y abortaba el proceso.
Rodeo: declarar los campos (`code: int`, `address: int | None`) en
`ExecutionFault` de minigpu_sim.py.
Al resolverse: las declaraciones pueden quedarse.
"""
class Fault(Exception):
    def __init__(self, code: int, address: int | None = None):
        super().__init__("fault")
        self.code = code
        self.address = address
def first():
    raise Fault(1)
def second():
    raise Fault(2, 0x40)
total = 0
for function in (first, second):
    try:
        function()
    except Fault as exc:
        total += exc.code
print("OK" if total == 3 else "MAL")
