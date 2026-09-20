"""El bloque de identificación, para los simuladores funcionales.

Gemelo en Python de [`sysid.v`](../22.fpga-gpu-bl8/sysid.v), que es copia
idéntica en las diez carpetas con juego de comandos. Cuatro palabras de sólo
lectura en `0x80000F00`:

      +0x00  SYS_ID        magic 4D47 ("MG") + número de carpeta
      +0x04  CONTRACT      versión del contrato de mapa de memoria
      +0x08  DEV_BITMAP    un bit por dispositivo presente (fase 4b, hoy cero)
      +0x0C  ISA_PROFILE   qué sabe ejecutar el núcleo

Por qué los simuladores también lo llevan
-----------------------------------------
Porque un programa que se identifica —leer `SYS_ID`, mirar `ISA_PROFILE` y
decidir— tiene que poder probarse **sin placa**. Sin esto, el único sitio donde
ese programa corre es el hardware, que es exactamente al revés de como se
trabaja aquí: el caso se escribe contra el simulador y la placa confirma.

Y hay una segunda razón, menos obvia: el simulador es el sitio donde un
`ISA_PROFILE` mentiroso se detecta barato. En el RTL hay un test que contrasta
el perfil declarado contra los opcodes que el núcleo decodifica; aquí se puede
hacer lo mismo contra los opcodes que el modelo ejecuta.

Qué número de carpeta llevan
----------------------------
El suyo: 2 y 11. No fingen ser la placa que modelan, porque no lo son —el
simulador de CPU no tiene un mapa de memoria concreto ni un juego de
dispositivos fijo— y hacerles decir «soy la 21» convertiría `SYS_ID` en una
mentira útil, que es la peor clase.

Los bits de `ISA_PROFILE`, en cambio, sí describen lo que el modelo ejecuta de
verdad, y un test lo contrasta.
"""

# El bloque SYSTEM de MMIO v2 (1.isa/mmio.md §5). Antes eran cuatro palabras
# en 0x80000F00 con el magic 0x4D47 en los bits 31:16 de SYS_ID; ahora son
# siete en 0x80000000 y el magic es una palabra entera con otro valor, para
# que un host no confunda los dos mapas (§5.1).
#
# §17 exige que el simulador implemente el MISMO contrato que el RTL: mismas
# direcciones, mismos registros, mismos errores. Este fichero y `sysid.v`
# tienen que decir lo mismo, y `test_sysid_device.py` lo contrasta.
MAGIC = 0x4D47_4155

VERSION_MAJOR = 2
VERSION_MINOR = 0

BASE = 0x8000_0000
SIZE = 0x1_0000         # bloque de 64 KiB

MAGIC_OFF = 0x00
MMIO_VERSION = 0x04
SYSTEM_ID = 0x08
DEVICES = 0x0C
MEM_BASE = 0x10
MEM_SIZE = 0x14
MONITOR_VERSION = 0x18

# Los mismos bits que el RTL.
BIT_MUL = 1 << 0
BIT_DIV = 1 << 1
BIT_SUBWORD = 1 << 2
BIT_SIMT = 1 << 3


class SysIdDevice:
    """Siete palabras de solo lectura; el resto del bloque da error."""

    BASE = BASE
    SIZE = SIZE

    MAGIC_OFF = MAGIC_OFF
    MMIO_VERSION = MMIO_VERSION
    SYSTEM_ID = SYSTEM_ID
    DEVICES = DEVICES
    MEM_BASE = MEM_BASE
    MEM_SIZE = MEM_SIZE
    MONITOR_VERSION = MONITOR_VERSION

    _REGISTROS = (MAGIC_OFF, MMIO_VERSION, SYSTEM_ID, DEVICES, MEM_BASE,
                  MEM_SIZE, MONITOR_VERSION)

    def __init__(self, folder: int, isa_profile: int, contract: int = 1,
                 devices: int = 0, mem_base: int = 0, mem_size: int = 0,
                 monitor_version: int = 0):
        if not 0 <= folder <= 0xFF:
            raise ValueError("el número de carpeta son ocho bits")
        self.folder = folder
        # ISA_PROFILE ya no se expone por este bloque --la identidad del
        # núcleo es de CPU CORE (§13.1)-- pero se conserva el atributo porque
        # `test_sysid_device.py` lo contrasta contra lo que el modelo ejecuta.
        self.isa_profile = isa_profile
        self.contract = contract
        self.devices = devices
        self.mem_base = mem_base
        self.mem_size = mem_size
        self.monitor_version = monitor_version

    def contains(self, address: int) -> bool:
        return self.BASE <= address < self.BASE + self.SIZE

    def validate(self, offset: int, writing: bool = False) -> None:
        # Las siete son de SOLO LECTURA y el resto del bloque no es alias:
        # da error, no cero (§5). Que un offset reservado devolviera cero
        # haría indistinguible «no existe» de «vale cero».
        if writing or offset not in self._REGISTROS:
            raise RuntimeError(
                f"acceso invalido a SYSTEM: {self.BASE + offset:#010x}")

    def read(self, offset: int) -> int:
        self.validate(offset)
        if offset == self.MAGIC_OFF:
            return MAGIC
        if offset == self.MMIO_VERSION:
            return (VERSION_MAJOR << 8) | VERSION_MINOR
        if offset == self.SYSTEM_ID:
            return self.folder
        if offset == self.DEVICES:
            return self.devices
        if offset == self.MEM_BASE:
            return self.mem_base
        if offset == self.MEM_SIZE:
            return self.mem_size
        if offset == self.MONITOR_VERSION:
            return self.monitor_version

    def write(self, offset: int, value: int) -> None:
        self.validate(offset, writing=True)

    def tick(self) -> None:
        """No tiene estado que avanzar; existe para encajar con los demás."""
