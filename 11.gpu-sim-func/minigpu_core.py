"""Núcleo de la MiniGPU: estado, planificador SIMT y ejecución, sin la CLI.

`minigpu_sim.py` explica el modelo, añade la línea de órdenes y lo reexporta:
quien use el simulador sigue importando `minigpu_sim`. Este módulo lo compila
además el backend Codon de `sim-sys`, así que no usa `sys.path`, `argparse` ni
`from __future__` (tools/codon/LIMITACIONES.md, l14 y l15); necesita en
`sys.path` la raíz del repositorio y esta carpeta, que pone quien lo importa.
"""
from gpu_trace import TextTrace, TraceEvent
from tools.sysid_device import (
    BIT_DIV, BIT_MUL, BIT_SIMT, BIT_SUBWORD, SysIdDevice,
)
# Lo que Codon no trae (struct, from_bytes, dataclasses...): ver tools/codon/LIMITACIONES.md.
from tools.codon_compat import (
    dataclass, load_le, load_u32, store_le, store_u32,
)
from tools.mmio_device import MmioDevice
from tools.sim_devices import InputDevice, SerialDevice, VideoDevice

# Qué sabe ejecutar ESTE modelo. Con `BIT_SUBWORD`: los accesos de 8 y 16 bits
# (LOADB/LOADUB/STOREB/LOADH/LOADUH/STOREH) se retroportaron aquí desde la
# MiniCPU y desde el modelo de ciclos de la 25, que ya los tenían. El RTL de las
# GPU todavía NO: declara `0x0b` (sin este bit), así que este modelo va por
# delante de la placa. Un test contrasta el perfil con los opcodes que el modelo
# ejecuta, no con el RTL.
SIMULATOR_ISA_PROFILE = BIT_MUL | BIT_DIV | BIT_SUBWORD | BIT_SIMT

MASK32 = 0xFFFFFFFF
MAX_WARPS = 8
MAX_SIMT_REGIONS = 8
MAX_SIMT_PATHS = 8
ERROR_NONE = 0x00
ERROR_INVALID_OPCODE = 0x01
ERROR_MEMORY_ACCESS = 0x02
ERROR_EXPLICIT_TRAP = 0x03
ERROR_DIVISION_BY_ZERO = 0x04
ERROR_INVALID_ENCODING = 0x05
ERROR_SIMT = 0x06
ERROR_BARRIER = 0x07

# GETID (opcode 0x30): el campo Y es el `type`. 0 GETTID, 1 GETLANE, 2 GETWARP,
# 3 GETLWARP (LOGICAL_WARP_ID) y 4 GETARG (WARP_ARG). Los demás están reservados.
GETID_LAST_TYPE = 4

# Opcodes de memoria y bytes que tocan. Solo los usa la traza detallada.
ACCESS_SIZE = {0x15: 4, 0x16: 4, 0x18: 1, 0x19: 1, 0x1A: 1, 0x1B: 2, 0x1C: 2, 0x1D: 2}
LOAD_OPCODES = {0x15, 0x18, 0x19, 0x1B, 0x1C}


#: Opcodes que ejecuta la GPU; los demás son ERROR_INVALID_OPCODE.
IMPLEMENTED_OPCODES = {
    0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
    0x09, 0x0A, 0x0C, 0x10, 0x11, 0x12, 0x13, 0x14, 0x15,
    0x16, 0x17, 0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D,
    0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x2C, 0x2D, 0x2E, 0x2F,
    0x30, 0x31, 0x32, 0x33, 0x3E, 0x3F,
}

# Los conjuntos de opcodes van como tuplas o constantes del módulo y no como
# `{...}` en la condición: Python convierte ese literal en una constante, pero
# Codon lo construye en cada llamada (tools/codon/LIMITACIONES.md, l22).
def valid_encoding(instr: int, opcode: int) -> bool:
    """Comprueba los campos reservados de instrucciones conocidas."""
    if opcode in (0x00, 0x32, 0x33, 0x3E, 0x3F):  # NOP, TRAP, HALT
        return (instr & 0x03FFFFFF) == 0
    if opcode in (0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A, 0x0C):
        return (instr & 0x7FF) == 0
    if opcode in (0x10, 0x17):  # MOVI/MOVHI require Y=0
        return ((instr >> 16) & 0x1F) == 0
    if opcode == 0x30:  # GETID: Y es el `type` (0..4) e imm16 = 0
        return (instr & 0xFFFF) == 0 and ((instr >> 16) & 0x1F) <= GETID_LAST_TYPE
    if opcode == 0x2C:  # JAL no tiene registro fuente
        return ((instr >> 16) & 0x1F) == 0
    if opcode == 0x2E:  # JR no tiene ni destino ni inmediato
        return ((instr >> 21) & 0x1F) == 0 and (instr & 0xFFFF) == 0
    return True


def u32(x: int) -> int:
    """Conserva únicamente los 32 bits bajos."""
    return x & MASK32


def s32(x: int) -> int:
    """Interpreta un patrón de 32 bits como entero signed."""
    x &= MASK32
    return x - (1 << 32) if x & 0x80000000 else x


