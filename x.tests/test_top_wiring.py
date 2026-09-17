"""Toda entrada del monitor tiene que estar CONDUCIDA en el top.

El fallo que motiva esto: `mem_read_word` --la palabra de 32 bits que contesta
READ_WORD-- estaba declarada en el top de la 10 y de la 16, conectada al
monitor, y **no la conducia nadie**. El adaptador ya producia el valor; sólo
faltaba el cable. En placa, READ_WORD devolvia una X.

Por qué no lo vio ninguna prueba, que es la parte interesante: `monitor_tb`
prueba el monitor contra una memoria falsa, y ahí `mem_read_word` es un `reg`
del propio banco, que el banco conduce. O sea que la señal siempre tenía valor
en simulación justamente porque el banco suplía lo que al top le faltaba. Y
ningún testbench de esas carpetas instancia `top`, así que su cableado no se
simulaba en ninguna parte.

De ahí la forma de esta prueba. No simula: lee el RTL y comprueba que cada
señal que entra al monitor sale de algún sitio -- un `assign`, la salida de
otro módulo, o un `always`. Es barato, cubre las diez carpetas, y ataca
exactamente el hueco que dejan los bancos de unidad.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROTOTIPOS = ("6.fpga-cpu", "10.fpga-cpu-ram", "12.fpga-gpu", "14.fpga-gpu-ram",
              "16.fpga-cpu-hdmi", "17.fpga-gpu-ram-v2", "18.fpga-cpu-hdmi-bl8",
              "19.fpga-cpu-hdmi-ls", "21.fpga-cpu-hdmi-alu", "22.fpga-gpu-bl8")

# Las entradas del monitor que traen DATOS de vuelta. Las de control
# (`clk`, `reset`) las conduce el reloj y no hace falta mirarlas.
ENTRADAS = ("mem_read_data", "mem_read_word", "mem_ready", "mem_error",
            "cpu_halted", "cpu_pc", "cpu_debug_register_data")


def _cerrar(texto: str, desde: int) -> int:
    """Índice tras el paréntesis que cierra el abierto en `desde`."""
    profundidad, cursor = 1, desde
    while profundidad and cursor < len(texto):
        profundidad += {"(": 1, ")": -1}.get(texto[cursor], 0)
        cursor += 1
    return cursor


def puertos_del_monitor(texto: str) -> dict:
    """{puerto: señal} de la instanciación de `monitor` en este fichero.

    Los paréntesis se equilibran en vez de buscar el primer cierre: la familia
    GPU instancia el monitor CON PARÁMETROS --`.VERSION_MAJOR(8'h02)`, cinco
    ventanas...-- y un `[^)]*` se corta dentro del primero de ellos. Con eso
    esta prueba sólo miraba las seis carpetas de CPU y decía que todo bien.
    """
    con_parametros = re.search(r"\bmonitor\s*#\s*\(", texto)
    if con_parametros:
        # Saltar la lista de parámetros entera y buscar la de puertos detrás.
        tras_parametros = _cerrar(texto, con_parametros.end())
        siguiente = re.compile(r"\s*\w+\s*\(").match(texto, tras_parametros)
        if not siguiente:
            return {}
        inicio = siguiente.end()
    else:
        simple = re.search(r"\bmonitor\s+\w+\s*\(", texto)
        if not simple:
            return {}
        inicio = simple.end()
    cursor = _cerrar(texto, inicio)
    lista = texto[inicio:cursor]
    return {p: s for p, s in re.findall(r"\.(\w+)\s*\(\s*([\w\[\]:]+)\s*\)", lista)}


def esta_conducida(texto: str, senal: str, sin: str) -> bool:
    """¿Sale `senal` de algún sitio, aparte de entrar al monitor?"""
    resto = texto.replace(sin, "")
    return bool(
        re.search(rf"\bassign\s+{re.escape(senal)}\b", resto)
        # salida de otro módulo: .lo_que_sea(senal)
        or re.search(rf"\.\w+\s*\(\s*{re.escape(senal)}\s*\)", resto)
        or re.search(rf"\b{re.escape(senal)}\s*<=", resto)
        or re.search(rf"\b{re.escape(senal)}\s*=", resto)
    )


class CableadoDelTopTest(unittest.TestCase):
    def test_toda_entrada_del_monitor_sale_de_algun_sitio(self):
        revisados = 0
        for prototipo in PROTOTIPOS:
            for top in sorted((ROOT / prototipo).glob("top*.v")):
                if top.name.endswith("_tb.v"):
                    continue
                texto = top.read_text(encoding="utf8")
                puertos = puertos_del_monitor(texto)
                if not puertos:
                    continue
                revisados += 1
                for puerto in ENTRADAS:
                    senal = puertos.get(puerto)
                    if senal is None:
                        continue        # este prototipo no tiene ese puerto
                    conexion = f".{puerto}({senal})"
                    with self.subTest(prototipo=prototipo, top=top.name,
                                      puerto=puerto):
                        self.assertTrue(
                            esta_conducida(texto, senal, conexion),
                            f"{prototipo}/{top.name}: {senal} entra al monitor "
                            f"por .{puerto} y no la conduce nadie")
        # Que la prueba no pase por no haber mirado nada.
        self.assertGreaterEqual(revisados, len(PROTOTIPOS))


if __name__ == "__main__":
    unittest.main()
