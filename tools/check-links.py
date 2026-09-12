"""Comprueba que todos los enlaces relativos de los .md apuntan a algo que existe.

Nace de dos fallos reales del repositorio, los dos iguales: algo cambio de sitio
y la referencia se quedo atras, sin que nada avisara.

  - test_simt_regions.py buscaba los casos de Mandelbrot en cases-gpu/ despues
    de que se reagruparan bajo cases-gpu/programs/. Llevaba meses fallando.
  - El .gitignore de 16.fpga-cpu-hdmi ignoraba los binarios por nombre, y los de
    tear_demo entraron en el repositorio porque no encajaban en ningun patron.

Mover ficheros sin verificar es el riesgo. Esto es la verificacion.

Uso:
    .venv/Scripts/python.exe tools/check-links.py

Devuelve 1 si algun enlace esta roto, para poder encadenarlo.
"""

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "_build", "__pycache__", ".venv", "node_modules"}

# [texto](destino), ignorando imagenes y enlaces de referencia.
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

# Un enlace externo o un ancla dentro del propio documento no se comprueba.
EXTERNAL = ("http://", "https://", "mailto:", "#", "<")

# Los artefactos de sintesis solo existen despues de compilar, asi que un
# enlace a _build/ no esta roto por no encontrarse ahora mismo. La ruta si
# tiene que ser la correcta para quien lea el documento, pero eso no se puede
# comprobar sin construir.
GENERATED = ("_build/",)


def markdown_files():
    for path in sorted(ROOT.rglob("*.md")):
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        yield path


def main():
    checked = 0
    broken = []

    for path in markdown_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for target in LINK.findall(line):
                if target.startswith(EXTERNAL):
                    continue
                # Se descarta el ancla: solo interesa que el fichero exista.
                destination = unquote(target.split("#", 1)[0])
                if not destination:
                    continue
                if any(part in destination for part in GENERATED):
                    continue
                checked += 1
                if not (path.parent / destination).exists():
                    where = path.relative_to(ROOT).as_posix()
                    broken.append(f"{where}:{line_number}  ->  {target}")

    for entry in broken:
        print(f"ROTO  {entry}")

    total = len(list(markdown_files()))
    if broken:
        print(f"\n{len(broken)} de {checked} enlaces rotos en {total} ficheros .md")
        return 1

    print(f"OK: {checked} enlaces relativos en {total} ficheros .md, ninguno roto")
    return 0


if __name__ == "__main__":
    sys.exit(main())
