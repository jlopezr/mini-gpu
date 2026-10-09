"""Propagacion y plegado de constantes

Donde un registro vale una constante por todos los caminos (`MOVI R7, 256`), la instruccion que
lo lee pasa a su forma con inmediato: `SUB d, a, R7` -> `ADDI d, a, -256`; `ADD`, `AND`, `OR` y
`XOR` igual (la suma con signo de 16 bits, la logica sin signo). Un desplazamiento de 1 bit es
una suma: `SHL d, a, R9` con R9 = 1 -> `ADD d, a, a`. La constante deja de ocupar un registro
(la GPU no tiene saltos ni desplazamientos con inmediato, asi que no todas se van).

Ademas, con la misma informacion:

- **copias**: una copia de una constante (`ADD d, s, R0`) tambien deja a `d` con ese valor; la copia no
  se toca (es lo que sigue `copyprop`), pero los usos de `d` se pliegan como si fuera la constante.
- **redundantes**: un `MOVI`/`LI` de un registro que ya vale eso por todos los caminos se borra
  (lcc recarga el `3` del desplazamiento en cada `SHL` aunque no lo haya tocado).
- **evaluar**: si los dos operandos son constantes, la operacion se hace aqui y queda un `MOVI`/`LI`
  (`ADD`, `SUB`, `MUL`, `AND`, `OR`, `XOR`, `SHL`, `SHR`, `SAR`, `SLT`, `SLTU` y sus formas con
  inmediato, con la aritmetica de 32 bits de la maquina). Una copia (`ADD d, x, R0`) no se evalua:
  es lo que `copyprop` sabe seguir, y con un cero (`ADD d, R0, R0`) deja que los usos lean `R0`.
- **identidades**: `x + 0`, `x - 0`, `x | 0`, `x ^ 0`, `x << 0`, `x * 1` y `x & -1` son una copia
  (`ADD d, x, R0`, que `copyprop` sabe seguir; si `d` es `x` se borra); `x * 0`, `x & 0`, `x - x` y
  `x ^ x` son un cero.
- **`MUL` seguido de `SHL`**: `MUL d, a, K ; SHL d, d, S` es `MUL d, a, K << S`. La GPU no tiene `MULI`
  ni `SHLI`, asi que la constante esta en un registro: se recarga con el valor ya desplazado justo
  antes del `MUL` (si ese registro no se lee despues) y el `SHL` desaparece."""
from __future__ import annotations

from ..flow import Block, build_cfg, forward_must, liveness, live_after
from ..isa import IMM2, R3, defs_uses, instr, number, reg_of
from ..model import Line, Unit
from ..registry import register_pass

FOLD_LOGIC = {"AND": "ANDI", "OR": "ORI", "XOR": "XORI"}
SIGNED_16 = range(-32768, 32768)
UNSIGNED_16 = range(0, 0x10000)
MASK = 0xFFFFFFFF
SHIFTS = ("SHL", "SHR", "SAR")
IMM_LOGIC = ("ANDI", "ORI", "XORI")
IMM_SHIFTS = ("SHLI", "SHRI", "SARI")


def s32(value: int) -> int:
    value &= MASK
    return value - (1 << 32) if value & 0x80000000 else value


def constant_of(line: Line) -> int | None:
    """Valor que deja en su destino una instruccion que carga una constante numerica."""
    if line.kind != "instr" or len(line.args) < 2:
        return None
    if line.op in ("MOVI", "LI"):
        return number(line.args[1])
    if line.op == "ADDI" and reg_of(line.args[1]) == 0:
        return number(line.args[2])
    return None


def copy_source(line: Line) -> int | None:
    """El registro del que copia `ADD d, s, R0`; None si no es una copia."""
    if line.kind == "instr" and line.op == "ADD" and len(line.args) == 3 and reg_of(line.args[2]) == 0:
        return reg_of(line.args[1])
    return None


def track_constants(state: dict[int, int], line: Line) -> None:
    """Actualiza las constantes vigentes `{registro: valor}` tras ejecutar `line`. Una copia de una
    constante (`ADD d, s, R0`, y R0 es el cero) tambien lo es: la copia se queda, pero sus usos se pliegan."""
    source = copy_source(line)
    copied = known(state, source)
    for written in defs_uses(line)[0]:
        state.pop(written, None)
    value = constant_of(line)
    if value is None:
        value = copied
    dest = reg_of(line.args[0]) if value is not None else None
    if value is not None and dest:                  # None y R0 no cuentan
        state[dest] = value


