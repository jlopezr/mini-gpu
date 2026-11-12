"""Los contadores de CPU PERFORMANCE: leerlos y repartir los ciclos.

Contrato: `1.isa/mmio.md` §12 y §13.2. El bloque esta en `MMIO_CPU_PERF_BASE`, el
contador `n` en `+4n`, y `PERF_CTRL` y `PERF_OVF0` detras del array.

Sirve a dos sitios que hasta ahora no compartian nada: `monitor.py perf`, que
lee la placa en directo, y `t.tests/run_tests.py --measure`, que lee una vez por
caso y monta una tabla. Los dos necesitan lo mismo --que ranuras existen y como
se reparten los ciclos-- y una copia en cada uno seria la forma de que la tabla
y el comando dijeran cosas distintas del mismo programa.

Solo la 30 tiene las ranuras 2 a 7 (busquedas, transacciones y esperas). Las
demas CPU tienen dos contadores, CYCLES y RETIRED, y leerles el resto da error de
MMIO --no ceros--, asi que `read_counters(stalls=False)` es el valor por
defecto seguro y quien sabe que tiene el bloque completo pide `stalls=True`.
"""
from __future__ import annotations

from tools.mmio_map import (
    MMIO_CPU_PERF_BASE,
    MMIO_PERF_CTRL_ENABLE_BIT,
    MMIO_PERF_CTRL_OFF,
    MMIO_PERF_CYCLES_OFF,
    MMIO_PERF_DMEM_HITS_OFF,
    MMIO_PERF_DMEM_MISSES_OFF,
    MMIO_PERF_MULDIV_RETIRED_OFF,
    MMIO_PERF_STALL_MULDIV_OFF,
    MMIO_PERF_IMEM_HITS_OFF,
    MMIO_PERF_IMEM_MISSES_OFF,
    MMIO_PERF_MEM_TX_OFF,
    MMIO_PERF_OVF0_OFF,
    MMIO_PERF_RETIRED_OFF,
    MMIO_PERF_STALL_FETCH_OFF,
    MMIO_PERF_STALL_MEM_OFF,
    MMIO_PERF_STALL_MMIO_OFF,
    MMIO_PERF_STALL_BRANCH_OFF,
    MMIO_PERF_STALL_EX_MEM_OFF,
    MMIO_PERF_STALL_ID_EMPTY_OFF,
    MMIO_PERF_STALL_RAW_OFF,
)

# Nombre de cada contador de espera -> su offset en el bloque.
STALL_COUNTERS = {
    "imem_hits": MMIO_PERF_IMEM_HITS_OFF,
    "imem_misses": MMIO_PERF_IMEM_MISSES_OFF,
    "mem_tx": MMIO_PERF_MEM_TX_OFF,
    "stall_mem": MMIO_PERF_STALL_MEM_OFF,
    "stall_fetch": MMIO_PERF_STALL_FETCH_OFF,
    "stall_mmio": MMIO_PERF_STALL_MMIO_OFF,
}


# Los de la CPU segmentada (capacidad `perf_pipeline`, ranuras 8 a 11): el
# motivo de cada ciclo en que ninguna instruccion pasa de ID a EX. Van en el
# mismo diccionario que los de espera.
PIPELINE_COUNTERS = {
    "stall_ex_mem": MMIO_PERF_STALL_EX_MEM_OFF,
    "stall_raw": MMIO_PERF_STALL_RAW_OFF,
    "stall_branch": MMIO_PERF_STALL_BRANCH_OFF,
    "stall_id_empty": MMIO_PERF_STALL_ID_EMPTY_OFF,
}


# Los de la cache de datos (capacidad `perf_dcache`, ranuras 12 y 13): cada
# LOAD a memoria acierta o falla. Tambien van con los de espera.
DCACHE_COUNTERS = {
    "dmem_hits": MMIO_PERF_DMEM_HITS_OFF,
    "dmem_misses": MMIO_PERF_DMEM_MISSES_OFF,
}


# Los de MUL/DIV en la CPU segmentada (capacidad `perf_muldiv`, ranuras 14 y
# 15): la espera es un motivo mas del reparto del pipeline.
MULDIV_COUNTERS = {
    "stall_muldiv": MMIO_PERF_STALL_MULDIV_OFF,
    "muldiv_retired": MMIO_PERF_MULDIV_RETIRED_OFF,
}