def sign_extend(value: int, bits: int) -> int:
    """Extiende el signo de un entero codificado con 'bits' bits."""
    sign = 1 << (bits - 1)
    mask = (1 << bits) - 1
    value &= mask
    return value - (1 << bits) if value & sign else value


def signed_divide(a: int, b: int) -> int:
    """Divide enteros signed truncando el resultado hacia cero."""
    if b == 0:
        raise ZeroDivisionError("división por cero")

    # Evitamos int(a / b): pasaría por float y podría perder precisión.
    quotient = abs(a) // abs(b)
    if (a < 0) != (b < 0):
        quotient = -quotient
    return quotient


@dataclass
class Fault:
    """Primer fallo arquitectónico; core_id=None indica fallo común del warp."""

    code: int
    pc: int
    warp_id: int
    core_id: int | None
    address: int | None = None


class ExecutionFault(Exception):
    """Fallo de la ISA, capturado exclusivamente en la frontera del warp."""

    # Declarados: sin ellos Codon hace la excepción genérica y `except` no la
    # captura siempre (tools/codon/LIMITACIONES.md, l12).
    code: int
    address: int | None

    def __init__(self, code: int, address: int | None = None):
        super().__init__(f"error 0x{code:02X}")
        self.code = code
        self.address = address


class SimulationError(RuntimeError):
    """Límite o capacidad del simulador; no es un error de la ISA."""


class InstructionLimitExceeded(SimulationError):
    pass


def check_address(memory: bytearray, address: int) -> None:
    if address < 0 or address & 3 or address + 4 > len(memory):
        raise ExecutionFault(ERROR_MEMORY_ACCESS, address)


def read_u32(memory: bytearray, address: int) -> int:
    check_address(memory, address)
    return load_u32(memory, address)




def config_integer(value: object, field: str) -> int:
    """Acepta enteros JSON o cadenas decimales/hexadecimales, nunca booleanos."""
    if type(value) is int:
        return value
    if isinstance(value, str):
        try:
            return int(value, 16 if value.lower().startswith('0x') else 10)
        except ValueError:
            pass
    raise ValueError(f"config: {field} debe ser un entero decimal o hexadecimal")


def config_fields(value: object, allowed: set[str], field: str) -> dict:
    if not isinstance(value, dict):
        raise TypeError(f"config: {field} debe ser un objeto")
    if value.keys() - allowed:
        raise ValueError(f"config: campos desconocidos en {field}")
    return value


def config_warp_size(config: object) -> int:
    config = config_fields(config, {'warp_size', 'warps'}, 'raíz')
    size = config_integer(config.get('warp_size', 8), 'warp_size')
    if size <= 0:
        raise ValueError("config: warp_size debe ser positivo")
    return size


@dataclass
class SimtRegion:
    ssy_pc: int
    join_pc: int
    entry_mask: int
    path_base: int


@dataclass
class SimtPath:
    pending_pc: int
    pending_mask: int