def fold_constant(line: Line, state: dict[int, int]) -> bool:
    """Reescribe `line` con inmediato si un operando es una constante conocida."""
    if line.op not in R3 or len(line.args) != 3:
        return False
    d, a, b = line.args
    ra, rb = reg_of(a), reg_of(b)
    ca = state.get(ra) if ra else None
    cb = state.get(rb) if rb else None
    if line.op == "ADD":
        if cb is not None and cb in SIGNED_16:
            line.op, line.args = "ADDI", [d, a, str(cb)]
        elif ca is not None and ca in SIGNED_16:
            line.op, line.args = "ADDI", [d, b, str(ca)]
        else:
            return False
    elif line.op == "SUB" and cb is not None and -cb in SIGNED_16:
        line.op, line.args = "ADDI", [d, a, str(-cb)]
    elif line.op in FOLD_LOGIC:
        if cb is not None and cb in UNSIGNED_16:
            line.op, line.args = FOLD_LOGIC[line.op], [d, a, str(cb)]
        elif ca is not None and ca in UNSIGNED_16:
            line.op, line.args = FOLD_LOGIC[line.op], [d, b, str(ca)]
        else:
            return False
    elif line.op == "SHL" and cb == 1:
        line.op, line.args = "ADD", [d, a, a]
    else:
        return False
    return True


# ---------------------------------------------------------------------------
# Evaluar con la aritmetica de la maquina
# ---------------------------------------------------------------------------

def evaluate(op: str, x: int, y: int) -> int | None:
    """Resultado de `op x, y` en 32 bits (los desplazamientos usan los 5 bits bajos); None si no se evalua."""
    x, y = x & MASK, y & MASK
    if op == "ADD":
        return (x + y) & MASK
    if op == "SUB":
        return (x - y) & MASK
    if op == "MUL":
        return (x * y) & MASK
    if op == "AND":
        return x & y
    if op == "OR":
        return x | y
    if op == "XOR":
        return x ^ y
    if op == "SHL":
        return (x << (y & 31)) & MASK
    if op == "SHR":
        return x >> (y & 31)
    if op == "SAR":
        return (s32(x) >> (y & 31)) & MASK
    if op == "SLT":
        return int(s32(x) < s32(y))
    if op == "SLTU":
        return int(x < y)
    return None


IMM_AS_R3 = {"ADDI": "ADD", "ANDI": "AND", "ORI": "OR", "XORI": "XOR",
             "SHLI": "SHL", "SHRI": "SHR", "SARI": "SAR"}


def immediate_value(op: str, imm: int) -> int:
    """El valor que usa la maquina: con signo en la suma, 16 bits sin signo en la logica, 5 bits en los desplazamientos."""
    if op in IMM_LOGIC:
        return imm & 0xFFFF
    if op in IMM_SHIFTS:
        return imm & 31
    return s32(imm)


def load_of(dest: str, value: int) -> Line:
    """`MOVI` si cabe en 16 bits con signo, y `LI` si no."""
    value = s32(value)
    return instr("MOVI" if value in SIGNED_16 else "LI", dest, str(value))


def copy_of(dest: str, source: str) -> Line:
    return instr("ADD", dest, source, "R0")


def known(state: dict[int, int], register: int | None) -> int | None:
    """Valor constante de un registro; R0 es el cero."""
    if register is None:
        return None
    return 0 if register == 0 else state.get(register)


def identity_of(op: str, ra: int, rb: int, ka: int | None, kb: int | None) -> tuple | None:
    """('copy', 1|2) = el resultado es el operando 1 o 2; ('zero',); None = ninguna identidad."""
    if ra == rb and ra and op in ("SUB", "XOR"):
        return ("zero",)
    if op in ("ADD", "OR", "XOR"):
        if kb == 0:
            return ("copy", 1)
        if ka == 0:
            return ("copy", 2)
    elif op == "SUB":
        if kb == 0:
            return ("copy", 1)
    elif op in SHIFTS:
        if kb is not None and kb & 31 == 0:
            return ("copy", 1)
    elif op == "MUL":
        if kb == 0 or ka == 0:
            return ("zero",)
        if kb == 1:
            return ("copy", 1)
        if ka == 1:
            return ("copy", 2)
    elif op == "AND":
        if kb == 0 or ka == 0:
            return ("zero",)
        if kb is not None and kb & MASK == MASK:
            return ("copy", 1)
        if ka is not None and ka & MASK == MASK:
            return ("copy", 2)
    return None


def apply_identity(line: Line, identity: tuple, rd: int, stats: dict) -> Line | None:
    """La instruccion que sustituye a `line`; None si se borra (copiar un registro a si mismo)."""
    d = line.args[0]
    if identity[0] == "zero":
        stats["constprop.identities"] = stats.get("constprop.identities", 0) + 1
        return load_of(d, 0)
    source = line.args[identity[1]]
    if reg_of(source) == rd:
        stats["constprop.identities"] = stats.get("constprop.identities", 0) + 1
        return None
    if line.op == "ADD" and reg_of(line.args[2]) == 0:         # ya es una copia
        return line
    stats["constprop.identities"] = stats.get("constprop.identities", 0) + 1
    return copy_of(d, source)