def read_counters(read_word, write_word=None, stalls: bool = False,
                  base: int = MMIO_CPU_PERF_BASE, pipeline: bool = False,
                  dcache: bool = False, muldiv: bool = False) -> dict:
    """Todos los contadores de un mismo instante.

    `read_word(direccion)` y `write_word(direccion, valor)` son los del cliente
    del monitor. Con `write_word` se congela el bloque mientras se lee
    (`PERF_CTRL.ENABLE = 0`, §12.5): con el programa corriendo, seis lecturas
    son seis instantes distintos y el CPI que sale es de una mezcla. Se restaura
    el valor que tenia, no se fuerza a uno.

    Devuelve `cycles`, `instructions`, `overflow` (PERF_OVF0) y, con
    `stalls=True`, `stalls` con los seis contadores de espera.
    """
    previo = None
    if write_word is not None:
        previo = read_word(base + MMIO_PERF_CTRL_OFF)
        write_word(base + MMIO_PERF_CTRL_OFF, previo & ~(1 << MMIO_PERF_CTRL_ENABLE_BIT))
    try:
        contadores = {
            "cycles": read_word(base + MMIO_PERF_CYCLES_OFF),
            "instructions": read_word(base + MMIO_PERF_RETIRED_OFF),
            "overflow": read_word(base + MMIO_PERF_OVF0_OFF),
            "stalls": None,
        }
        if stalls:
            contadores["stalls"] = {nombre: read_word(base + offset)
                                    for nombre, offset in STALL_COUNTERS.items()}
            if pipeline:
                contadores["stalls"].update({nombre: read_word(base + offset)
                                             for nombre, offset in PIPELINE_COUNTERS.items()})
            if dcache:
                contadores["stalls"].update({nombre: read_word(base + offset)
                                             for nombre, offset in DCACHE_COUNTERS.items()})
            if muldiv:
                contadores["stalls"].update({nombre: read_word(base + offset)
                                             for nombre, offset in MULDIV_COUNTERS.items()})
    finally:
        if write_word is not None:
            write_word(base + MMIO_PERF_CTRL_OFF, previo)
    return contadores


def difference(antes: dict, despues: dict) -> dict:
    """Lo que ha contado el bloque ENTRE dos lecturas de `read_counters`.

    Aritmetica modular de 32 bits (§12.2): sigue valiendo aunque un contador
    haya dado la vuelta en medio, mientras no haya dado dos, y por eso es como se
    mide un programa que lleva minutos corriendo, cuyas lecturas absolutas ya no
    significan nada. `overflow` sale a cero: la diferencia es de fiar.
    """
    mascara = 0xFFFF_FFFF
    resta = {
        "cycles": (despues["cycles"] - antes["cycles"]) & mascara,
        "instructions": (despues["instructions"] - antes["instructions"]) & mascara,
        "overflow": 0,
        "stalls": None,
    }
    if antes.get("stalls") and despues.get("stalls"):
        resta["stalls"] = {nombre: (despues["stalls"][nombre] - antes["stalls"][nombre]) & mascara
                           for nombre in antes["stalls"]}
    return resta


def breakdown(cycles, instructions, stalls) -> dict | None:
    """Reparto de los ciclos, o `None` si no hay con que hacerlo.

    CYCLES = calculo + STALL_MEM + STALL_MMIO; de STALL_MEM, STALL_FETCH es la
    busqueda de instruccion y el resto los datos. Los eventos cruzan un par de
    registros antes de contarse, asi que la suma de esperas puede pasarse de
    CYCLES en un ciclo o dos: el calculo no baja de cero.

    Todo son fracciones de CYCLES salvo `hit_rate` (de las busquedas cacheables)
    y `tx_per_instruction`; los dos son `None` cuando no hay con que dividir.
    """
    if not cycles or not stalls:
        return None
    fetch = stalls["stall_fetch"]
    data = stalls["stall_mem"] - fetch
    mmio = stalls["stall_mmio"]
    lookups = stalls["imem_hits"] + stalls["imem_misses"]
    return {
        "compute": max(0, cycles - stalls["stall_mem"] - mmio) / cycles,
        "fetch": fetch / cycles,
        "data": data / cycles,
        "mmio": mmio / cycles,
        "hit_rate": stalls["imem_hits"] / lookups if lookups else None,
        "tx_per_instruction": (stalls["mem_tx"] / instructions
                               if instructions else None),
    }


def dcache_breakdown(instructions, stalls) -> dict | None:
    """Aciertos de la cache de datos (capacidad `perf_dcache`).

    Devuelve `hits`, `misses`, `hit_rate` (None sin ningun LOAD a memoria) y
    `misses_per_instruction`; None si la medida no trae esos contadores.
    """
    if not stalls or "dmem_hits" not in stalls or "dmem_misses" not in stalls:
        return None
    hits, misses = stalls["dmem_hits"], stalls["dmem_misses"]
    loads = hits + misses
    return {
        "hits": hits,
        "misses": misses,
        "hit_rate": hits / loads if loads else None,
        "misses_per_instruction": misses / instructions if instructions else None,
    }


