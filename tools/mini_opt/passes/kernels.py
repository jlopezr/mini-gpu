"""Kernels de GPU: `__kernel_<nombre>` es una funcion que arranca una lane"""
from __future__ import annotations

from ..flow import Block, build_cfg, free_register, live_after, live_in_entry, liveness
from ..isa import ARG_REGS, LOADS, STACK, instr, number, reg, reg_of
from ..model import Function, Line, OptError, Unit
from ..registry import register_pass

KERNEL_PREFIX = "__kernel_"

# Bytes de pila por lane y simbolo de la zona; los define el runtime de C (gpu.c) y
# tienen que coincidir con `GPU_STACK_PER_LANE` de gpu.h.
GPU_STACK_PER_LANE = 512
GPU_STACK_SYMBOL = "__gpu_stack"

KERNEL_PARAMS = 4                       # R1..R4, del bloque de argumentos +8, +12, +16, +20

SHIFT_IMMEDIATE = {"SHLI": "SHL", "SHRI": "SHR", "SARI": "SAR"}

# Lo que ejecutan las lanes de la GPU en cada prototipo. `LI` es un pseudo del ensamblador.
GPU_ISAS = {
    "36": {"NOP", "ADD", "SUB", "MULFX", "AND", "OR", "XOR", "SHL", "SHR", "SAR", "MUL", "DIV",
           "MOVI", "ADDI", "ANDI", "ORI", "XORI", "LI", "MOVHI", "LOAD", "STORE", "LOADB",
           "LOADUB", "STOREB", "LOADH", "LOADUH", "STOREH", "BEQ", "BNE", "BLT", "BGE",
           "BLTU", "BGEU", "BRA", "GETTID", "GETLANE", "GETWARP", "GETLWARP", "GETARG",
           "SSY", "BAR", "EXIT", "TRAP", "HALT"},
}
GPU_ISA = "36"


def stack_adjust(line: Line) -> int | None:
    """N de `ADDI R30, R30, N` (lo que lcc hace al abrir y cerrar el marco), o None."""
    if (line.kind == "instr" and line.op == "ADDI" and len(line.args) == 3
            and reg_of(line.args[0]) == STACK and reg_of(line.args[1]) == STACK):
        return number(line.args[2])
    return None


def drop_frame(function: Function, stats: dict) -> bool:
    """Quita de un kernel lo que lcc guarda y restaura de los registros preservados.

    El prologo de lcc (`ADDI R30,R30,-N` y un `STORE Rk,R30,off` por cada R16..R29 que usa) y el
    epilogo que lo deshace (los `LOAD` y el `ADDI R30,R30,N`) devuelven esos registros a quien
    llamo. Un kernel no vuelve a nadie: acaba con EXIT. Siempre se borran esos guardados y
    restauraciones (en la GPU cada uno es un acceso a la pila de la lane, con direcciones
    separadas por lane, es decir sin coalescer). Si tras eso NADA mas toca R30 (ni un local ni un
    derrame), se borra tambien el marco y el kernel no necesita pila.

    Devuelve True si ya no queda ninguna referencia a R30, y False si el kernel usa la pila de
    verdad (y se queda con su marco para los locales)."""
    refs = [l for l in function.body
            if l.kind == "instr" and any(reg_of(a) == STACK for a in l.args)]
    if not refs:
        return True
    first = refs[0]
    opening = stack_adjust(first)
    if opening is None or opening >= 0:
        return False
    size = -opening
    saves: dict[int, int] = {}                  # desplazamiento -> registro preservado
    for line in refs[1:]:
        if line.op != "STORE" or reg_of(line.args[1]) != STACK:
            break
        register, offset = reg_of(line.args[0]), number(line.args[2])
        if (register is None or not 16 <= register <= 29 or offset is None or offset in saves
                or not 0 <= offset < size):
            break
        saves[offset] = register
    remove = list(refs[1:1 + len(saves)])
    for line in refs[1 + len(saves):]:
        offset = number(line.args[2]) if len(line.args) == 3 else None
        if (line.op == "LOAD" and reg_of(line.args[1]) == STACK and offset is not None
                and saves.get(offset) == reg_of(line.args[0])):
            remove.append(line)
    rest = [l for l in refs[1:] if all(l is not r for r in remove)]
    epilogue = [l for l in rest if stack_adjust(l) == size]
    only_frame = len(rest) == len(epilogue)
    if only_frame:
        remove += [first] + epilogue
    if not remove:
        return False
    gone = {id(line) for line in remove}
    function.body = [line for line in function.body if id(line) not in gone]
    key = "kernels.frames" if only_frame else "kernels.saves"
    stats[key] = stats.get(key, 0) + 1
    return only_frame