def rewrite_r3(line: Line, state: dict[int, int], stats: dict) -> Line | None:
    d, a, b = line.args
    rd, ra, rb = reg_of(d), reg_of(a), reg_of(b)
    if not rd or ra is None or rb is None:
        return line
    ka, kb = known(state, ra), known(state, rb)
    is_copy = line.op == "ADD" and rb == 0                     # la forma que `copyprop` sabe seguir: no se evalua
    if ka is not None and kb is not None and not is_copy:
        value = evaluate(line.op, ka, kb)
        if value is not None:
            stats["constprop.evaluated"] = stats.get("constprop.evaluated", 0) + 1
            return load_of(d, value)
    identity = identity_of(line.op, ra, rb, ka, kb)
    if identity:
        return apply_identity(line, identity, rd, stats)
    if fold_constant(line, state):
        stats["constprop.folded"] = stats.get("constprop.folded", 0) + 1
    return line


def rewrite_imm(line: Line, state: dict[int, int], stats: dict) -> Line | None:
    d, a, text = line.args
    rd, ra, imm = reg_of(d), reg_of(a), number(text)
    if not rd or not ra or imm is None:             # `op d, R0, k` ya es una carga de constante
        return line
    value = immediate_value(line.op, imm)
    ka = state.get(ra)
    if ka is not None:
        stats["constprop.evaluated"] = stats.get("constprop.evaluated", 0) + 1
        return load_of(d, evaluate(IMM_AS_R3[line.op], ka, value))
    if line.op == "ANDI" and value == 0:
        return apply_identity(line, ("zero",), rd, stats)
    if (line.op in ("ADDI", "ORI", "XORI") and value == 0) or (line.op in IMM_SHIFTS and value == 0):
        return apply_identity(line, ("copy", 1), rd, stats)
    return line


def rewrite(line: Line, state: dict[int, int], stats: dict) -> Line | None:
    """La instruccion que sustituye a `line` (la misma, tocada o no) o None si sobra."""
    value = constant_of(line)
    dest = reg_of(line.args[0]) if value is not None else None
    if dest and state.get(dest) is not None and state[dest] & MASK == value & MASK:
        stats["constprop.redundant"] = stats.get("constprop.redundant", 0) + 1
        return None
    if line.op in R3 and len(line.args) == 3:
        return rewrite_r3(line, state, stats)
    if line.op in IMM2 and len(line.args) == 3:
        return rewrite_imm(line, state, stats)
    return line


# ---------------------------------------------------------------------------
# MUL por una constante seguido de SHL por otra
# ---------------------------------------------------------------------------

def multiplier_of(line: Line, state: dict[int, int], live: set[int]) -> tuple[int, int] | None:
    """(registro de la constante, valor) si `line` es `MUL d, x, k` con k constante y ese registro no se
    lee despues (se va a sobrescribir con la constante desplazada), y no es ni el destino ni el otro operando."""
    if line.op != "MUL" or len(line.args) != 3:
        return None
    rd, ra, rb = (reg_of(arg) for arg in line.args)
    if not rd or not ra or not rb or ra == rb:
        return None
    for const, other in ((rb, ra), (ra, rb)):
        if const in state and const != rd and const not in live:
            return const, state[const]
    return None


def fuse_shift(line: Line, state: dict[int, int], pending: dict, keep: list[Line], stats: dict) -> bool:
    """`SHL d, d, S` justo despues del `MUL` que escribio `d`: el `MUL` pasa a multiplicar por `K << S`."""
    if line.op != "SHL" or len(line.args) != 3:
        return False
    rd, ra, rs = (reg_of(arg) for arg in line.args)
    if not rd or rd != ra or rd not in pending or state.get(rs) is None:
        return False
    index, constant, value = pending[rd]
    keep.insert(index, load_of(f"R{constant}", (value & MASK) << (state[rs] & 31)))
    pending.clear()                                 # los indices de `keep` ya no valen
    state.pop(constant, None)
    stats["constprop.fused"] = stats.get("constprop.fused", 0) + 1
    return True


def simplify_block(block: Block, state: dict[int, int], live_out: set[int], stats: dict) -> list[Line]:
    keep: list[Line] = []
    pending: dict[int, tuple[int, int, int]] = {}   # d -> (posicion del MUL en keep, registro y valor de su constante)
    for position, line in enumerate(block.lines):
        if line.kind != "instr":
            keep.append(line)
            continue
        if fuse_shift(line, state, pending, keep, stats):
            track_constants(state, line)
            continue
        new = rewrite(line, state, stats)
        defs, uses = defs_uses(line)
        for register in defs | uses:
            pending.pop(register, None)
        if new is not None:
            if new.op == "MUL":
                found = multiplier_of(new, state, live_after(block, live_out, position))
                if found and reg_of(new.args[0]):
                    pending[reg_of(new.args[0])] = (len(keep), *found)
            keep.append(new)
            track_constants(state, new)
    return keep


@register_pass("constprop", "constantes conocidas: a inmediato, redundantes, evaluar, identidades, MUL+SHL")
def pass_constprop(unit: Unit, stats: dict) -> None:
    for function in unit.functions():
        if function.opaque:
            continue
        blocks = build_cfg(function)
        if not blocks:
            continue
        live_out = liveness(blocks)
        for block, entering in zip(blocks, forward_must(blocks, track_constants)):
            block.lines = simplify_block(block, dict(entering), live_out[block.index], stats)
        function.body = [line for block in blocks for line in block.lines]