class CPU:
    """Lane: registros privados; evalúa sin modificar el estado arquitectónico.

    No guarda su warp ni el sistema: los recibe `evaluate` y las comprobaciones de
    memoria. Codon no admite ciclos de referencias entre clases
    (tools/codon/LIMITACIONES.md, l08).
    """

    # Declarados porque `reset` crea `regs` y Codon solo infiere los campos
    # asignados en el propio __init__ (l10).
    memory: bytearray
    core_id: int
    regs: list[int]
    # El resultado de `evaluate`, que el warp confirma después. No es estado
    # arquitectónico: vale lo que dejó la última instrucción. Va en campos de la
    # lane, y no en un objeto nuevo con una copia de los registros, porque se
    # evalúa una vez por lane e instrucción (tools/codon/RENDIMIENTO.md).
    rd: int             # registro que escribe; 0 = ninguno (R0 está cableado a cero)
    value: int
    next_pc: int
    halted: bool
    store_size: int     # 0 = sin STORE; si no, 1, 2 o 4 bytes
    store_address: int
    store_value: int    # ya recortado al tamaño

    def __init__(self, memory: bytearray, core_id: int):
        self.memory = memory
        self.core_id = core_id
        self.reset()

    def reset(self) -> None:
        self.regs = [0] * 32
        self.rd = 0
        self.value = 0
        self.next_pc = 0
        self.halted = False
        self.store_size = 0
        self.store_address = 0
        self.store_value = 0

    def read_word(self, address: int, system) -> int:
        """LOAD de 32 bits, por memoria o por un dispositivo MMIO.

        El MMIO no admite accesos parciales ni desalineados, igual que el mux
        del hardware, asi que la comprobacion de alineacion es la misma que la
        de memoria y el fallo tambien.
        """
        device = system.device_for(address)
        if device is None:
            return read_u32(self.memory, address)
        if address & 3:
            raise ExecutionFault(ERROR_MEMORY_ACCESS, address)
        try:
            return device.read(address - device.BASE)
        except RuntimeError as exc:
            raise ExecutionFault(ERROR_MEMORY_ACCESS, address) from exc

    def check_subword(self, address: int, size: int, system) -> None:
        """Valida un acceso de 1 o 2 bytes, de carga o de almacenamiento.

        Es RAM y nada más: el MMIO solo admite palabras de 32 bits alineadas
        (mmio.md §4.1), porque leer un registro tiene efectos y media lectura no
        tiene significado. Una media palabra exige dirección par; un byte, nada.
        """
        if (size == 2 and address & 1
                or system.device_for(address) is not None
                or address < 0 or address + size > len(self.memory)):
            raise ExecutionFault(ERROR_MEMORY_ACCESS, address)

    def check_store(self, address: int, system, writing: bool = True) -> None:
        """Valida el destino de un STORE antes de diferirlo."""
        device = system.device_for(address)
        if device is None:
            check_address(self.memory, address)
        elif address & 3:
            raise ExecutionFault(ERROR_MEMORY_ACCESS, address)
        else:
            try:
                device.validate(address - device.BASE, writing=writing)
            except RuntimeError as exc:
                raise ExecutionFault(ERROR_MEMORY_ACCESS, address) from exc

    def evaluate(self, instr: int, pc: int, warp, system) -> None:
        """Ejecuta `instr` sin tocar los registros: deja el resultado en `rd`,
        `value`, `next_pc`, `halted` y `store_*`, y el warp lo confirma cuando han
        terminado todas sus lanes (un fallo en una no deja a las otras a medias).
        """
        regs = self.regs
        rd = 0
        value = 0
        next_pc = u32(pc + 4)
        halted = False
        store_size = 0
        store_address = 0
        store_value = 0
        opcode = instr >> 26

        if opcode == 0x00:  # NOP
            pass

        elif opcode == 0x10:  # MOVI
            rd = (instr >> 21) & 0x1F
            imm16 = instr & 0xFFFF
            value = u32(sign_extend(imm16, 16))

        elif opcode == 0x17:  # MOVHI
            rd = (instr >> 21) & 0x1F
            imm16 = instr & 0xFFFF
            value = u32(imm16 << 16)

        elif opcode == 0x13:  # ORI
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = instr & 0xFFFF
            value = u32(regs[ra] | imm16)

        elif opcode == 0x01:  # ADD
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            value = u32(regs[ra] + regs[rb])

        elif opcode == 0x11:  # ADDI
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            value = u32(regs[ra] + imm16)

        elif opcode == 0x02:  # SUB
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            value = u32(regs[ra] - regs[rb])

        elif opcode == 0x04:  # AND
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            value = regs[ra] & regs[rb]

        elif opcode == 0x05:  # OR
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            value = regs[ra] | regs[rb]

        elif opcode == 0x06:  # XOR
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            value = regs[ra] ^ regs[rb]

        elif opcode == 0x07:  # SHL
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            # MiniISA usa únicamente los cinco bits bajos de la cantidad.
            value = u32(regs[ra] << (regs[rb] & 0x1F))

        elif opcode == 0x08:  # SHR
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            value = regs[ra] >> (regs[rb] & 0x1F)

        elif opcode == 0x09:  # SAR
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F
            value = u32(s32(regs[ra]) >> (regs[rb] & 0x1F))

        elif opcode == 0x0A:  # MUL
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F

            # Producto 32 x 32; conservamos los 32 bits bajos.
            value = u32(regs[ra] * regs[rb])

        elif opcode == 0x03:  # MULFX signed Q16.16
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F

            # Q16.16 x Q16.16 produce Q32.32. El desplazamiento aritmético
            # restaura la escala Q16.16 antes del wrap final a 32 bits.
            product = s32(regs[ra]) * s32(regs[rb])
            value = u32(product >> 16)

        elif opcode == 0x0C:  # DIV signed
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F

            dividend = s32(regs[ra])
            divisor = s32(regs[rb])
            if divisor == 0:
                raise ExecutionFault(ERROR_DIVISION_BY_ZERO)
            value = u32(signed_divide(dividend, divisor))

        elif opcode == 0x12:  # ANDI
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            # Los inmediatos lógicos se extienden con ceros, no con signo.
            imm16 = instr & 0xFFFF
            value = regs[ra] & imm16

        elif opcode == 0x14:  # XORI
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = instr & 0xFFFF
            value = regs[ra] ^ imm16

        elif opcode == 0x15:  # LOAD
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)

            address = u32(regs[ra] + imm16)
            value = self.read_word(address, system)

        elif opcode == 0x16:  # STORE
            # En STORE, el campo Rd contiene el registro fuente.
            source = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)

            address = u32(regs[ra] + imm16)
            self.check_store(address, system)
            store_size = 4
            store_address = address
            store_value = u32(regs[source])

        elif opcode in (0x18, 0x19, 0x1B, 0x1C):  # LOADB/LOADUB/LOADH/LOADUH
            rd = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            size = 1 if opcode in (0x18, 0x19) else 2
            is_signed = opcode in (0x18, 0x1B)

            address = u32(regs[ra] + imm16)
            self.check_subword(address, size, system)
            raw = load_le(self.memory, address, size)
            value = u32(sign_extend(raw, 8 * size)) if is_signed else raw

        elif opcode in (0x1A, 0x1D):  # STOREB / STOREH
            # Como en STORE, el campo Rd contiene el registro fuente.
            source = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            size = 1 if opcode == 0x1A else 2

            address = u32(regs[ra] + imm16)
            self.check_subword(address, size, system)
            store_size = size
            store_address = address
            store_value = regs[source] & ((1 << (8 * size)) - 1)

        elif opcode == 0x20:  # BEQ
            ra = (instr >> 21) & 0x1F
            rb = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            if regs[ra] == regs[rb]:
                next_pc = u32(next_pc + (imm16 << 2))

        elif opcode == 0x21:  # BNE
            ra = (instr >> 21) & 0x1F
            rb = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            if regs[ra] != regs[rb]:
                next_pc = u32(next_pc + (imm16 << 2))

        elif opcode == 0x22:  # BLT signed
            ra = (instr >> 21) & 0x1F
            rb = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            if s32(regs[ra]) < s32(regs[rb]):
                next_pc = u32(next_pc + (imm16 << 2))

        elif opcode == 0x23:  # BGE signed
            ra = (instr >> 21) & 0x1F
            rb = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            if s32(regs[ra]) >= s32(regs[rb]):
                next_pc = u32(next_pc + (imm16 << 2))

        elif opcode == 0x24:  # BLTU unsigned
            ra = (instr >> 21) & 0x1F
            rb = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            if regs[ra] < regs[rb]:
                next_pc = u32(next_pc + (imm16 << 2))

        elif opcode == 0x25:  # BGEU unsigned
            ra = (instr >> 21) & 0x1F
            rb = (instr >> 16) & 0x1F
            imm16 = sign_extend(instr & 0xFFFF, 16)
            if regs[ra] >= regs[rb]:
                next_pc = u32(next_pc + (imm16 << 2))

        elif opcode == 0x2C:  # JAL: enlace en PC+4 y offset en palabras
            rd = (instr >> 21) & 0x1F
            value = next_pc
            next_pc = u32(next_pc + (sign_extend(instr & 0xFFFF, 16) << 2))

        elif opcode == 0x2D:  # JALR: Ra se lee antes de escribir el enlace
            rd = (instr >> 21) & 0x1F
            value = next_pc
            next_pc = u32(regs[(instr >> 16) & 0x1F] + (sign_extend(instr & 0xFFFF, 16) << 2)) & ~3

        elif opcode == 0x2E:  # JR
            next_pc = u32(regs[(instr >> 16) & 0x1F]) & ~3

        elif opcode == 0x2F:  # BRA
            # BRA dispone de un offset signed de 26 bits porque no usa
            # registros. El offset también está expresado en instrucciones.
            offset26 = sign_extend(instr & 0x03FFFFFF, 26)
            next_pc = u32(next_pc + (offset26 << 2))

        elif opcode == 0x30:  # GETID: GETTID/GETLANE/GETWARP/GETLWARP/GETARG
            rd = (instr >> 21) & 0x1F
            # `valid_encoding` ya garantizó type <= GETID_LAST_TYPE.
            value = (warp.warp_id * warp.num_threads + self.core_id,
                        self.core_id,
                        warp.warp_id,
                        warp.logical_warp_id,
                        warp.arg)[(instr >> 16) & 0x1F]

        elif opcode in (0x33, 0x3F):  # HALT
            halted = True

        elif opcode == 0x3E:  # TRAP
            raise ExecutionFault(ERROR_EXPLICIT_TRAP)

        else:
            raise ExecutionFault(ERROR_INVALID_OPCODE)

        # Nada ha escrito todavía en `regs`: cada instrucción escribe como mucho
        # un registro, y lo hace el warp al confirmar (`Warp.step`). R0 está
        # cableado a cero (1.isa/isa.md, sección 1): `rd == 0` es «no escribe»,
        # así que el descarte queda en un solo sitio y no repartido por las
        # ramas, y las lecturas de R0 valen siempre cero.
        self.rd = rd
        self.value = value
        self.next_pc = next_pc
        self.halted = halted
        self.store_size = store_size
        self.store_address = store_address
        self.store_value = store_value

