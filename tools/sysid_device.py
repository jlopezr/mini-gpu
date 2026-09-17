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

MAGIC = 0x4D47          # "MG"

BASE = 0x8000_0F00
SIZE = 256

SYS_ID = 0x00
CONTRACT = 0x04
DEV_BITMAP = 0x08
ISA_PROFILE = 0x0C

# Los mismos bits que el RTL.
BIT_MUL = 1 << 0
BIT_DIV = 1 << 1
BIT_SUBWORD = 1 << 2
BIT_SIMT = 1 << 3


class SysIdDevice:
    """Cuatro palabras de sólo lectura. Escribir se ignora, como en el RTL."""

    BASE = BASE
    SIZE = SIZE

    SYS_ID = SYS_ID
    CONTRACT = CONTRACT
    DEV_BITMAP = DEV_BITMAP
    ISA_PROFILE = ISA_PROFILE

    def __init__(self, folder: int, isa_profile: int, contract: int = 1):
        if not 0 <= folder <= 0xFF:
            raise ValueError("el número de carpeta son ocho bits")
        self.folder = folder
        self.isa_profile = isa_profile
        self.contract = contract

    def contains(self, address: int) -> bool:
        return self.BASE <= address < self.BASE + self.SIZE

    def read(self, offset: int) -> int:
        if offset == self.SYS_ID:
            return (MAGIC << 16) | self.folder
        if offset == self.CONTRACT:
            return self.contract
        if offset == self.DEV_BITMAP:
            # Fase 4b. Cero con CONTRACT = 1 significa «sin declarar», no
            # «ningún dispositivo».
            return 0
        if offset == self.ISA_PROFILE:
            return self.isa_profile
        # Un registro que no existe lee cero, igual que en el bloque de vídeo.
        return 0

    def write(self, offset: int, value: int) -> None:
        """Sólo lectura: la escritura se traga, no se falla.

        Es lo que hace el RTL --`sysid.v` no tiene puerto de escritura y el
        decodificador ignora la escritura sobre su slot-- y la diferencia
        importa: un programa que escribiera aquí por error se comportaría
        distinto en simulación que en la placa.
        """
        del offset, value

    def tick(self) -> None:
        """No tiene estado que avanzar; existe para encajar con los demás."""
