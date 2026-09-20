"""Genera la identidad de cada prototipo desde su RTL: `<carpeta>/sysid_params.vh`.

POR QUE ESTO Y NO UN LITERAL EN CADA `top.v`. Lo pide `1.isa/mmio.md` §5.4 con
todas las letras:

    `DEVICES` no se escribe a mano en cada `top.v`. Se deriva de lo que hay en
    el RTL [...]. Un bitmap escrito a mano seria una tercera gemela junto a las
    ventanas del decodificador y la lista del cliente Python.

Y la razon no es teorica. Cuando se escribio este generador, el bitmap estaba a
mano en once sitios de diez carpetas y tenia **seis errores**:

  - la 6 y la 10 no declaraban su propio bit de CPU, mientras las otras ocho si
    declaraban el suyo;
  - la 18, la 19, la 21 y la 22 instancian `memory_fabric_4` y ninguna
    declaraba el bit FABRIC.

Ninguno rompia nada: un bit de mas o de menos en un bitmap descriptivo no da
error, solo miente. Es exactamente el modo de fallo silencioso contra el que
existe este fichero.

QUE NO ESTA AQUI, Y POR QUE. `sysid.v` no es este fichero y no puede serlo: es
byte a byte identico en las diez carpetas y hay un test que lo exige
(`test_sysid_es_copia_identica`). Ahi vive la LOGICA --que palabra contesta
cada offset-- y aqui los VALORES de cada prototipo. Separarlos es lo que
permite que la logica siga siendo una sola copia.

COMO SE USA. Quien instancia `sysid` hace `` `include "sysid_params.vh" `` y
pasa los `define`. Como el include se resuelve dentro de la carpeta, el fichero
que lo incluye puede ser identico entre prototipos: es lo que deja el
`gpu_system.v` de la 14 y el de la 17 byte a byte iguales.

POR QUE SE VERSIONA LO GENERADO. La misma razon que `mmio_map.vh`: no hay paso
de build entre editar RTL y sintetizar, asi que generar al vuelo obligaria a
que todo camino que sintetiza ejecutara antes el generador. Versionarlo y
comprobarlo con `--check` mueve el fallo a un test que dice que pasa.
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import sys  # noqa: E402

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.rtl_facts import (  # noqa: E402
    backend_from_rtl,
    capabilities_from_rtl,
    load_capability_signals,
    monitor_version_from_rtl,
)

#: Los bits de `DEVICES`, de mmio.md §5.4. Una asignacion, una vez hecha, nunca
#: cambia de significado: por eso estan escritos aqui y no derivados de nada.
BIT_SYSTEM = 0
BIT_FABRIC = 1
BIT_SDRAM = 2
BIT_EBR = 3
BIT_SERIAL = 4
BIT_VIDEO = 5
BIT_CPU = 9
BIT_GPU = 10

AVISO = ("GENERADO por tools/generate-sysid desde el RTL de esta carpeta. "
         "No editar.")


class SysidError(ValueError):
    """El RTL de un prototipo no deja deducir su identidad."""


def prototipos() -> list[Path]:
    """Las carpetas con `sysid.v`, que son las que tienen identidad."""
    return sorted((p.parent for p in ROOT.glob("*/sysid.v")),
                  key=lambda d: int(d.name.split(".", 1)[0]))


def _ficheros_rtl(directorio: Path) -> set[str]:
    """Los `.v`/`.sv` de la carpeta, SIN los bancos.

    Sin excluir los `*_tb.v` la 6 declararia FABRIC: no instancia ninguno, pero
    sus bancos si mencionan el modulo. Un banco no se sintetiza y por tanto no
    es un dispositivo presente.
    """
    return {p.name for p in list(directorio.glob("*.v")) + list(directorio.glob("*.sv"))
            if not p.name.endswith("_tb.v")}


def _instancia(directorio: Path, modulo: str) -> bool:
    """Si algun RTL no-banco instancia ese modulo.

    Se mira la INSTANCIACION y no solo que el fichero exista, porque la 22
    tiene dos sistemas y uno puede llevar algo que el otro no.
    """
    import re
    # El `#(...)` opcional no es un detalle: `sdram_controller` se instancia
    # como `sdram_controller #(.CLK_FREQ_HZ(25_000_000)) controller (`, y sin
    # contemplarlo la 14, la 17 y la 22 salian declarando EBR en vez de SDRAM.
    patron = re.compile(
        rf"^[ \t]*{modulo}\w*[ \t\r\n]*(?:#\s*\([^;]*?\)[ \t\r\n]*)?\w+[ \t\r\n]*\(",
        re.MULTILINE)
    for nombre in _ficheros_rtl(directorio):
        if patron.search((directorio / nombre).read_text(encoding="utf-8",
                                                         errors="replace")):
            return True
    return False


def devices_de(directorio: Path, capacidades: set[str]) -> int:
    """El bitmap de §5.4 de este prototipo.

    Los bits de nucleo (9 y 10) significan **que el prototipo tiene ese
    nucleo**, no que el bloque CORE de §13.1/§14.1 conteste: §5.4 dice
    «dispositivos presentes» y lista EBR, que no es un bloque MMIO. Con la otra
    lectura el bit seria cero en las diez, porque ni CPU CORE ni GPU CORE estan
    implementados, y el bitmap no distinguiria una CPU de una GPU.
    """
    bits = 1 << BIT_SYSTEM

    if _instancia(directorio, "sdram_controller"):
        bits |= 1 << BIT_SDRAM
    else:
        bits |= 1 << BIT_EBR

    if _instancia(directorio, "memory_fabric"):
        bits |= 1 << BIT_FABRIC

    # SERIAL y VIDEO salen de `capabilities.json`, que es donde el repo ya
    # declara que buscar en el RTL para saber si un prototipo tiene cada cosa.
    # La memoria y el fabric no estan alli y se miran aqui: meterlos en
    # `capabilities.json` cambiaria que casos se saltan en los tests, que es
    # otro asunto y no debe moverse de rebote.
    if "serial" in capacidades:
        bits |= 1 << BIT_SERIAL
    if "video" in capacidades:
        bits |= 1 << BIT_VIDEO

    arquitectura = backend_from_rtl(directorio)
    if arquitectura == "cpu":
        bits |= 1 << BIT_CPU
    elif arquitectura == "gpu":
        bits |= 1 << BIT_GPU
    else:
        raise SysidError(
            f"{directorio.name}: no se pudo deducir si es CPU o GPU; "
            f"`backend_from_rtl` devolvio {arquitectura!r}")
    return bits


def isa_profile_de(capacidades: set[str]) -> int:
    """Que sabe ejecutar el nucleo. Los bits los documenta `sysid.v`:

        bit 0  MUL, MULHI          bit 2  cargas y almacenes de 8 y 16 bits
        bit 1  DIV, DIVU, REM...   bit 3  SIMT: SSY, BAR, EXIT, GETTID

    Todo sale de `capabilities.json`, sin mirar la arquitectura. Al escribir
    esto `mul_div` estaba declarada `"architecture": "cpu"` y por tanto
    **ninguna GPU la reportaba**, aunque las cuatro tienen `OPCODE_MUL:` y
    `OPCODE_DIV:` en `gpu_lane.v`; el perfil derivado salia 0x8 donde el RTL
    dice 0x0b, o sea «esta GPU no sabe multiplicar». La declaracion estaba mal,
    no la derivacion: se corrigio alli, que es el sitio que el repo tiene para
    decir que buscar en el RTL.
    """
    perfil = 0
    if "mul_div" in capacidades:
        perfil |= (1 << 0) | (1 << 1)
    if "subword_memory" in capacidades:
        perfil |= 1 << 2
    if "simt_debug" in capacidades:
        perfil |= 1 << 3
    return perfil


def mem_size_de(directorio: Path) -> int:
    """El tamano de la memoria principal, del `RAM_END` que declara el `top.v`.

    NO se usa `MMIO_MEM_SIZE_EBR` del mapa: esa constante son 32 KiB y describe
    la 6, mientras que la 12 --el otro prototipo sin SDRAM-- tiene 128 KiB. El
    unico sitio que sabe cuanta memoria tiene ESTA carpeta es su propio RTL.
    """
    import re
    for nombre in ("top.v", "top_bl8.v"):
        camino = directorio / nombre
        if not camino.exists():
            continue
        texto = camino.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"\.RAM_END\(\s*33'h([0-9a-fA-F_]+)\s*\)", texto)
        if match:
            return int(match.group(1).replace("_", ""), 16)
    raise SysidError(f"{directorio.name}: no se encontro `.RAM_END(33'h...)` "
                     f"en top.v ni en top_bl8.v")


def identidad(directorio: Path, senales: dict) -> dict[str, int]:
    """Las seis constantes de un prototipo."""
    capacidades = set(capabilities_from_rtl(directorio, senales))
    version = monitor_version_from_rtl(directorio)
    if version is None:
        raise SysidError(f"{directorio.name}: no se pudo leer "
                         f"VERSION_MAJOR/VERSION_MINOR de monitor.v")
    mayor, menor = version
    return {
        "SYSID_FOLDER": int(directorio.name.split(".", 1)[0]),
        "SYSID_ISA_PROFILE": isa_profile_de(capacidades),
        "SYSID_DEVICES": devices_de(directorio, capacidades),
        "SYSID_MEM_BASE": 0x0000_0000,
        "SYSID_MEM_SIZE": mem_size_de(directorio),
        "SYSID_MONITOR_VERSION": (mayor << 8) | menor,
    }


def render(directorio: Path, valores: dict[str, int]) -> str:
    lineas = [
        "// " + AVISO,
        "//",
        "// La identidad de este prototipo, para el bloque SYSTEM de MMIO v2",
        "// (1.isa/mmio.md §5). La LOGICA que sirve estos valores esta en",
        "// `sysid.v`, que es byte a byte identico en las diez carpetas; aqui",
        "// solo estan los numeros, que si son de cada una.",
        "//",
        f"// Prototipo: {directorio.name}",
        "",
        "// La guarda no es adorno: la 22 tiene DOS sistemas --`gpu_system.v` y",
        "// `gpu_system_bl8.v`-- y los dos se compilan juntos, asi que los dos",
        "// incluyen este fichero. Un `define` de Verilog es global al fichero",
        "// de compilacion, y redefinirlo avisa o falla segun la herramienta.",
        "`ifndef SYSID_PARAMS_VH",
        "`define SYSID_PARAMS_VH",
        "",
    ]
    for nombre, valor in valores.items():
        alto, bajo = f"{valor:08X}"[:4], f"{valor:08X}"[4:]
        lineas.append(f"`define {nombre:<24} 32'h{alto}_{bajo}")
    lineas += ["", "`endif"]
    return "\n".join(lineas) + "\n"


def generar() -> dict[Path, str]:
    """Lo que DEBERIA haber en disco, para los diez. No escribe."""
    senales = load_capability_signals(ROOT)
    salidas: dict[Path, str] = {}
    for directorio in prototipos():
        salidas[directorio / "sysid_params.vh"] = render(
            directorio, identidad(directorio, senales))
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
        description="Genera <carpeta>/sysid_params.vh desde el RTL")
    parser.add_argument("--check", action="store_true",
                        help="no escribe; sale con 1 si algo cambiaria")
    args = parser.parse_args()

    try:
        salidas = generar()
    except SysidError as error:
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
            destino.write_text(contenido, encoding="utf-8")

    relativo = [str(p.relative_to(ROOT)).replace("\\", "/") for p in cambiados]

    if args.check:
        if cambiados:
            print("desincronizado respecto al RTL:")
            for nombre in relativo:
                print(f"  {nombre}")
            print("ejecuta: ./tools/generate-sysid")
            return 1
        print(f"al dia: {len(salidas)} ficheros sysid_params.vh")
        return 0

    for nombre in relativo:
        print(f"escrito: {nombre}")
    if not cambiados:
        print("sin cambios")
    return 0