def muldiv_breakdown(instructions, stalls) -> dict | None:
    """MUL/DIV de la CPU segmentada (capacidad `perf_muldiv`).

    Devuelve `retired` (MUL/DIV retiradas), `stall` (ciclos de espera),
    `fraction` (parte de las instrucciones que son MUL/DIV) y `cycles_per_op`
    (espera media de cada una, None sin ninguna); None si la medida no trae
    esos contadores.
    """
    if not stalls or "stall_muldiv" not in stalls or "muldiv_retired" not in stalls:
        return None
    retired, stall = stalls["muldiv_retired"], stalls["stall_muldiv"]
    return {
        "retired": retired,
        "stall": stall,
        "fraction": retired / instructions if instructions else None,
        "cycles_per_op": stall / retired if retired else None,
    }


def pipeline_breakdown(cycles, instructions, stalls) -> dict | None:
    """Ciclos por instruccion de cada motivo de no emitir, o `None` sin datos.

    CYCLES = RETIRED + STALL_EX_MEM + STALL_RAW + STALL_BRANCH + STALL_ID_EMPTY
    (+ STALL_MULDIV) + otros, asi que CPI = 1 + la suma de lo que devuelve.
    `muldiv` solo esta si la medida trae STALL_MULDIV. `other` son los ciclos
    de arranque, STEP, HALT y error; no baja de cero, porque los eventos llegan
    un ciclo tarde.
    """
    if not cycles or not instructions or not stalls or "stall_raw" not in stalls:
        return None
    motivos = list(PIPELINE_COUNTERS)
    if "stall_muldiv" in stalls:
        motivos.append("stall_muldiv")
    parts = {nombre.removeprefix("stall_"): stalls[nombre] / instructions
             for nombre in motivos}
    counted = instructions + sum(stalls[nombre] for nombre in motivos)
    parts["other"] = max(0, cycles - counted) / instructions
    return parts


def _pct(fraction) -> str:
    return "n/d" if fraction is None else f"{100.0 * fraction:.1f} %"


def format_report(contadores: dict) -> list[str]:
    """Las lineas que imprime `monitor.py perf`."""
    cycles, instructions = contadores["cycles"], contadores["instructions"]
    # Con un contador dado la vuelta, el CPI de valores absolutos es de otra
    # cosa: se enseña, pero marcado, y el aviso de abajo dice como medir bien.
    dudoso = "  [no fiable: un contador dio la vuelta]" if contadores.get("overflow") else ""
    if instructions == 0:
        lineas = [f"cycles={cycles} instructions=0 (CPI: sin datos){dudoso}"]
    else:
        cpi = cycles / instructions
        lineas = [f"cycles={cycles} instructions={instructions} "
                  f"CPI={cpi:.2f} IPC={1 / cpi:.3f}{dudoso}"]
    r = breakdown(cycles, instructions, contadores.get("stalls"))
    if r is not None:
        stalls = contadores["stalls"]
        lineas.append(
            f"  reparto de los ciclos: calculo {_pct(r['compute'])}, "
            f"busqueda {_pct(r['fetch'])}, datos {_pct(r['data'])}, "
            f"MMIO {_pct(r['mmio'])}")
        lineas.append(
            f"  buffer de instrucciones: {stalls['imem_hits']} aciertos, "
            f"{stalls['imem_misses']} fallos ({_pct(r['hit_rate'])} de acierto); "
            f"{stalls['mem_tx']} peticiones a memoria")
    p = pipeline_breakdown(cycles, instructions, contadores.get("stalls"))
    if p is not None:
        muldiv = f"MUL/DIV {p['muldiv']:.2f}, " if "muldiv" in p else ""
        lineas.append(
            f"  ciclos por instruccion, ademas del 1: EX con memoria {p['ex_mem']:.2f}, "
            f"{muldiv}dependencia {p['raw']:.2f}, salto {p['branch']:.2f}, "
            f"ID vacio {p['id_empty']:.2f}, otros {p['other']:.2f}")
    m = muldiv_breakdown(instructions, contadores.get("stalls"))
    if m is not None and m["retired"]:
        lineas.append(
            f"  MUL/DIV: {m['retired']} retiradas ({_pct(m['fraction'])} de las "
            f"instrucciones), {m['cycles_per_op']:.1f} ciclos de espera de media")
    if contadores.get("overflow"):
        lineas.append(
            f"  AVISO: PERF_OVF0={contadores['overflow']:#x}, algun contador ha dado la "
            f"vuelta (a 80 MHz, 53 s): los valores absolutos no son de fiar, solo las "
            f"diferencias entre dos lecturas. Mide una ventana con `perf <segundos>`, "
            f"o ponlos a cero con PERF_CTRL.RESET o reinicia con `run`.")
    return lineas
