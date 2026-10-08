"""Pase `intrinsics`: las variables `__gpu_*` pasan a `GETTID`, `GETLANE`... y `__gpu_bar = 0;` a `BAR`."""
from __future__ import annotations

from ..flow import Block, build_cfg, free_register, live_after, liveness
from ..isa import defs_uses, instr, reg_of
from ..model import Line, OptError, Unit, directive_parts
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
}


def reaching_symbols(blocks: list[Block], names: set[str]) -> list[dict[int, str]]:
    """Por bloque, que registros contienen a la entrada la direccion de un intrinseco
    (`LI r, __gpu_x`). Solo se conserva lo que llega igual por todos los caminos.
    lcc carga la direccion una vez y la reutiliza para varias lecturas, a veces desde
    otro bloque (antes de un bucle, por ejemplo)."""
    entry: list[dict[int, str] | None] = [None] * len(blocks)
    entry[0] = {}
    changed = True
    while changed:
        changed = False
        for block in blocks:
            if entry[block.index] is None:
                continue
            current = dict(entry[block.index])
            for line in block.lines:
                if line.kind == "instr":
                    defs, _ = defs_uses(line)
                    for d in defs:
                        current.pop(d, None)
                    if line.op == "LI" and len(line.args) == 2 and line.args[1] in names:
                        current[reg_of(line.args[0])] = line.args[1]
            for s in block.succ:
                if entry[s] is None:
                    entry[s] = dict(current)
                    changed = True
                else:
                    merged = {r: sym for r, sym in entry[s].items() if current.get(r) == sym}
                    if merged != entry[s]:
                        entry[s] = merged
                        changed = True
    return [e if e is not None else {} for e in entry]


@register_pass("intrinsics", "variables __gpu_* -> GETTID/GETLANE/GETWARP/GETLWARP/GETARG/BAR")
def pass_intrinsics(unit: Unit, stats: dict) -> None:
    names = set(INTRINSIC_LOADS) | set(INTRINSIC_STORES) | COMPOSITE_LOADS
    for function in unit.functions():
        where = f"{unit.path}: {function.name}"
        blocks = build_cfg(function)
        if not blocks:
            continue
        live_out = liveness(blocks)
        held = reaching_symbols(blocks, names)
        for block in blocks:
            current = dict(held[block.index])
            i = 0
            while i < len(block.lines):
                line = block.lines[i]
                if line.kind != "instr":
                    i += 1
                    continue
                defs, _ = defs_uses(line)
                new = None
                sym = current.get(reg_of(line.args[1])) if line.op in ("LOAD", "STORE") and len(line.args) == 3 \
                    and line.args[2] in ("0", "+0") and reg_of(line.args[1]) is not None else None
                if sym is not None and line.op == "LOAD" and (sym in INTRINSIC_LOADS or sym in COMPOSITE_LOADS):
                    d = line.args[0]
                    if sym in COMPOSITE_LOADS:
                        after = live_after(block, live_out[block.index], i)
                        t = free_register(after | {reg_of(d)}, where)
                        new = [instr("GETARG", d), instr("LOAD", f"R{t}", d, "0"),
                               instr("LOAD", d, d, "4"), instr("MUL", d, d, f"R{t}")]
                    else:
                        new = [instr(INTRINSIC_LOADS[sym], d)]
                elif sym is not None and line.op == "STORE" and sym in INTRINSIC_STORES \
                        and reg_of(line.args[0]) not in current:
                    new = [instr(INTRINSIC_STORES[sym])]
                if new is not None:
                    block.lines[i:i + 1] = new
                    stats["intrinsics"] = stats.get("intrinsics", 0) + 1
                    i += len(new)
                else:
                    i += 1
                for d in defs:
                    current.pop(d, None)
                if line.op == "LI" and len(line.args) == 2 and line.args[1] in names:
                    current[reg_of(line.args[0])] = line.args[1]
        # la direccion cargada ya no la usa nadie: fuera. Si algo mas la usa (se tomo la
        # direccion, se sumo...), no se puede reescribir
        function.body = [line for block in blocks for line in block.lines]
        blocks = build_cfg(function)
        live_out = liveness(blocks)
        for block in blocks:
            i = 0
            while i < len(block.lines):
                line = block.lines[i]
                if line.kind == "instr" and line.op == "LI" and len(line.args) == 2 and line.args[1] in names:
                    register = reg_of(line.args[0])
                    if register in live_after(block, live_out[block.index], i):
                        raise OptError(f"{where}: '{line.args[1]}' solo se puede leer"
                                       f"{' o escribir' if line.args[1] in INTRINSIC_STORES else ''} como "
                                       f"variable entera (R{register} sigue vivo tras leer {line.args[1]})")
                    del block.lines[i]
                    continue
                i += 1
        function.body = [line for block in blocks for line in block.lines]
    # las declaraciones `.extern` de los intrinsecos ya no designan nada
    unit.chunks = [c for c in unit.chunks
                   if not (isinstance(c, Line) and c.kind == "directive"
                           and directive_parts(c)[0].lower() == ".extern"
                           and directive_parts(c)[1] in names)]
    # ninguna referencia suelta a un intrinseco
    for function in unit.functions():
        for line in function.body:
            if line.kind == "instr" and any(a in names for a in line.args):
                raise OptError(
                    f"{unit.path}: {function.name}: uso no soportado de un intrinseco: {line.render()}")
