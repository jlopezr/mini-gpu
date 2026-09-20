"""Los simuladores también se identifican, y su perfil de ISA no miente.

`SysIdDevice` es el gemelo en Python de `sysid.v`. Existe porque un programa que
se identifica —leer `SYS_ID`, mirar `ISA_PROFILE` y decidir— tiene que poder
probarse **sin placa**; si no, el único sitio donde corre es el hardware, que es
al revés de como se trabaja aquí.

Lo que estos tests protegen es que el bloque diga la verdad. Escribir
`ISA_PROFILE` a mano es inevitable —no se deriva solo— pero dejarlo sin
contrastar es peor que no tenerlo: un perfil que promete lo que el modelo no
hace convierte una capacidad ausente en un fallo raro y tardío, en vez de en un
«esto no lo tengo». El RTL tiene exactamente esta prueba
(`test_el_perfil_de_isa_sale_del_rtl`); esto es la mitad que faltaba.

El caso que lo justifica es el bit SIMT en la MiniCPU. `SSY` y `BAR` se
decodifican en el simulador de CPU —tienen que hacerlo, para que el mismo
binario corra en las dos familias— pero son `pass`. Contar «lo decodifica» como
«lo tiene» declararía semántica SIMT que ese modelo no da.
"""

import importlib
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.sysid_device import (  # noqa: E402
    BIT_DIV, BIT_MUL, BIT_SIMT, BIT_SUBWORD, MAGIC, SysIdDevice,
)

# Simulador -> (carpeta, módulo, fichero donde se decodifican los opcodes).
SIMULADORES = {
    "cpu": (2, "minicpu_sim", ROOT / "2.cpu-sim-func" / "minicpu_sim.py"),
    "gpu": (11, "minigpu_sim", ROOT / "11.gpu-sim-func" / "minigpu_sim.py"),
}

# Bit -> cómo se reconoce en el fuente que el modelo lo EJECUTA. Los opcodes
# son los del juego: 0x0A MUL, 0x0C-0x0F DIV/DIVU/REM/REMU, 0x18-0x1D los
# accesos de 8 y 16 bits, 0x31/0x32 SSY y BAR.
RASGOS = {
    BIT_MUL: re.compile(r"opcode == 0x0A"),
    BIT_DIV: re.compile(r"opcode in \(0x0C|opcode == 0x0C"),
    BIT_SUBWORD: re.compile(r"opcode in \(0x18|opcode == 0x18"),
}


def cargar(nombre: str):
    carpeta, modulo, _ = SIMULADORES[nombre]
    ruta = ROOT / ("2.cpu-sim-func" if nombre == "cpu" else "11.gpu-sim-func")
    if str(ruta) not in sys.path:
        sys.path.insert(0, str(ruta))
    return importlib.import_module(modulo)


