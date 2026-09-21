"""La identidad generada de cada prototipo: `<carpeta>/sysid_params.vh`.

Vigila tres cosas distintas, y ninguna cubre a las otras. Es el mismo reparto
que `test_mmio_map.py`, por la misma razón:

1. **Sincronía** — lo que hay en disco es lo que sale del generador hoy.
   No dice nada sobre si los valores son correctos.
2. **Conformidad** — los valores son los que `mmio.md` §5 y el RTL implican.
   Los números están escritos **a mano** adrede: derivarlos del mismo sitio que
   el generador convertiría el test en una tautología, y un generador con la
   regla equivocada pasaría, que es justo el fallo que importa.
3. **Que nadie lo escriba a mano en el RTL** — un literal reintroducido en un
   `top.v` vuelve a crear la gemela que §5.4 quiere quitar, y no fallaría nada.

POR QUE EXISTE. Cuando se escribió el generador, el bitmap estaba a mano en
once sitios de diez carpetas y tenía **seis errores**: la 6 y la 10 no
declaraban su propio bit de CPU, y la 18, la 19, la 21 y la 22 instancian
`memory_fabric_4` sin declarar el bit FABRIC. Ninguno rompía nada — un bit de
más o de menos en un bitmap descriptivo no da error, sólo miente.
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.generate_sysid import (  # noqa: E402
    desincronizados, generar, prototipos,
)

#: Lo que cada prototipo DEBE declarar, escrito a mano desde `mmio.md` §5.4 y
#: lo que se ve en el RTL. Si el generador cambia de regla, esto salta.
#:
#:   bit 0 SYSTEM · 1 FABRIC · 2 SDRAM · 3 EBR · 4 SERIAL · 5 VIDEO
#:   bit 9 CPU · 10 GPU
ESPERADO = {
    #                    DEVICES  ISA   MEM_SIZE
    "6.fpga-cpu":        (0x0209, 0x3, 0x0000_8000),
    "10.fpga-cpu-ram":   (0x0205, 0x0, 0x0200_0000),
    "12.fpga-gpu":       (0x0409, 0xB, 0x0002_0000),
    "14.fpga-gpu-ram":   (0x0405, 0xB, 0x0200_0000),
    "16.fpga-cpu-hdmi":  (0x0225, 0x3, 0x0200_0000),
    "17.fpga-gpu-ram-v2": (0x0405, 0xB, 0x0200_0000),
    "18.fpga-cpu-hdmi-bl8": (0x0227, 0x3, 0x0200_0000),
    "19.fpga-cpu-hdmi-ls": (0x0237, 0x7, 0x0200_0000),
    "21.fpga-cpu-hdmi-alu": (0x0237, 0x7, 0x0200_0000),
    "22.fpga-gpu-bl8":   (0x0427, 0xB, 0x0200_0000),
}

DEFINE = re.compile(r"^`define\s+(SYSID_\w+)\s+32'h([0-9A-Fa-f_]+)\s*$",
                    re.MULTILINE)


def _leer(carpeta: Path) -> dict[str, int]:
    texto = (carpeta / "sysid_params.vh").read_text(encoding="utf-8")
    return {n: int(v.replace("_", ""), 16) for n, v in DEFINE.findall(texto)}


class SincroniaTest(unittest.TestCase):
    def test_lo_generado_esta_al_dia(self):
        fuera = desincronizados()
        self.assertEqual(
            [], fuera,
            "hay sysid_params.vh desincronizados del RTL. "
            "Ejecuta ./tools/generate-sysid y vuelve a commitear:\n  "
            + "\n  ".join(str(p) for p in fuera))

    def test_hay_uno_por_prototipo(self):
        """Diez carpetas con `sysid.v`, diez ficheros. Si alguien añade un
        prototipo y no regenera, aquí salta y no tres semanas después."""
        self.assertEqual(10, len(generar()))
        self.assertEqual({p.name for p in prototipos()}, set(ESPERADO))


class ConformidadTest(unittest.TestCase):
    def test_devices_isa_y_memoria(self):
        for nombre, (devices, isa, memoria) in ESPERADO.items():
            with self.subTest(nombre):
                valores = _leer(ROOT / nombre)
                self.assertEqual(devices, valores["SYSID_DEVICES"])
                self.assertEqual(isa, valores["SYSID_ISA_PROFILE"])
                self.assertEqual(memoria, valores["SYSID_MEM_SIZE"])

    def test_el_numero_de_carpeta_es_el_del_directorio(self):
        """No se puede poner mal sin renombrar la carpeta, que es el punto."""
        for carpeta in prototipos():
            with self.subTest(carpeta.name):
                self.assertEqual(int(carpeta.name.split(".", 1)[0]),
                                 _leer(carpeta)["SYSID_FOLDER"])

    def test_cada_prototipo_declara_su_nucleo_y_una_memoria(self):
        """§5.4: el bitmap describe **dispositivos presentes**, así que un
        prototipo declara su núcleo y exactamente una clase de memoria.

        Lo segundo es lo que caza un SDRAM mal detectado: al escribir el
        generador, una regex que no contemplaba `#(...)` en la instanciación
        hacía que la 14, la 17 y la 22 salieran declarando EBR."""
        for carpeta in prototipos():
            with self.subTest(carpeta.name):
                devices = _leer(carpeta)["SYSID_DEVICES"]
                cpu, gpu = devices >> 9 & 1, devices >> 10 & 1
                self.assertEqual(1, cpu + gpu, "ni CPU ni GPU, o las dos")
                sdram, ebr = devices >> 2 & 1, devices >> 3 & 1
                self.assertEqual(1, sdram + ebr, "ni SDRAM ni EBR, o las dos")
                self.assertTrue(devices & 1, "SYSTEM siempre presente (§5.4)")

    def test_la_memoria_cuadra_con_la_clase_declarada(self):
        """Los 128 KiB de la 12 y los 32 KiB de la 6 son los dos EBR, así que
        `MMIO_MEM_SIZE_EBR` no vale como comprobación: lo único que se puede
        exigir es que quien declara SDRAM tenga los 32 MiB."""
        for carpeta in prototipos():
            with self.subTest(carpeta.name):
                valores = _leer(carpeta)
                if valores["SYSID_DEVICES"] >> 2 & 1:
                    self.assertEqual(0x0200_0000, valores["SYSID_MEM_SIZE"])
                else:
                    self.assertLess(valores["SYSID_MEM_SIZE"], 0x0200_0000)


class NadieLoEscribeAManoTest(unittest.TestCase):
    """§5.4: «`DEVICES` no se escribe a mano en cada `top.v`»."""

    LITERAL = re.compile(
        r"\.(DEVICES|MEM_SIZE|MEM_BASE|MONITOR_VERSION|ISA_PROFILE|FOLDER)"
        r"\(\s*3?2?'[hd]", re.IGNORECASE)

    def test_ningun_rtl_de_prototipo_pasa_un_literal(self):
        culpables = []
        for carpeta in prototipos():
            for fuente in sorted(carpeta.glob("*.v")):
                # Los bancos sí pueden: montan piezas sueltas con valores
                # inventados, y no son la identidad de nadie.
                if fuente.name.endswith("_tb.v"):
                    continue
                texto = fuente.read_text(encoding="utf-8", errors="replace")
                for match in self.LITERAL.finditer(texto):
                    linea = texto[:match.start()].count("\n") + 1
                    culpables.append(
                        f"{fuente.relative_to(ROOT)}:{linea}: {match.group(0)}")
        self.assertEqual(
            [], culpables,
            "la identidad se pasa por literal. Usa los `define` de "
            "sysid_params.vh, que genera ./tools/generate-sysid:\n  "
            + "\n  ".join(culpables))


if __name__ == "__main__":
    unittest.main()
