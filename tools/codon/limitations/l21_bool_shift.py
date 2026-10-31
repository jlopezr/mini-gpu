"""Un `bool` no se puede desplazar (`(x is not None) << 6`).

Síntoma (0.20.5): `unsupported operand type(s) for <<: 'bool' and '6'`.
Rodeo: `int(...) << n` (GpuSimtDebugDevice.read, GpuWarpsDevice).
Al resolverse: se puede quitar el `int(...)`.
"""
lane = 3
print("OK" if ((lane is not None) << 6) == 64 else "MAL")
