"""El programa del banco de frame completo de la 21, y sus tres invariantes.

POR QUE EXISTE ESTE FICHERO. `video_fullframe_tb.v` carga un `.hex` versionado
en vez de ensamblar al vuelo, porque no hay paso de build entre escribir un
`.asm` y correr `apio test`. Un fichero generado y versionado se queda viejo en
silencio, y este se quedo viejo de las tres formas posibles a la vez:

  1. **El fuente equivocado.** La cabecera del banco y el README decian que el
     .hex salia de `examples/fullframe.asm`, y no: ese programa pone el
     framebuffer en 0x01000000, que en el modelo de SDRAM del banco es la fila
     4096 de un banco de 128. Regenerarlo "como ponia ahi" hizo que el modelo
     contase 60 009 violaciones, que es como se ve un acceso a una fila que no
     existe. El sintoma no se parecia nada a la causa.
  2. **El formato equivocado.** El .hex se habia escrito a mano en medias
     palabras de 16 bits y el ensamblador emite palabras de 32. Regenerarlo con
     la herramienta cargaba un programa que no era el programa.
  3. **La deriva entre los dos.** El de la placa y el del banco son el mismo
     programa salvo dos constantes. Si se tocan por separado, el banco deja de
     probar lo que corre en la placa sin que nada falle.

De ahi los tres tests. El (2) ya no puede volver a pasar --el banco lee
palabras-- pero el test se queda igual: es lo que fija el formato.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INC = ROOT / "x.tests" / "inc"


def _carpetas():
    """Toda carpeta que tenga el trio completo, no una lista escrita a mano.

    Se descubren solas a proposito: la 19 necesito exactamente estas mismas
    comprobaciones, y con la carpeta cableada arriba habria habido que acordarse
    de anadirla --que es justo como la cabecera del banco de la 21 llego a
    mentir durante meses sin que nadie lo notara--. Cuando migre la 18, queda
    cubierta el dia que cree su `fullframe_tb.asm`.
    """
    encontradas = []
    for carpeta in sorted(ROOT.glob("*.fpga-*")):
        banco = carpeta / "fullframe_tb.asm"
        placa = carpeta / "examples" / "fullframe.asm"
        fichero_hex = carpeta / "fullframe.hex"
        bench = carpeta / "video_fullframe_tb.v"
        if all(p.exists() for p in (banco, placa, fichero_hex, bench)):
            encontradas.append((carpeta.name, placa, banco, fichero_hex, bench))
    return encontradas


CARPETAS = _carpetas()


def _ensamblador():
    spec = importlib.util.spec_from_file_location(
        "miniisa_asm_para_fullframe", ROOT / "1.isa" / "miniisa_asm.py")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def _cuerpo(texto: str) -> list[str]:
    """Lo que viene tras el ultimo `.equ`: el programa sin sus constantes."""
    lineas = texto.replace("\r\n", "\n").split("\n")
    ultimo = max(i for i, linea in enumerate(lineas)
                 if linea.strip().lower().startswith(".equ"))
    return lineas[ultimo + 1:]


class FullframeFixtureTest(unittest.TestCase):

    def test_hay_carpetas_que_comprobar(self):
        """Que el descubrimiento no se quede a cero y el fichero entero pase
        por no mirar nada."""
        self.assertGreaterEqual(
            len(CARPETAS), 2,
            f"solo se han encontrado {len(CARPETAS)} carpetas con el trio "
            f"fullframe; el descubrimiento ha dejado de funcionar")

    def test_el_hex_sale_del_fuente_del_banco(self):
        asm = _ensamblador()
        for nombre, _placa, banco, fichero_hex, _bench in CARPETAS:
            with self.subTest(carpeta=nombre):
                imagen = asm.assemble_bytes(
                    banco.read_text(encoding="utf-8"),
                    base_dir=banco.parent, origin=str(banco),
                    include_dirs=(INC,))
                esperado = "".join(
                    f"{int.from_bytes(imagen[i:i + 4], 'little'):08X}\n"
                    for i in range(0, len(imagen), 4))
                self.assertEqual(
                    fichero_hex.read_text(
                        encoding="ascii").replace("\r\n", "\n"),
                    esperado,
                    f"{nombre}/fullframe.hex no cuadra con fullframe_tb.asm; "
                    f"regeneralo desde esa carpeta:\n"
                    "  python ..\\1.isa\\miniisa_asm.py fullframe_tb.asm "
                    "--hex fullframe.hex -I ..\\x.tests\\inc")

    def test_los_dos_programas_solo_difieren_en_las_bases(self):
        for nombre, placa, banco, _hex, _bench in CARPETAS:
            with self.subTest(carpeta=nombre):
                self.assertEqual(
                    _cuerpo(banco.read_text(encoding="utf-8")),
                    _cuerpo(placa.read_text(encoding="utf-8")),
                    f"{nombre}: el programa del banco y el de la placa se han "
                    f"separado: ya no se esta simulando lo que corre en la placa")

    def test_las_bases_del_banco_caben_en_las_filas_que_modela(self):
        """La invariante que el .hex equivocado rompio, dicha en numeros.

        Fila = bits [23:11] de la direccion de PALABRA, o sea [24:12] de la de
        byte. Se comprueban las dos bases y el final del segundo buffer.

        `filas` se lee del propio banco y no se copia: si alguien agranda el
        modelo, esto se entera solo.
        """
        for nombre, _placa, banco, _hex, bench in CARPETAS:
            with self.subTest(carpeta=nombre):
                filas = int(re.search(
                    r"\.ROWS\((\d+)\)",
                    bench.read_text(encoding="utf-8")).group(1))
                texto = banco.read_text(encoding="utf-8")
                bases = [int(valor, 16) for valor in
                         re.findall(r"^\.equ FB_\w+_ADDR,\s*(0x[0-9A-Fa-f]+)",
                                    texto, re.MULTILINE)]
                self.assertEqual(len(bases), 2)
                for base in bases + [max(bases) + 320 * 240 * 2 - 1]:
                    self.assertLess(
                        (base >> 12) & 0x1FFF, filas,
                        f"{nombre}: 0x{base:08X} cae en una fila que el modelo "
                        f"no tiene; el modelo lo cuenta como violacion JEDEC, "
                        f"una por acceso")


if __name__ == "__main__":
    unittest.main()