class SysIdDeviceTest(unittest.TestCase):
    def test_el_magic_y_la_carpeta(self):
        for nombre, (carpeta, _, _) in SIMULADORES.items():
            modulo = cargar(nombre)
            dispositivo = (modulo.CPU(1024).sysid if nombre == "cpu"
                           else modulo.System(1024, 8, 8).sysid)
            with self.subTest(simulador=nombre):
                # En v2 el magic tiene su PROPIA palabra en +0x00; ya no
                # viaja en los bits altos de SYSTEM_ID, que es el número de
                # carpeta pelado (§5.3).
                self.assertEqual(dispositivo.read(SysIdDevice.MAGIC_OFF), MAGIC)
                palabra = dispositivo.read(SysIdDevice.SYSTEM_ID)
                self.assertEqual(palabra >> 8, 0, "31:8 están reservados")
                self.assertEqual(palabra & 0xFF, carpeta)

    def test_declaran_su_propia_carpeta_y_no_la_placa_que_modelan(self):
        """2 y 11, no 21 ni 22. Hacerles decir «soy la 21» convertiría SYS_ID en
        una mentira útil, que es la peor clase: el simulador no tiene el mapa de
        memoria ni el juego de dispositivos de ninguna placa concreta."""
        modulo = cargar("cpu")
        self.assertEqual(modulo.CPU(1024).sysid.read(SysIdDevice.SYSTEM_ID) & 0xFF, 2)
        modulo = cargar("gpu")
        self.assertEqual(
            modulo.System(1024, 8, 8).sysid.read(SysIdDevice.SYSTEM_ID) & 0xFF, 11)

    def test_el_perfil_de_isa_es_el_que_el_modelo_ejecuta(self):
        """Escrito a mano pero CONTRASTADO, igual que en el RTL."""
        for nombre, (_, _, fuente) in SIMULADORES.items():
            texto = fuente.read_text(encoding="utf8")
            esperado = 0
            for bit, patron in RASGOS.items():
                if patron.search(texto):
                    esperado |= bit
            # El bit SIMT no se deriva de decodificar SSY: hay que EJECUTARLO.
            # En el simulador de CPU son `pass`.
            if nombre == "gpu":
                esperado |= BIT_SIMT

            modulo = cargar(nombre)
            dispositivo = (modulo.CPU(1024).sysid if nombre == "cpu"
                           else modulo.System(1024, 8, 8).sysid)
            with self.subTest(simulador=nombre):
                self.assertEqual(dispositivo.isa_profile,
                                 esperado,
                                 f"{nombre}: el fuente dice {esperado:#04x}")

    def test_el_bit_simt_es_cero_en_la_cpu_aunque_decodifique_ssy(self):
        """El caso que hace falta que esté escrito.

        `SSY` y `BAR` se decodifican en el simulador de CPU, y tienen que
        hacerlo: sin ellos el binario compartido no correría. Pero son `pass`,
        así que declarar SIMT prometería una semántica que no está.
        """
        texto = SIMULADORES["cpu"][2].read_text(encoding="utf8")
        self.assertIn("0x31, 0x32", texto, "el simulador ya no decodifica SSY/BAR")
        perfil = cargar("cpu").CPU(1024).sysid.isa_profile
        self.assertEqual(perfil & BIT_SIMT, 0)

    def test_el_modelo_de_ciclos_no_hereda_la_identidad_del_funcional(self):
        """El 25 hereda de `functional.System`, así que se llevaba el `sysid`
        del 11 puesto y contestaba «soy la 11».

        Heredarlo en silencio es PEOR que no tenerlo: un bloque de
        identificación que miente es justo lo que `SYS_ID` existe para evitar.
        Son dos modelos distintos de la misma ISA —uno funcional y otro con
        pipeline— y distinguirlos es su trabajo.
        """
        ciclos = ROOT / "25.gpu-sim-cycle-uarch"
        if str(ciclos) not in sys.path:
            sys.path.insert(0, str(ciclos))
        cargar("gpu")           # el funcional tiene que estar en el camino
        modulo = importlib.import_module("minigpu_cycle")
        sistema = modulo.System(1024, 8, 8)
        palabra = sistema.sysid.read(SysIdDevice.SYSTEM_ID)
        self.assertEqual(palabra & 0xFF, 25)
        self.assertEqual(sistema.sysid.read(SysIdDevice.MAGIC_OFF), MAGIC)
        # El perfil sí es el mismo: cambia CUÁNDO ejecuta, no QUÉ.
        funcional = cargar("gpu").System(1024, 8, 8)
        self.assertEqual(sistema.sysid.isa_profile,
                         funcional.sysid.isa_profile)

    def test_identificacion_rechaza_escrituras_y_offsets_reservados(self):
        dispositivo = SysIdDevice(folder=2, isa_profile=BIT_MUL)
        antes = dispositivo.read(SysIdDevice.SYSTEM_ID)
        for offset in range(0, 256, 4):
            with self.subTest(offset=offset):
                with self.assertRaises(RuntimeError):
                    dispositivo.write(offset, 0xDEAD_BEEF)
                # En v2 el bloque tiene SIETE palabras, hasta +0x18. Antes
                # eran cuatro y el corte estaba en 16.
                if offset > SysIdDevice.MONITOR_VERSION:
                    with self.assertRaises(RuntimeError):
                        dispositivo.read(offset)
        self.assertEqual(dispositivo.read(SysIdDevice.SYSTEM_ID), antes)
        self.assertEqual(dispositivo.read(SysIdDevice.DEVICES), 0)

    def test_se_lee_por_la_memoria_como_cualquier_mmio(self):
        """No basta con que el objeto exista: tiene que responder en
        0x80000000 cuando un programa hace LOAD."""
        cpu = cargar("cpu").CPU(1024)
        self.assertEqual(cpu.read_u32(0x8000_0000), MAGIC)


if __name__ == "__main__":
    unittest.main()