class Warp:
    """PC compartido; valida todos los hilos antes de confirmar resultados.

    Va detrás de la lane (`CPU`) porque declara `processors: list[CPU]`, y Codon no
    admite referencias adelantadas (tools/codon/LIMITACIONES.md, l07). Como la lane,
    no guarda su SM ni el sistema: `step` recibe el sistema (l08).
    """

    # Declarados porque los inicializa `reset` y Codon solo infiere los campos
    # asignados en el propio __init__ (l10).
    memory: bytearray
    warp_id: int
    num_threads: int
    processors: list[CPU]
    pc: int
    active_mask: int
    live_mask: int
    state: str
    workgroup_id: int
    logical_warp_id: int
    arg: int
    barrier_generation: int
    barrier_key: tuple[int, int] | None
    region_stack: list[SimtRegion]
    path_stack: list[SimtPath]
    instructions_executed: int

    def __init__(self, memory: bytearray, warp_id: int, num_threads: int = 8):
        self.memory = memory
        self.warp_id = warp_id
        self.num_threads = num_threads
        self.processors = [CPU(memory, i) for i in range(num_threads)]
        self.reset()

    @property
    def halted(self) -> bool:
        return self.live_mask == 0

    def reset(self) -> None:
        self.pc = 0
        self.active_mask = 0
        self.live_mask = 0
        self.state = 'READY'
        self.workgroup_id = 0
        # Los lee GETLWARP y GETARG. Valen cero tras el reset, como el resto de la
        # configuración del warp; un lanzador (`configure_warps`, o el MMIO de la
        # carpeta 32) los fija después.
        self.logical_warp_id = 0
        self.arg = 0
        self.barrier_generation = 0
        self.barrier_key = None
        self.region_stack: list[SimtRegion] = []
        self.path_stack: list[SimtPath] = []
        self.instructions_executed = 0
        for processor in self.processors:
            processor.reset()

    def reconverge(self, system) -> None:
        if not self.live_mask:
            self.region_stack.clear()
            self.path_stack.clear()
            self.active_mask = 0
            self.state = 'FINISHED'
            return
        while self.region_stack:
            region = self.region_stack[-1]
            if self.active_mask and self.pc != region.join_pc:
                return
            assert len(self.path_stack) >= region.path_base
            if len(self.path_stack) > region.path_base:
                path = self.path_stack.pop()
                self.pc = path.pending_pc
                self.active_mask = path.pending_mask & self.live_mask
            else:
                self.region_stack.pop()
                self.pc = region.join_pc
                self.active_mask = region.entry_mask & self.live_mask
        assert not self.path_stack
        if not self.active_mask:
            system.stop_with_error(Fault(ERROR_SIMT, self.pc, self.warp_id, None))

    def step(self, system) -> bool:
        if system.halted or self.halted or self.state == 'WAIT_BAR':
            return False
        core_id = None
        try:
            instr = read_u32(self.memory, self.pc)
            opcode = instr >> 26
            if not valid_encoding(instr, opcode):
                raise ExecutionFault(ERROR_INVALID_ENCODING)
            if opcode not in IMPLEMENTED_OPCODES:
                raise ExecutionFault(ERROR_INVALID_OPCODE)
            if opcode == 0x3E:
                raise ExecutionFault(ERROR_EXPLICIT_TRAP)
            if opcode == 0x31:  # Reaffirm the innermost region or open a new one.
                target = u32(self.pc + 4 + sign_extend(instr & 0x3FFFFFF, 26) * 4)
                check_address(self.memory, target)
                if self.region_stack and self.region_stack[-1].ssy_pc == self.pc:
                    if self.region_stack[-1].join_pc != target:
                        raise ExecutionFault(ERROR_SIMT)
                else:
                    if len(self.region_stack) >= system.simt_region_depth:
                        raise ExecutionFault(ERROR_SIMT)
                    self.region_stack.append(SimtRegion(
                        self.pc, target, self.active_mask, len(self.path_stack)))
                self.pc = u32(self.pc + 4)
                self.instructions_executed += 1
                self.reconverge(system)
                return True
            if opcode == 0x32:
                if self.active_mask != self.live_mask:
                    raise ExecutionFault(ERROR_BARRIER)
                key = (self.pc, self.barrier_generation)
                if any(w.workgroup_id == self.workgroup_id and w.state == 'WAIT_BAR'
                       and w.barrier_key != key for w in system.streaming_multiprocessor.warps):
                    raise ExecutionFault(ERROR_BARRIER)
                self.state = 'WAIT_BAR'
                self.barrier_key = key
                self.instructions_executed += 1
                system.streaming_multiprocessor.release_barriers(system)
                self.reconverge(system)
                return True
            if opcode == 0x15:  # LOAD: validar el warp antes de efectos MMIO.
                for processor in self.processors:
                    if self.active_mask & (1 << processor.core_id):
                        core_id = processor.core_id
                        address = u32(processor.regs[(instr >> 16) & 31]
                                      + sign_extend(instr & 0xFFFF, 16))
                        processor.check_store(address, system, writing=False)
            for processor in self.processors:
                if self.active_mask & (1 << processor.core_id):
                    core_id = processor.core_id
                    processor.evaluate(instr, self.pc, self, system)
        except ExecutionFault as exc:
            system.stop_with_error(
                Fault(exc.code, self.pc, self.warp_id, core_id, exc.address)
            )
            return False

        # Las lanes evaluadas, que son las que confirman: la divergencia puede
        # cambiar `active_mask` antes.
        evaluated = self.active_mask
        next_pc = -1
        diverged = False
        for processor in self.processors:
            if evaluated & (1 << processor.core_id):
                if next_pc < 0:
                    next_pc = processor.next_pc
                elif processor.next_pc != next_pc:
                    diverged = True
        if next_pc < 0:
            # Ninguna lane activa: reconverge ya lo trata como error SIMT.
            system.stop_with_error(Fault(ERROR_SIMT, self.pc, self.warp_id, None))
            return False
        if diverged:
            # JALR/JR con destinos distintos por lane: no hay uno que apilar (como en
            # gpu_sm.v de la 37 y en el simulador de ciclos 25).
            if opcode in (0x2D, 0x2E) or not self.region_stack:
                system.stop_with_error(Fault(ERROR_SIMT, self.pc, self.warp_id, None))
                return False
            # Un salto condicional: unas lanes siguen y otras saltan, al mismo
            # destino.
            region = self.region_stack[-1]
            fallthrough = u32(self.pc + 4)
            target = fallthrough
            taken = 0
            for processor in self.processors:
                if evaluated & (1 << processor.core_id) and processor.next_pc != fallthrough:
                    target = processor.next_pc
                    taken |= 1 << processor.core_id
            if target == region.join_pc:
                self.active_mask &= ~taken
                next_pc = fallthrough
            elif fallthrough == region.join_pc:
                self.active_mask = taken
                next_pc = target
            else:
                if len(self.path_stack) >= system.simt_path_depth:
                    system.stop_with_error(Fault(ERROR_SIMT, self.pc, self.warp_id, None))
                    return False
                self.path_stack.append(SimtPath(target, taken))
                self.active_mask &= ~taken
                next_pc = fallthrough
        for processor in self.processors:
            if not evaluated & (1 << processor.core_id):
                continue
            if processor.rd:
                processor.regs[processor.rd] = processor.value
            size = processor.store_size
            if size:
                address = processor.store_address
                value = processor.store_value
                # Las escrituras se aplican en orden de lane. Si varios lanes
                # escriben el MISMO registro MMIO en la misma instruccion, gana
                # el ultimo, que es una de las ordenes posibles: el hardware las
                # serializa por el bus y tampoco promete cual. Un kernel que
                # dependa de eso esta mal escrito en las dos partes.
                device = system.device_for(address)
                if device is not None:
                    # Un registro puede rechazar el DATO, no solo la
                    # direccion: desde MMIO v2 una base de framebuffer
                    # desalineada es error en vez de truncarse (§9.2), y eso
                    # `check_store` no lo puede ver --valida antes de tener el
                    # valor--. Sin este try la excepcion salia del simulador
                    # en vez de convertirse en el fallo del kernel.
                    try:
                        device.write(address - device.BASE, value)
                    except RuntimeError:
                        system.stop_with_error(
                            Fault(ERROR_MEMORY_ACCESS, self.pc, self.warp_id,
                                  processor.core_id, address))
                        return False
                elif size == 4:
                    store_u32(self.memory, address, value)
                else:
                    # STOREB/STOREH solo tocan sus bytes: dos lanes que escriben
                    # bytes distintos de la misma palabra aciertan las dos, que es
                    # lo que hace el `wstrb` en el fabric. Si escriben el mismo
                    # byte gana la ultima en orden de lane.
                    store_le(self.memory, address, size, value)
            if processor.halted:
                self.active_mask &= ~(1 << processor.core_id)
                self.live_mask &= ~(1 << processor.core_id)
        self.pc = next_pc
        self.instructions_executed += 1
        self.reconverge(system)
        system.streaming_multiprocessor.release_barriers(system)
        return True


