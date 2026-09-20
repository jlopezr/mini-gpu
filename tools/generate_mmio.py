"""Genera las constantes de MMIO v2 desde la fuente unica `1.isa/mmio_map.vh`.

Salidas:

    x.tests/inc/mmio.inc    para el ensamblador (`.equ`)
    tools/mmio_map.py       para monitor.py, sim_devices.py y los simuladores

POR QUE ESTO Y NO TRES LISTAS A MANO. `1.isa/mmio.md` §20 lo pide, y la razon
esta contada en el propio contrato: hoy la misma direccion vive en el
decodificador Verilog, en la lista blanca del cliente Python y en cada `.asm`
que la lleva cableada. Mover un dispositivo son tres ediciones que nada obliga
a hacer juntas, y el sintoma de olvidar una es un NACK que parece un bitstream
viejo.

POR QUE LOS FICHEROS GENERADOS SE VERSIONAN. No hay paso de build entre
escribir un `.asm` y ensamblarlo: `run_tests.py` y `tools/run_board.py` llaman
al ensamblador directamente. Generar al vuelo obligaria a que TODO camino que
ensambla ejecutara antes el generador --y el que se olvide falla de una forma
oscura, en el sitio equivocado--. Versionarlos y comprobarlos con `--check`
mueve el fallo a un test que dice exactamente que pasa.

El parser es a proposito de tres lineas. Si algun dia no basta, el problema es
que `mmio_map.vh` ha dejado de ser tonto, no que el parser se haya quedado
corto: lo que hay que arreglar es el .vh.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "1.isa" / "mmio_map.vh"
INC_OUTPUT = ROOT / "x.tests" / "inc" / "mmio.inc"
PY_OUTPUT = ROOT / "tools" / "mmio_map.py"

SOURCE_V1 = ROOT / "1.isa" / "mmio_map_v1.vh"
INC_OUTPUT_V1 = ROOT / "x.tests" / "inc" / "mmio_v1.inc"
PY_OUTPUT_V1 = ROOT / "tools" / "mmio_map_v1.py"

#: (fuente, .inc, modulo .py). El segundo mapa es el de v1, con las mismas
#: constantes y los valores de HOY, para que los programas de una carpeta
#: puedan pasar a simbolos antes de que las direcciones se muevan.
#:
#: Se borro al cerrar la migracion de la 21 --"si un mapa de transicion sigue
#: aqui y ningun `.asm` lo incluye, sobra"-- y hubo que rehacerlo entero para
#: la 19. El criterio estaba mal: el andamio no sobra cuando lo suelta la
#: primera carpeta, sobra cuando lo suelta la ULTIMA. Ocho carpetas seguian en
#: v1 cuando se borro.
MAPAS = (
    (SOURCE, INC_OUTPUT, PY_OUTPUT),
    (SOURCE_V1, INC_OUTPUT_V1, PY_OUTPUT_V1),
)

# `define NOMBRE 32'hXXXX_XXXX`, y nada mas. Cualquier otra forma se rechaza
# en vez de ignorarse: una linea que el parser no entiende y se salta es una
# constante que desaparece del fichero generado sin que nadie se entere.
DEFINE_RE = re.compile(
    r"^\s*`define\s+([A-Z][A-Z0-9_]*)\s+32'h([0-9A-Fa-f_]+)\s*$")

AVISO = "GENERADO por tools/generate-mmio desde 1.isa/mmio_map.vh. No editar."


class MmioMapError(ValueError):
    """Algo en `mmio_map.vh` no cumple las reglas del propio fichero."""


def parse_map(text: str, nombre_fuente: str = "mmio_map.vh") -> dict[str, int]:
    """Lee el .vh. Estricto a proposito: lo que no encaja, se denuncia."""
    valores: dict[str, int] = {}
    for numero, linea in enumerate(text.splitlines(), 1):
        limpia = linea.split("//", 1)[0].strip()
        if not limpia:
            continue
        if not limpia.startswith("`define"):
            raise MmioMapError(
                f"{nombre_fuente}:{numero}: solo se admiten lineas `define "
                f"y comentarios: {linea.strip()}")
        match = DEFINE_RE.match(limpia)
        if not match:
            raise MmioMapError(
                f"{nombre_fuente}:{numero}: un `define` tiene que ser nombre y "
                f"una constante 32'hXXXX_XXXX, sin expresiones: {limpia}")
        nombre, digitos = match.group(1), match.group(2).replace("_", "")
        if nombre in valores:
            raise MmioMapError(
                f"{nombre_fuente}:{numero}: constante duplicada: {nombre}")
        valores[nombre] = int(digitos, 16)
    if not valores:
        raise MmioMapError(f"{nombre_fuente}: no define ninguna constante")
    return valores


def render_inc(valores: dict[str, int],
               nombre_fuente: str = "mmio_map.vh") -> str:
    """El include del ensamblador.

    Las bases salen tal cual; los `_OFF` se emiten TAMBIEN como direccion
    absoluta de su bloque, que es lo que un programa quiere escribir. La suma
    la hace `.equ`, que admite `BASE+0x...`, asi que el .inc sigue sin tener
    logica: solo nombres y sumas de dos terminos.
    """
    lineas = [
        f"; GENERADO por tools/generate-mmio desde 1.isa/{nombre_fuente}. No editar.",
        ";",
        "; La carpeta x.tests/inc ya va en el -I de run_tests.py y run_board.py,",
        "; asi que basta con `.include` y el nombre.",
        ".once",
        "",
    ]

    for nombre, valor in valores.items():
        lineas.append(f".equ {nombre}, 0x{valor:08X}")

    # Direcciones absolutas: <BLOQUE>_<REG> = <BLOQUE>_BASE + offset.
    absolutas = []
    for nombre, valor in valores.items():
        if not nombre.endswith("_OFF"):
            continue
        base = base_de(nombre, valores)
        if base is None:
            continue
        absolutas.append((nombre[:-len("_OFF")], base, valor))

    comprobar_colisiones(absolutas, valores)

    if absolutas:
        lineas += ["", "; Direcciones absolutas, por comodidad: base + offset.", ""]
        for nombre, base, offset in absolutas:
            lineas.append(f".equ {nombre}_ADDR, {base}+0x{offset:08X}")

    return "\n".join(lineas) + "\n"


def comprobar_colisiones(absolutas: list[tuple[str, str, int]],
                         valores: dict[str, int]) -> None:
    """Dos registros distintos no pueden caer en la misma direccion.

    Es la red de seguridad de `base_de`, que adivina el bloque por el prefijo
    del nombre. La primera version de este generador colgo los descriptores de
    warp y todo SIMT DEBUG de `MMIO_GPU_BASE` --porque se llamaban
    `MMIO_GPU_WARP_*` y la base es `MMIO_GPU_WARPS_BASE`, con S-- y saco
    `GPU_WARP_PC` en la misma direccion que `GPU_ID`.

    Nada fallaba: el .inc se generaba, el ensamblador lo tragaba y el programa
    escribia en el registro equivocado. Exactamente el modo de fallo silencioso
    por el que existe todo este generador, cometido por el generador. De ahi
    que la comprobacion sea un error duro y no un aviso.
    """
    por_direccion: dict[int, str] = {}
    for nombre, base, offset in absolutas:
        direccion = valores[base] + offset
        if direccion in por_direccion:
            raise MmioMapError(
                f"dos registros en 0x{direccion:08X}: {por_direccion[direccion]} "
                f"y {nombre}. Casi seguro que un `_OFF` no encaja con el "
                f"`_BASE` de su bloque; comprueba el nombre en mmio_map.vh")
        por_direccion[direccion] = nombre


def base_de(nombre_off: str, valores: dict[str, int]) -> str | None:
    """A que `_BASE` pertenece un `_OFF`, por prefijo mas largo que encaje.

    Devuelve None cuando no hay ninguna --los `_OFF` de PERF y de WARP son
    plantillas que valen para dos bloques distintos, asi que no tienen una
    direccion absoluta unica y no se les inventa una.
    """
    tronco = nombre_off[:-len("_OFF")]
    partes = tronco.split("_")
    for corte in range(len(partes), 0, -1):
        candidata = "_".join(partes[:corte]) + "_BASE"
        if candidata in valores:
            return candidata
    return None


def render_py(valores: dict[str, int],
              nombre_fuente: str = "mmio_map.vh") -> str:
    """El modulo Python, para el monitor y los simuladores."""
    lineas = [
        '"""GENERADO por tools/generate-mmio desde 1.isa/' + nombre_fuente
        + ". No editar.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
    ]
    for nombre, valor in valores.items():
        lineas.append(f"{nombre} = 0x{valor:08X}")
    lineas += [
        "",
        "",
        "#: Todas las constantes por nombre, para quien recorra el mapa entero",
        "#: en vez de citar una. Lo usa el test de sincronia.",
        "ALL = {",
    ]
    for nombre in valores:
        lineas.append(f'    "{nombre}": {nombre},')
    lineas.append("}")
    return "\n".join(lineas) + "\n"


