"""Guiones de entrada de INPUT (`tools/input_script.py`) y sus opciones de CLI."""
import argparse
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "11.gpu-sim-func"))

from tools import hid_keys, input_script, sim_peripherals
from tools.sim_devices import InputDevice
import minigpu_sim


def play(text, keyboard=False, mouse=False, ticks=0):
    """Un dispositivo con el guion cargado y `ticks` instrucciones transcurridas."""
    device = InputDevice()
    if keyboard:
        device.connect_keyboard()
    if mouse:
        device.connect_mouse()
    device.attach_script(input_script.parse(text))
    for _ in range(ticks):
        device.tick()
    return device


def events(device):
    out = []
    while device.fifo:
        out.append(InputDevice.decode_event(device.read(InputDevice.EVENT_DATA)))
    return out


class HidKeysTest(unittest.TestCase):
    def test_usage_ids_de_la_spec(self):
        # Los de 1.isa/mmio.md §25.1.
        expected = {"A": 0x04, "B": 0x05, "SPACE": 0x2C, "RIGHT": 0x4F, "LEFT": 0x50,
                    "DOWN": 0x51, "UP": 0x52, "LCTRL": 0xE0, "LSHIFT": 0xE1, "RGUI": 0xE7}
        for name, usage in expected.items():
            self.assertEqual(hid_keys.usage_of(name), usage, name)

    def test_los_nombres_no_distinguen_mayusculas_y_aceptan_literales(self):
        self.assertEqual(hid_keys.usage_of("lshift"), 0xE1)
        self.assertEqual(hid_keys.usage_of("0x2C"), 0x2C)
        self.assertEqual(hid_keys.name_of(0x2C), "SPACE")
        self.assertEqual(hid_keys.name_of(0x99), "0x99")

    def test_tecla_desconocida_o_fuera_de_rango(self):
        # "0" no entra: es la tecla del dígito, no el Usage ID 0.
        for name in ("ZZ", "0x00", "0x100", ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                hid_keys.usage_of(name)

    def test_hay_un_usage_id_por_nombre_y_ninguno_se_repite_entre_letras_y_digitos(self):
        letters = [hid_keys.usage_of(c) for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"]
        self.assertEqual(len(set(letters)), len(letters))

    def test_ascii_us(self):
        self.assertEqual(hid_keys.keystrokes("a"), [["A"]])
        self.assertEqual(hid_keys.keystrokes("A"), [["LSHIFT", "A"]])
        self.assertEqual(hid_keys.keystrokes("!"), [["LSHIFT", "1"]])
        self.assertEqual(hid_keys.keystrokes("\n"), [["ENTER"]])
        with self.assertRaises(ValueError):
            hid_keys.keystrokes("ñ")


class ParseTest(unittest.TestCase):
    def test_instantes_absolutos_y_relativos(self):
        actions = input_script.parse(
            "@0 keyboard connect\n+10 key down A\n+5 key up A\n@100 key press B\n")
        self.assertEqual([a.at for a in actions], [0, 10, 15, 100, 100])

    def test_comentarios_y_lineas_en_blanco(self):
        actions = input_script.parse("# nada\n\n@0 keyboard connect   # conecta\n")
        self.assertEqual(len(actions), 1)

    def test_errores_con_numero_de_linea(self):
        casos = {
            "key down A": "empieza por @N o +N",
            "@0 baila": "acción desconocida",
            "@0 key down": "key admite",
            "@0 key down ZZ": "tecla desconocida",
            "@0 mouse move 1": "mouse admite",
            "@0 mouse move a b": "no es un entero",
            "@0 mouse button 40 down": "fuera de rango",
            "@0 mouse button left pulsar": "down",
            "@10 keyboard connect\n@5 keyboard disconnect": "anterior",
            "@0": "falta la acción",
        }
        for text, fragment in casos.items():
            with self.subTest(text=text), self.assertRaises(ValueError) as error:
                input_script.parse(text)
            self.assertIn(fragment, str(error.exception))
            self.assertIn("línea", str(error.exception))

    def test_el_numero_de_linea_es_el_de_la_linea_mala(self):
        with self.assertRaises(ValueError) as error:
            input_script.parse("@0 keyboard connect\n\n@1 baila\n")
        self.assertIn("línea 3", str(error.exception))


class CheckTest(unittest.TestCase):
    def test_una_tecla_sin_teclado_conectado_falla_al_cargar(self):
        actions = input_script.parse("@0 key press A")
        with self.assertRaises(ValueError) as error:
            input_script.check(actions)
        self.assertIn("línea 1", str(error.exception))
        self.assertIn("teclado no presente", str(error.exception))

    def test_el_ratón_sin_conectar_falla(self):
        with self.assertRaises(ValueError):
            input_script.check(input_script.parse("@0 mouse move 1 1"))

    def test_keyboard_pedido_por_flag_cuenta_como_conectado(self):
        input_script.check(input_script.parse("@0 key press A"), keyboard=True)

    def test_conectar_en_el_propio_guion_basta(self):
        input_script.check(input_script.parse("@0 keyboard connect\n@1 key press A"))


class PlaybackTest(unittest.TestCase):
    def test_arroba_cero_se_aplica_al_cargar(self):
        device = play("@0 keyboard connect A")
        self.assertTrue(device.keyboard_present)
        self.assertEqual(events(device), [
            {"type": "key", "usage": 0x04, "down": True, "modifiers": 0}])

    def test_las_acciones_ocurren_en_su_instante(self):
        device = play("@0 keyboard connect\n@5 key down A", ticks=4)
        self.assertEqual(events(device), [])
        device.tick()
        self.assertEqual([e["usage"] for e in events(device)], [0x04])

    def test_varias_acciones_en_el_mismo_instante_en_orden(self):
        device = play("@0 keyboard connect\n@1 key down A\n@1 key up A", ticks=1)
        self.assertEqual([e["down"] for e in events(device)], [True, False])

    def test_key_press_son_dos_reports(self):
        device = play("@0 keyboard connect\n@0 key press A")
        self.assertEqual([e["down"] for e in events(device)], [True, False])

    def test_varias_teclas_en_un_comando_son_un_solo_report(self):
        device = play("@0 keyboard connect\n@0 key down LSHIFT A")
        # Un report: el evento de modificadores va antes que el DOWN.
        self.assertEqual(events(device), [
            {"type": "modifiers", "modifiers": 0x02},
            {"type": "key", "usage": 0x04, "down": True, "modifiers": 0x02}])

    def test_type_teclea_con_shift_para_las_mayusculas(self):
        device = play('@0 keyboard connect\n@0 type "Hi"')
        self.assertEqual(events(device), [
            {"type": "modifiers", "modifiers": 0x02},
            {"type": "key", "usage": 0x0B, "down": True, "modifiers": 0x02},    # H
            {"type": "key", "usage": 0x0B, "down": False, "modifiers": 0x00},
            {"type": "modifiers", "modifiers": 0x00},
            {"type": "key", "usage": 0x0C, "down": True, "modifiers": 0x00},    # i
            {"type": "key", "usage": 0x0C, "down": False, "modifiers": 0x00},
        ])

    def test_type_con_escapes_y_almohadilla(self):
        device = play('@0 keyboard connect\n@0 type "a#\\n"')
        usages = [e["usage"] for e in events(device) if e["type"] == "key" and e["down"]]
        self.assertEqual(usages, [0x04, 0x20, 0x28])       # a, # (Shift+3), Enter

    def test_raton(self):
        device = play("@0 mouse connect\n@0 mouse move 12 -5\n@0 mouse button left click\n"
                      "@0 mouse report 0b100 3 4")
        self.assertEqual(events(device), [
            {"type": "move", "dx": 12, "dy": -5},
            {"type": "button", "button": 0, "down": True},
            {"type": "button", "button": 0, "down": False},
            {"type": "button", "button": 2, "down": True},
            {"type": "move", "dx": 3, "dy": 4},
        ])

    def test_conectar_con_botones_pulsados(self):
        device = play("@0 mouse connect left right")
        self.assertEqual(device.read(InputDevice.MOUSE_BUTTONS), 0b11)

    def test_desconexion_desde_el_guion(self):
        device = play("@0 keyboard connect\n@0 key down A\n@5 keyboard disconnect", ticks=5)
        self.assertFalse(device.keyboard_present)
        self.assertEqual(device.read(InputDevice.KEY_STATE0), 0)

    def test_la_gpu_funcional_avanza_el_guion_con_sus_ticks(self):
        device = InputDevice()
        device.attach_script(input_script.parse("@0 keyboard connect\n@3 key press A"))
        system = minigpu_sim.System(input_device=device)
        for _ in range(2):
            system.tick_devices()
        self.assertEqual(events(device), [])
        system.tick_devices()
        self.assertEqual(len(events(device)), 2)


def namespace(**kwargs):
    base = dict(video=False, frame_instructions=1000, halt_after_swaps=None,
                frame_output=None, console=False, console_output=None,
                console_image=None, console_font="cpc464", serial=False,
                serial_input=None, serial_output=None, keyboard=False, mouse=False,
                input_script=None)
    base.update(kwargs)
    return argparse.Namespace(**base)


class CliOptionsTest(unittest.TestCase):
    def test_sin_opciones_no_hay_input(self):
        self.assertIsNone(sim_peripherals.from_arguments(namespace())["input_device"])

    def test_keyboard_y_mouse_conectan_desde_el_principio(self):
        device = sim_peripherals.from_arguments(namespace(keyboard=True))["input_device"]
        self.assertTrue(device.keyboard_present)
        self.assertFalse(device.mouse_present)
        device = sim_peripherals.from_arguments(namespace(mouse=True))["input_device"]
        self.assertTrue(device.mouse_present)

    def test_el_guion_habilita_input_sin_conectar_nada(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "entrada.txt"
            path.write_text("@5 keyboard connect\n", encoding="utf-8")
            device = sim_peripherals.from_arguments(namespace(input_script=path))["input_device"]
            self.assertFalse(device.keyboard_present)

    def test_un_guion_con_error_falla_al_construir(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "entrada.txt"
            path.write_text("@0 key press A\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                sim_peripherals.from_arguments(namespace(input_script=path))

    def test_namespace_antiguo_sin_las_opciones_nuevas_sigue_valiendo(self):
        args = namespace()
        for name in ("keyboard", "mouse", "input_script"):
            delattr(args, name)
        self.assertIsNone(sim_peripherals.from_arguments(args)["input_device"])


class CpuEndToEndTest(unittest.TestCase):
    """Un programa de MiniCPU lee los eventos que el guion inyecta."""

    PROGRAM = """MOVHI R1, 0x8060
MOVHI R2, 0x8010
MOVI R5, 4
wait: LOAD R3, R1, 4
ANDI R3, R3, 0xFF
BEQ R3, R0, wait
LOAD R4, R1, 0
STORE R4, R2, 0
ADDI R5, R5, -1
BNE R5, R0, wait
HALT"""

    def run_cli(self, tmp, *options):
        program = Path(tmp) / "leer_input.asm"
        program.write_text(self.PROGRAM, encoding="utf-8")
        output = Path(tmp) / "salida.bin"
        result = subprocess.run(
            [sys.executable, str(ROOT / "2.cpu-sim-func" / "minicpu_sim.py"), str(program),
             "--serial-output", str(output), "--run-limit", "100000", *options],
            capture_output=True, text=True)
        return result, output

    def test_teclear_ab_llega_al_programa(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "entrada.txt"
            script.write_text('@0 keyboard connect\n@200 type "ab"\n', encoding="utf-8")
            result, output = self.run_cli(tmp, "--input-script", str(script))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("ERROR", result.stdout)
            # Cuatro eventos (A down/up, B down/up); el byte bajo es el Usage ID.
            self.assertEqual(output.read_bytes(), b"\x04\x04\x05\x05")

    def test_un_guion_malo_se_rechaza_antes_de_simular(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "entrada.txt"
            script.write_text("@0 key press A\n", encoding="utf-8")
            result, _ = self.run_cli(tmp, "--input-script", str(script))
            self.assertEqual(result.returncode, 2)
            # Sin acentos: la codificación de stderr depende de la consola.
            self.assertIn("key press A", result.stderr)
            self.assertIn("teclado no presente", result.stderr)

    def test_sin_input_el_acceso_da_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            result, _ = self.run_cli(tmp)
            self.assertIn("ERROR", result.stdout)


if __name__ == "__main__":
    unittest.main()