class StreamingMultiprocessor:
    """Planificador determinista: una instrucción de warp por paso."""

    # Declarados: `System` declara un campo de esta clase (l19).
    memory: bytearray
    num_warps: int
    warp_size: int
    warps: list[Warp]
    next_warp: int
        # `filename` es un `Path` (sin anotar: el núcleo no importa pathlib).

    def __init__(self, memory: bytearray,
                 num_warps: int = 8, warp_size: int = 8):
        self.memory = memory
        self.num_warps = num_warps
        self.warp_size = warp_size
        self.warps = [Warp(memory, i, warp_size) for i in range(num_warps)]
        self.next_warp = 0

    def reset(self) -> None:
        self.next_warp = 0
        for warp in self.warps:
            warp.reset()

    def step(self, system) -> bool:
        if system.halted:
            return False
        for offset in range(self.num_warps):
            index = (self.next_warp + offset) % self.num_warps
            warp = self.warps[index]
            if not warp.halted and warp.state == 'READY':
                completed = self._step_warp(warp, system)
                self.next_warp = (index + 1) % self.num_warps
                return completed
        return False

    def release_barriers(self, system) -> None:
        # Se llama tras cada instrucción de warp y casi nunca hay nadie esperando:
        # entonces no hay nada que liberar y se evita construir grupos y listas
        # (en Codon era la mitad del tiempo de la GPU).
        for w in self.warps:
            if w.state == 'WAIT_BAR':
                break
        else:
            return
        for group in {w.workgroup_id for w in self.warps}:
            participants = [w for w in self.warps if w.workgroup_id == group and not w.halted]
            if participants and all(w.state == 'WAIT_BAR' for w in participants):
                for w in participants:
                    w.state = 'READY'
                    w.pc = u32(w.pc + 4)
                    w.barrier_generation += 1
                    w.reconverge(system)

    def _step_warp(self, warp, system) -> bool:
        trace = system.trace
        if trace is None:
            return warp.step(system)
        pc, mask = warp.pc, warp.active_mask
        word = None
        if 0 <= pc and not pc & 3 and pc + 4 <= len(self.memory):
            word = load_u32(self.memory, pc)
        before = {}
        if trace.detail and trace.recording:
            before = {lane.core_id: lane.regs.copy() for lane in warp.processors
                      if mask & (1 << lane.core_id)}
        try:
            completed = warp.step(system)
        except SimulationError as exc:
            trace(TraceEvent(warp.warp_id, pc, mask, warp.live_mask, word, warp.pc, f'SIMULADOR: {exc}'))
            raise
        details = []
        fault = system.fault
        if fault:
            outcome = f'ERROR 0x{fault.code:02X} hilo={fault.core_id}'
            if fault.address is not None:
                outcome += f' direccion=0x{fault.address:08X}'
            outcome += ' (sin commit)'
        else:
            outcome = 'FINISHED' if warp.halted else warp.state
            for lane_id, regs in before.items():
                after = warp.processors[lane_id].regs
                for number, (old, new) in enumerate(zip(regs, after)):
                    if old != new:
                        details.append(f'T{lane_id} R{number}: 0x{old:08X} -> 0x{new:08X}')
                if word is not None and word >> 26 in ACCESS_SIZE:
                    op, rd, ra = word >> 26, (word >> 21) & 31, (word >> 16) & 31
                    address = u32(regs[ra] + sign_extend(word & 0xFFFF, 16))
                    is_load = op in LOAD_OPCODES
                    value = (after[rd] if is_load
                             else regs[rd] & ((1 << 8 * ACCESS_SIZE[op]) - 1))
                    details.append(f'T{lane_id} {"READ" if is_load else "WRITE"} '
                                   f'[0x{address:08X}] = 0x{value:08X}')
        trace(TraceEvent(warp.warp_id, pc, mask, warp.live_mask, word, warp.pc, outcome, tuple(details)))
        return completed


