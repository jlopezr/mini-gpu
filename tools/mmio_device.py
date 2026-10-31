"""Base común de los dispositivos MMIO de los simuladores.

Un núcleo pregunta qué dispositivo responde a una dirección y le pasa el acceso
con `read`/`write`/`validate`, sin saber cuál es. En Python eso funciona con
cualquier objeto que tenga esos métodos; Codon, que compila el mismo núcleo, no
tiene tipado pato y necesita una clase base común (`tools/codon/LIMITACIONES.md`,
l11). Por eso `BASE` y `SIZE` son campos de la instancia y no constantes de clase:
Codon no ve la constante de la subclase a través de la base.
"""


class MmioDevice:
    """Un bloque MMIO: dirección, tamaño y qué hace cada acceso."""

    BASE: int
    SIZE: int

    def __init__(self, base: int, size: int):
        self.BASE = base
        self.SIZE = size

    def contains(self, address: int) -> bool:
        return self.BASE <= address < self.BASE + self.SIZE

    def validate(self, offset: int, writing: bool = False) -> None:
        """Comprueba un acceso sin hacerlo; RuntimeError si no se admite."""
        raise RuntimeError(f"acceso no admitido: {self.BASE + offset:#010x}")

    def read(self, offset: int) -> int:
        self.validate(offset)
        return 0

    def write(self, offset: int, value: int) -> None:
        self.validate(offset, writing=True)

    def tick(self) -> None:
        """Sin reloj propio, por defecto."""

    def gpu_may_read(self, offset: int) -> bool:
        """Si la GPU puede leer este registro (§15). Por defecto, sí: lo que la
        GPU no ve en absoluto lo decide el permiso del bus, no el dispositivo."""
        return True


class MachineHooks:
    """Lo que piden al sistema completo la GPU y el anfitrión.

    `on_retire`: la GPU avisa tras cada instrucción de warp retirada.
    `request_stop`: parar en la próxima instrucción (cerrar la ventana, F12,
    Ctrl+C; ver `tools/sim_host.stop_machine`).

    Por defecto no hacen nada; `CpuGpuSystem` (32) los implementa. Es una clase y
    no funciones guardadas en campos porque Codon no admite esto último, y la base
    común evita ciclos de tipos: GpuUnit <-> CpuGpuSystem, y en el motor Codon,
    periféricos <-> sistema (tools/codon/LIMITACIONES.md, l08). Vive aquí, y no
    en 32, para que la vean también los periféricos (`sim_devices.codon`).
    """

    def on_retire(self) -> None:
        pass

    def request_stop(self) -> None:
        pass