def generar() -> dict[Path, str]:
    """Lo que DEBERIA haber en disco, para los dos mapas. No escribe."""
    salidas: dict[Path, str] = {}
    for fuente, destino_inc, destino_py in MAPAS:
        valores = parse_map(fuente.read_text(encoding="utf-8"), fuente.name)
        salidas[destino_inc] = render_inc(valores, fuente.name)
        salidas[destino_py] = render_py(valores, fuente.name)
    return salidas


def desincronizados() -> list[Path]:
    """Que ficheros generados no estan al dia. Vacio = todo en orden."""
    fuera = []
    for destino, contenido in generar().items():
        actual = (destino.read_text(encoding="utf-8")
                  if destino.exists() else None)
        if actual != contenido:
            fuera.append(destino)
    return fuera


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Genera las constantes MMIO desde 1.isa/mmio_map.vh")
    parser.add_argument("--check", action="store_true",
                        help="no escribe; sale con 1 si algo cambiaria")
    args = parser.parse_args()

    try:
        salidas = generar()
    except MmioMapError as error:
        print(f"error: {error}")
        return 2

    cambiados = []
    for destino, contenido in salidas.items():
        actual = (destino.read_text(encoding="utf-8")
                  if destino.exists() else None)
        if actual == contenido:
            continue
        cambiados.append(destino)
        if not args.check:
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(contenido, encoding="utf-8")

    relativo = [str(p.relative_to(ROOT)).replace("\\", "/") for p in cambiados]

    if args.check:
        if cambiados:
            print("desincronizado respecto a 1.isa/mmio_map.vh:")
            for nombre in relativo:
                print(f"  {nombre}")
            print("ejecuta: ./tools/generate-mmio")
            return 1
        todos = ", ".join(
            sorted(str(p.relative_to(ROOT)).replace("\\", "/")
                   for p in salidas))
        print(f"al dia: {todos}")
        return 0

    for nombre in relativo:
        print(f"escrito: {nombre}")
    if not cambiados:
        print("sin cambios")
    return 0
