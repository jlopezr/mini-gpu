"""`from paquete import módulo` no funciona, y `import paquete.x` dentro del propio
paquete se busca desde la carpeta del fichero, no desde la raíz.

Síntomas (0.20.5): `cannot import name 'x' from 'paquete.__init__'` y `no module
named 'tools.mmio_device'` (importado desde tools/sysid_device.py).
Rodeo: `import tools.mmio_map as mm` en vez de `from tools import mmio_map as mm`,
e import relativo (`from .mmio_device import MmioDevice`) dentro de tools/.
Al resolverse: se puede volver a `from tools import ...`.
El paquete de prueba es `l18pkg/`, al lado.
"""
from l18pkg import consts
print("OK" if consts.VALUE == 7 else "MAL")
