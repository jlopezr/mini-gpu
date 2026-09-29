"""Los contadores de CPU PERFORMANCE: leerlos y repartir los ciclos.

Contrato: `1.isa/mmio.md` §12 y §13.2. El bloque esta en `MMIO_CPU_PERF_BASE`, el
contador `n` en `+4n`, y `PERF_CTRL` y `PERF_OVF0` detras del array.

Sirve a dos sitios que hasta ahora no compartian nada: `monitor.py perf`, que
lee la placa en directo, y `x.tests/run_tests.py --measure`, que lee una vez por
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
    MMIO_PERF_IMEM_HITS_OFF,
    MMIO_PERF_IMEM_MISSES_OFF,
    MMIO_PERF_MEM_TX_OFF,
    MMIO_PERF_OVF0_OFF,
    MMIO_PERF_RETIRED_OFF,
    MMIO_PERF_STALL_FETCH_OFF,
    MMIO_PERF_STALL_MEM_OFF,
    MMIO_PERF_STALL_MMIO_OFF,
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


def read_counters(read_word, write_word=None, stalls: bool = False,
                  base: int = MMIO_CPU_PERF_BASE) -> dict:
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
    if contadores.get("overflow"):
        lineas.append(
            f"  AVISO: PERF_OVF0={contadores['overflow']:#x}, algun contador ha dado la "
            f"vuelta (a 80 MHz, 53 s): los valores absolutos no son de fiar, solo las "
            f"diferencias entre dos lecturas. Mide una ventana con `perf <segundos>`, "
            f"o ponlos a cero con PERF_CTRL.RESET o reinicia con `run`.")
    return lineas