def expand_immediate_shifts(blocks: list[Block], where: str, stats: dict) -> None:
    """La GPU solo tiene los desplazamientos con registro: `SHLI d,a,k` -> `MOVI t,k ; SHL d,a,t`."""
    live_out = liveness(blocks)
    for block in blocks:
        i = 0
        while i < len(block.lines):
            line = block.lines[i]
            if line.kind == "instr" and line.op in SHIFT_IMMEDIATE:
                d, a, k = line.args
                busy = live_after(block, live_out[block.index], i) | {reg(d), reg(a)}
                t = free_register(busy, where)
                block.lines[i:i + 1] = [instr("MOVI", f"R{t}", k),
                                        instr(SHIFT_IMMEDIATE[line.op], d, a, f"R{t}")]
                stats["kernels.shifts"] = stats.get("kernels.shifts", 0) + 1
                i += 2
            else:
                i += 1


def check_isa(function: Function, where: str) -> None:
    allowed = GPU_ISAS[GPU_ISA]
    for line in function.body:
        if line.kind == "instr" and line.op not in allowed:
            raise OptError(f"{where}: la GPU del prototipo {GPU_ISA} no ejecuta {line.op} "
                           f"({line.render()})")


def check_parameter_count(function: Function, where: str) -> None:
    """Los parametros son R1..R4. Mas de cuatro irian a la pila del llamador, que un kernel no tiene."""
    frame = next((-(stack_adjust(l) or 0) for l in function.body if stack_adjust(l) is not None), 0)
    for line in function.body:
        if line.kind == "instr" and line.op in LOADS and reg_of(line.args[1]) == STACK:
            offset = number(line.args[2]) or 0
            if offset >= frame > 0:
                raise OptError(f"{where}: un kernel admite {KERNEL_PARAMS} parametros como maximo "
                               "(pasa un puntero a una estructura)")


def entry_code(function: Function, uses_stack: bool) -> list[Line]:
    """Lo que va justo despues de la etiqueta: la pila de la lane (solo si se usa) y los parametros."""
    blocks = build_cfg(function)
    params = sorted(r for r in live_in_entry(blocks, liveness(blocks)) if r in ARG_REGS)
    size = GPU_STACK_PER_LANE
    entry = ([instr("GETTID", "R5"), instr("MOVI", "R6", str(size)), instr("MUL", "R5", "R5", "R6"),
              instr("LI", "R30", f"{GPU_STACK_SYMBOL}+{size}"), instr("ADD", "R30", "R30", "R5")]
             if uses_stack else [])
    if params:
        entry.append(instr("GETARG", "R5"))
        entry += [instr("LOAD", f"R{r}", "R5", str(8 + 4 * (r - 1))) for r in params]
    return entry


@register_pass("kernels", "__kernel_*: desplazamientos con registro, ISA de la GPU, entrada (pila de "
                          "lane y parametros desde GETARG) y EXIT en vez de JR R31")
def pass_kernels(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        if not function.name.startswith(KERNEL_PREFIX):
            continue
        where = f"{unit.path}: {function.name}"
        for line in function.body:              # el retorno de un kernel es parar la lane
            if line.kind == "instr" and line.op == "JR" and [a.upper() for a in line.args] == ["R31"]:
                line.op, line.args = "EXIT", []
        blocks = build_cfg(function)
        expand_immediate_shifts(blocks, where, stats)
        function.body = [line for block in blocks for line in block.lines]
        check_isa(function, where)
        check_parameter_count(function, where)
        uses_stack = not drop_frame(function, stats)
        function.body[1:1] = entry_code(function, uses_stack)   # justo despues de la etiqueta de la funcion
        stats["kernels"] = stats.get("kernels", 0) + 1
