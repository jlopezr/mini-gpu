"""Intrinsecos de GPU: variables `__gpu_*` que el C lee como si fueran normales

Es el equivalente a `threadIdx` / `__syncthreads` de CUDA sin tocar `rcc`: el C declara
`extern volatile int __gpu_tid;` y lo lee como una variable, y lcc lo compila como la carga de
una direccion mas un `LOAD`. El pase convierte el par `LI r,__gpu_tid ; LOAD d,r,0` en
`GETTID d` (y `__gpu_lane`, `__gpu_warp`, `__gpu_lwarp`, `__gpu_arg` en su `GET*`). Escribir
`__gpu_bar = 0;` pasa a `BAR`. `__gpu_nthreads` es compuesto: lee del bloque de argumentos
(`GETARG`) el numero de warps y de lanes y los multiplica.

La direccion puede haberse cargado en otro bloque, asi que se sigue con un analisis de
registros que contienen la direccion de un intrinseco por todos los caminos. Despues se borra
la carga de la direccion y la declaracion `.extern`. Si la direccion se usa para otra cosa
(se toma `&__gpu_tid`, se suma...), no se puede reescribir y es un error.

Para anadir otro intrinseco basta una entrada en `INTRINSIC_LOADS` o `INTRINSIC_STORES`."""
from __future__ import annotations

from ..flow import Block, build_cfg, forward_must, free_register, live_after, liveness
from ..isa import defs_uses, instr, reg, reg_of
from ..model import Function, Line, OptError, Unit, directive_parts
from ..registry import register_pass

# Variables especiales -> instruccion. `LI r,sim ; LOAD d,r,0` => `OP d`.
INTRINSIC_LOADS = {
    "__gpu_tid": "GETTID",
    "__gpu_lane": "GETLANE",
    "__gpu_warp": "GETWARP",
    "__gpu_lwarp": "GETLWARP",
    "__gpu_arg": "GETARG",
}

# Compuestos: se leen como una variable pero valen mas de una instruccion.
#   __gpu_nthreads = nwarps * nlanes del job, del bloque de argumentos (+0 y +4).
COMPOSITE_LOADS = {"__gpu_nthreads"}

# Escrituras: `LI r,sim ; STORE v,r,0` => `OP` (el valor se descarta).
INTRINSIC_STORES = {
    "__gpu_bar": "BAR",
    "__noalias_mark": "NOALIAS",            # `__noalias_mark = (int)p;` -> `NOALIAS Rp` (lo gasta y borra el pase noalias)
}

# Las escrituras que llevan el valor escrito como operando de la instruccion que las sustituye.
STORES_WITH_VALUE = {"__noalias_mark"}

INTRINSIC_NAMES = set(INTRINSIC_LOADS) | set(INTRINSIC_STORES) | COMPOSITE_LOADS


def is_address_load(line: Line) -> bool:
    """`LI r, __gpu_x`: carga la direccion de un intrinseco."""
    return line.kind == "instr" and line.op == "LI" and len(line.args) == 2 and line.args[1] in INTRINSIC_NAMES


def track_addresses(state: dict[int, str], line: Line) -> None:
    """Que registros contienen ahora la direccion de que intrinseco."""
    for written in defs_uses(line)[0]:
        state.pop(written, None)
    if is_address_load(line):
        state[reg(line.args[0])] = line.args[1]


def accessed_symbol(line: Line, state: dict[int, str]) -> str | None:
    """El intrinseco al que accede `LOAD d, r, 0` o `STORE v, r, 0` con `r` = su direccion."""
    if line.op not in ("LOAD", "STORE") or len(line.args) != 3 or line.args[2] not in ("0", "+0"):
        return None
    base = reg_of(line.args[1])
    return state.get(base) if base is not None else None


def replacement(line: Line, symbol: str, state: dict[int, str], block: Block, live_out: set[int],
                position: int, where: str) -> list[Line] | None:
    """Las instrucciones que sustituyen a una lectura o escritura de un intrinseco."""
    if line.op == "LOAD" and symbol in INTRINSIC_LOADS:
        return [instr(INTRINSIC_LOADS[symbol], line.args[0])]
    if line.op == "LOAD" and symbol in COMPOSITE_LOADS:
        d = line.args[0]
        busy = live_after(block, live_out, position) | {reg(d)}
        t = free_register(busy, where)
        return [instr("GETARG", d), instr("LOAD", f"R{t}", d, "0"),
                instr("LOAD", d, d, "4"), instr("MUL", d, d, f"R{t}")]
    if line.op == "STORE" and symbol in INTRINSIC_STORES and reg_of(line.args[0]) not in state:
        if symbol in STORES_WITH_VALUE:
            return [instr(INTRINSIC_STORES[symbol], line.args[0])]
        return [instr(INTRINSIC_STORES[symbol])]
    return None


def rewrite_accesses(blocks: list[Block], where: str, stats: dict) -> None:
    live_out = liveness(blocks)
    for block, entering in zip(blocks, forward_must(blocks, track_addresses)):
        state = dict(entering)
        i = 0
        while i < len(block.lines):
            line = block.lines[i]
            if line.kind != "instr":
                i += 1
                continue
            symbol = accessed_symbol(line, state)
            new = replacement(line, symbol, state, block, live_out[block.index], i, where) if symbol else None
            if new is not None:
                block.lines[i:i + 1] = new
                stats["intrinsics"] = stats.get("intrinsics", 0) + 1
                i += len(new)
            else:
                i += 1
            track_addresses(state, line)


def drop_address_loads(function: Function, where: str) -> None:
    """La direccion cargada ya no la usa nadie: fuera. Si algo mas la usa (se tomo la direccion,
    se sumo...), no se puede reescribir."""
    blocks = build_cfg(function)
    live_out = liveness(blocks)
    for block in blocks:
        i = 0
        while i < len(block.lines):
            line = block.lines[i]
            if is_address_load(line):
                register = reg(line.args[0])
                if register in live_after(block, live_out[block.index], i):
                    symbol = line.args[1]
                    raise OptError(f"{where}: '{symbol}' solo se puede leer"
                                   f"{' o escribir' if symbol in INTRINSIC_STORES else ''} como "
                                   f"variable entera (R{register} sigue vivo tras leer {symbol})")
                del block.lines[i]
                continue
            i += 1
    function.body = [line for block in blocks for line in block.lines]


def is_intrinsic_declaration(chunk: object) -> bool:
    """`.extern __gpu_x`: ya no designa nada."""
    if not (isinstance(chunk, Line) and chunk.kind == "directive"):
        return False
    parts = directive_parts(chunk)
    return len(parts) > 1 and parts[0].lower() == ".extern" and parts[1] in INTRINSIC_NAMES


@register_pass("intrinsics", "variables __gpu_* -> GETTID/GETLANE/GETWARP/GETLWARP/GETARG/BAR")
def pass_intrinsics(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        where = f"{unit.path}: {function.name}"
        blocks = build_cfg(function)
        if not blocks:
            continue
        rewrite_accesses(blocks, where, stats)
        function.body = [line for block in blocks for line in block.lines]
        drop_address_loads(function, where)
    unit.chunks = [c for c in unit.chunks if not is_intrinsic_declaration(c)]
    for function in unit.functions():                  # ninguna referencia suelta a un intrinseco
        for line in function.body:
            if line.kind == "instr" and any(a in INTRINSIC_NAMES for a in line.args):
                raise OptError(
                    f"{unit.path}: {function.name}: uso no soportado de un intrinseco: {line.render()}")