class System:
    """Memoria compartida y único registro de fallo de la GPU.

    Va la última, detrás de lo que contiene, porque declara sus campos (Codon no
    admite referencias adelantadas, l07). Por la misma razón los métodos de la
    lane, `Warp` y `StreamingMultiprocessor` reciben `system` sin anotar.
    """

    # Declarados porque `cpu_gpu_core._GpuSystem` hereda de esta clase, y Codon no
    # admite heredar de una clase con los campos inferidos
    # (tools/codon/LIMITACIONES.md, l19).
    simt_region_depth: int
    simt_path_depth: int
    memory: bytearray
    fault: Fault | None
    trace: TextTrace | None
    video: VideoDevice | None
    serial: SerialDevice | None
    input: InputDevice | None
    peripheral_halted: bool
    sysid: SysIdDevice
    streaming_multiprocessor: StreamingMultiprocessor

    def __init__(self, memory_size: int = 32 * 1024 * 1024,
                 num_warps: int = 8, warp_size: int = 8, *,
                 simt_region_depth: int = MAX_SIMT_REGIONS,
                 simt_path_depth: int = MAX_SIMT_PATHS,
                 video: VideoDevice | None = None,
                 serial: SerialDevice | None = None,
                 input_device: InputDevice | None = None):
        if memory_size <= 0 or num_warps <= 0 or warp_size <= 0:
            raise ValueError("memoria, número de warps y tamaño de warp deben ser positivos")
        if num_warps > MAX_WARPS:
            raise ValueError("se admiten como máximo 8 warps")
        for depth in (simt_region_depth, simt_path_depth):
            if type(depth) is not int or depth <= 0:
                raise ValueError("las profundidades SIMT deben ser enteros positivos")
        self.simt_region_depth = simt_region_depth
        self.simt_path_depth = simt_path_depth
        self.memory = bytearray(memory_size)
        self.fault: Fault | None = None
        self.trace: TextTrace | None = None
        # Sin dispositivo de vídeo, 0x80000000 sigue siendo memoria fuera de
        # rango y da ERROR_MEMORY_ACCESS, que es lo que hacían los casos de
        # siempre.
        self.video = video
        if video is not None:
            # En la GPU para el bit de GPU de HALT_TARGET, no el de CPU (§9.6).
            video.halt_owner = VideoDevice.HALT_TARGET_GPU
        self.serial = serial
        self.input = input_device
        self.peripheral_halted = False
        # El bloque de identificacion existe SIEMPRE, a diferencia del video:
        # es el unico dispositivo que toda carpeta con juego de comandos tiene,
        # asi que un kernel que se identifique tiene que poder probarse aqui.
        self.sysid = SysIdDevice(folder=11, isa_profile=SIMULATOR_ISA_PROFILE)
        self.streaming_multiprocessor = StreamingMultiprocessor(
            self.memory, num_warps, warp_size
        )

    def device_for(self, address: int) -> MmioDevice | None:
        """Qué dispositivo MMIO, si alguno, responde a esta dirección.

        Uno por uno y no con un bucle sobre una tupla: son clases distintas, y
        Codon solo admite devolverlas como su base común
        (tools/codon/LIMITACIONES.md, l11).
        """
        if self.video is not None and self.video.contains(address):
            return self.video
        if self.serial is not None and self.serial.contains(address):
            return self.serial
        if self.input is not None and self.input.contains(address):
            return self.input
        if self.sysid.contains(address):
            return self.sysid
        return None

    def tick_devices(self) -> None:
        """Un paso del reloj sintético de los dispositivos."""
        if self.serial is not None:
            self.serial.tick()
        if self.input is not None:
            self.input.tick()
        if self.video is not None:
            self.video.tick()
            if self.video.halt_request:
                self.peripheral_halted = True

    @property
    def halted(self) -> bool:
        return self.peripheral_halted or self.error or all(w.halted for w in self.streaming_multiprocessor.warps)

    @property
    def error(self) -> bool:
        return self.fault is not None

    @property
    def error_code(self) -> int:
        return self.fault.code if self.fault else ERROR_NONE

    @property
    def error_pc(self) -> int:
        return self.fault.pc if self.fault else 0

    @property
    def instructions_executed(self) -> int:
        return sum(w.instructions_executed for w in self.streaming_multiprocessor.warps)

    def reset(self) -> None:
        """Borra memoria in situ y deja todos los warps sin lanzar."""
        self.peripheral_halted = False
        self.memory[:] = bytes(len(self.memory))
        self.fault = None
        self.streaming_multiprocessor.reset()

    def load_program(self, data: bytes, address: int = 0, *, launch: bool = True) -> None:
        """Carga memoria; por defecto lanza todos los hilos por compatibilidad."""
        if address & 3:
            raise ValueError("dirección de carga no alineada")
        if not data or len(data) & 3:
            raise ValueError("el programa debe contener instrucciones completas")
        if address < 0 or address + len(data) > len(self.memory):
            raise ValueError("programa fuera de memoria")
        self.memory[address:address + len(data)] = data
        self.fault = None
        self.streaming_multiprocessor.reset()
        if launch:
            for warp in self.streaming_multiprocessor.warps:
                warp.pc = address
                warp.active_mask = warp.live_mask = (1 << warp.num_threads) - 1

    def configure_warps(self, config: object) -> None:
        """Valida todo el lanzamiento antes de reiniciar/aplicar estado; no toca memoria."""
        config = config_fields(config, {'warp_size', 'warps'}, 'raíz')
        size = config_warp_size(config)
        sm = self.streaming_multiprocessor
        if size != sm.warp_size:
            raise ValueError("config: warp_size no coincide con el sistema")
        entries = config.get('warps')
        if not isinstance(entries, list):
            raise TypeError("config: warps debe ser una lista")
        states = {}
        for index, entry in enumerate(entries):
            label = f'warps[{index}]'
            entry = config_fields(entry, {'id', 'enabled', 'pc', 'active_mask', 'workgroup_id',
                                          'logical_warp_id', 'arg'}, label)
            warp_id = config_integer(entry.get('id'), f'{label}.id')
            if not 0 <= warp_id < sm.num_warps:
                raise ValueError(f"config: {label}.id fuera de rango (0..{sm.num_warps - 1})")
            if warp_id in states:
                raise ValueError(f"config: id de warp duplicado: {warp_id}")
            enabled = entry.get('enabled', True)
            if type(enabled) is not bool:
                raise ValueError(f"config: {label}.enabled debe ser booleano")
            pc = config_integer(entry.get('pc', 0), f'{label}.pc')
            if pc < 0 or pc > MASK32 or pc & 3 or pc + 4 > len(self.memory):
                raise ValueError(f"config: {label}.pc no alineado o fuera de memoria")
            mask = config_integer(entry.get('active_mask', (1 << size) - 1),
                                  f'{label}.active_mask')
            if mask < 0 or mask >= (1 << size) or (enabled and mask == 0):
                raise ValueError(f"config: {label}.active_mask fuera de rango o vacío en warp habilitado")
            group = config_integer(entry.get('workgroup_id', 0), f'{label}.workgroup_id')
            if group < 0:
                raise ValueError("config: workgroup_id debe ser no negativo")
            # Los valores de GETLWARP y GETARG son palabras de 32 bits.
            values = []
            for name in ('logical_warp_id', 'arg'):
                value = config_integer(entry.get(name, 0), f'{label}.{name}')
                if not 0 <= value <= MASK32:
                    raise ValueError(f"config: {label}.{name} debe caber en 32 bits sin signo")
                values.append(value)
            states[warp_id] = (pc, mask if enabled else 0, group, *values)
        self.fault = None
        self.peripheral_halted = False
        sm.reset()
        for warp_id, (pc, mask, group, logical_id, arg) in states.items():
            warp = sm.warps[warp_id]
            warp.pc = pc
            warp.active_mask = warp.live_mask = mask
            warp.workgroup_id = group
            warp.logical_warp_id = logical_id
            warp.arg = arg

    def step(self) -> bool:
        """Emite como máximo una instrucción de un warp (round-robin)."""
        retired = self.streaming_multiprocessor.step(self)
        if retired:
            self.tick_devices()
        return retired

    def run(self, max_instructions: int = 100_000_000) -> None:
        """Límite absoluto de instrucciones de warp completadas desde la carga."""
        if max_instructions < 0:
            raise ValueError("el límite de instrucciones no puede ser negativo")
        while not self.halted:
            if self.instructions_executed >= max_instructions:
                raise InstructionLimitExceeded(
                    f"límite de {max_instructions} instrucciones de warp alcanzado"
                )
            self.step()

    def stop_with_error(self, fault: Fault) -> None:
        if self.fault is None:
            self.fault = fault

    def dump_memory(self, address: int, size: int, filename) -> None:
        if address < 0 or size < 0 or address + size > len(self.memory):
            raise ValueError("volcado fuera de memoria")
        filename.write_bytes(self.memory[address:address + size])
