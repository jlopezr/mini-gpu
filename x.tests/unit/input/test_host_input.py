"""Traducción de teclado y ratón del anfitrión a reports de INPUT.

El log de Tk en Windows (teclado español) está en el docstring de
`tools/host_input.py`; estos tests fijan cada decisión que salió de él.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tools import hid_keys, host_input
from tools.host_input import (EXTENDED_STATE_BIT, HostKeyboard, HostMouse,
                              host_usage, usage_from_scancode)


def usage(name):
    return hid_keys.usage_of(name)


class ScancodeTableTest(unittest.TestCase):
    def test_letras_y_digitos_por_posicion_fisica(self):
        # Fila QWERTY: scancodes 0x10..0x19, y A..Z en su sitio HID.
        for scancode, letter in zip(range(0x10, 0x1A), "QWERTYUIOP"):
            self.assertEqual(usage_from_scancode(scancode, False), usage(letter), letter)
        self.assertEqual(usage_from_scancode(0x1E, False), usage("A"))
        self.assertEqual(usage_from_scancode(0x02, False), usage("1"))
        self.assertEqual(usage_from_scancode(0x0B, False), usage("0"))

    def test_la_tecla_enie_es_la_del_punto_y_coma_us(self):
        # En un teclado español la ñ está donde el ; de un US: scancode 0x27.
        self.assertEqual(usage_from_scancode(0x27, False), usage("SEMICOLON"))

    def test_extendidas(self):
        self.assertEqual(usage_from_scancode(0x1C, False), usage("ENTER"))
        self.assertEqual(usage_from_scancode(0x1C, True), usage("KP_ENTER"))
        self.assertEqual(usage_from_scancode(0x1D, True), usage("RCTRL"))
        self.assertEqual(usage_from_scancode(0x38, True), usage("RALT"))
        for scancode, name in ((0x4B, "LEFT"), (0x48, "UP"), (0x4D, "RIGHT"), (0x50, "DOWN")):
            self.assertEqual(usage_from_scancode(scancode, True), usage(name))

    def test_las_teclas_de_la_spec(self):
        # 1.isa/mmio.md §25.1.
        self.assertEqual(usage_from_scancode(0x39, False), 0x2C)        # Space
        self.assertEqual(usage_from_scancode(0x2A, False), 0xE1)        # Left Shift
        self.assertEqual(usage_from_scancode(0x1D, False), 0xE0)        # Left Ctrl
        self.assertEqual(usage_from_scancode(0x5C, True), 0xE7)         # Right GUI

    def test_sin_colisiones_de_usage(self):
        self.assertEqual(len(set(host_input.SCAN_TO_HID.values())),
                         len(host_input.SCAN_TO_HID))

    def test_scancode_desconocido(self):
        self.assertIsNone(usage_from_scancode(0x7F, False))


class HostUsageTest(unittest.TestCase):
    def fake_scancode(self, table):
        return lambda vk: table.get(vk, 0)

    def test_traduce_por_scancode_si_lo_hay(self):
        scancode_of = self.fake_scancode({192: 0x27})       # VK_OEM_3 = ñ
        self.assertEqual(host_usage(192, 0x8, "ntilde", scancode_of=scancode_of),
                         usage("SEMICOLON"))

    def test_el_bit_extendido_distingue_enter(self):
        scancode_of = self.fake_scancode({13: 0x1C})
        self.assertEqual(host_usage(13, 0x8, "Return", scancode_of=scancode_of),
                         usage("ENTER"))
        self.assertEqual(host_usage(13, 0x8 | EXTENDED_STATE_BIT, "Return",
                                    scancode_of=scancode_of), usage("KP_ENTER"))

    def test_los_modificadores_se_resuelven_aparte(self):
        for vk in (16, 17, 18):
            self.assertIsNone(host_usage(vk, 0, "Shift_L",
                                         scancode_of=self.fake_scancode({vk: 0x2A})))

    def test_sin_scancodes_cae_al_keysym(self):
        self.assertEqual(host_usage(65, 0, "a"), usage("A"))
        self.assertEqual(host_usage(112, 0, "F1"), usage("F1"))
        self.assertEqual(host_usage(13, 0, "Return"), usage("ENTER"))
        self.assertEqual(host_usage(27, 0, "Escape"), usage("ESC"))
        self.assertEqual(host_usage(37, 0, "Left"), usage("LEFT"))
        self.assertIsNone(host_usage(0, 0, "ntilde"))

    @unittest.skipUnless(sys.platform == "win32", "MapVirtualKey solo existe en Windows")
    def test_map_virtual_key_real(self):
        scancode_of = host_input.windows_scancode_of
        self.assertEqual(host_usage(65, 0x8, "a", scancode_of=scancode_of), usage("A"))
        self.assertEqual(host_usage(112, 0x8, "F1", scancode_of=scancode_of), usage("F1"))
        self.assertEqual(host_usage(27, 0x8, "Escape", scancode_of=scancode_of), usage("ESC"))
        self.assertEqual(host_usage(13, 0x8, "Return", scancode_of=scancode_of), usage("ENTER"))
        self.assertEqual(host_input.default_scancode_of(), scancode_of)

    @unittest.skipUnless(sys.platform == "win32", "GetAsyncKeyState solo existe en Windows")
    def test_modificadores_reales_es_un_conjunto_de_modificadores(self):
        pressed = host_input.windows_modifiers()
        self.assertTrue(all(0xE0 <= u <= 0xE7 for u in pressed))


class HostKeyboardTest(unittest.TestCase):
    def setUp(self):
        self.reports = []
        self.keyboard = HostKeyboard(self.reports.append)

    def test_pulsar_y_soltar_emiten_el_estado_completo(self):
        self.keyboard.press(usage("A"))
        self.keyboard.press(usage("B"))
        self.keyboard.release(usage("A"))
        self.assertEqual(self.reports, [frozenset({4}), frozenset({4, 5}), frozenset({5})])

    def test_el_autorepeat_no_es_una_pulsacion_nueva(self):
        for _ in range(30):
            self.keyboard.press(usage("A"))
        self.assertEqual(self.reports, [frozenset({4})])

    def test_soltar_una_tecla_no_pulsada_no_emite(self):
        self.keyboard.release(usage("A"))
        self.assertEqual(self.reports, [])

    def test_modificadores_leidos_del_sistema_sustituyen_a_los_anteriores(self):
        self.keyboard.press(usage("A"))
        self.keyboard.set_modifiers({usage("LSHIFT"), usage("RSHIFT")})
        self.keyboard.set_modifiers({usage("RSHIFT")})          # se suelta el izquierdo
        self.keyboard.set_modifiers(set())                      # y después el derecho
        self.assertEqual(self.reports[-1], frozenset({4}))
        self.assertEqual(self.reports[1], frozenset({4, 0xE1, 0xE5}))
        self.assertEqual(self.reports[2], frozenset({4, 0xE5}))

    def test_set_modifiers_sin_cambios_no_emite(self):
        self.keyboard.set_modifiers({usage("LCTRL")})
        self.keyboard.set_modifiers({usage("LCTRL")})
        self.assertEqual(len(self.reports), 1)

    def test_set_modifiers_ignora_lo_que_no_es_modificador(self):
        self.keyboard.set_modifiers({usage("A")})
        self.assertEqual(self.reports, [])

    def test_altgr_retira_el_control_falso(self):
        # Log real: Control_L y Alt_R a 1 ms.
        self.keyboard.press(usage("LCTRL"), time_ms=1000)
        self.keyboard.press(usage("RALT"), time_ms=1001)
        self.assertEqual(self.reports[-1], frozenset({0xE6}))

    def test_altgr_leido_del_sistema_no_deja_pasar_el_control_falso(self):
        # El SO sigue contando Control_L mientras dura AltGr: no debe volver.
        self.keyboard.set_modifiers({usage("LCTRL"), usage("RALT")})
        self.assertEqual(self.reports[-1], frozenset({0xE6}))
        self.keyboard.set_modifiers({usage("LCTRL"), usage("RALT")})
        self.assertEqual(len(self.reports), 1)
        self.keyboard.set_modifiers(set())
        self.assertEqual(self.reports[-1], frozenset())
        # Pasado AltGr, un Control izquierdo auténtico vuelve a contar.
        self.keyboard.set_modifiers({usage("LCTRL")})
        self.assertEqual(self.reports[-1], frozenset({0xE0}))

    def test_control_ya_pulsado_y_despues_alt_derecho_son_dos_teclas(self):
        self.keyboard.set_modifiers({usage("LCTRL")})
        self.keyboard.set_modifiers({usage("LCTRL"), usage("RALT")})
        self.assertEqual(self.reports[-1], frozenset({0xE0, 0xE6}))

    def test_ctrl_y_alt_derecho_pulsados_a_mano_se_respetan(self):
        self.keyboard.press(usage("LCTRL"), time_ms=1000)
        self.keyboard.press(usage("RALT"), time_ms=1500)
        self.assertEqual(self.reports[-1], frozenset({0xE0, 0xE6}))

    def test_perder_el_foco_suelta_todo(self):
        # La tecla Windows abre el menú Inicio y no entrega release.
        self.keyboard.press(usage("LGUI"))
        self.keyboard.press(usage("A"))
        self.keyboard.release_all()
        self.assertEqual(self.reports[-1], frozenset())
        self.keyboard.release_all()
        self.assertEqual(len(self.reports), 3)          # no repite el vacío


class HostMouseTest(unittest.TestCase):
    def test_los_deltas_son_diferencias_de_posicion(self):
        mouse = HostMouse()
        mouse.enter(100, 50)
        mouse.motion(110, 45)
        mouse.motion(115, 60)
        self.assertEqual(mouse.drain(0), (0, 15, 10))

    def test_sin_origen_la_primera_entrada_no_es_mover(self):
        # No hay referencia hasta que el puntero se ve por primera vez.
        mouse = HostMouse()
        mouse.enter(10, 10)
        self.assertIsNone(mouse.drain(0))
        mouse.motion(15, 10)                # desde ahí, ya sí
        self.assertEqual(mouse.drain(0), (0, 5, 0))

    def test_con_origen_la_primera_entrada_lleva_del_centro_al_puntero(self):
        mouse = HostMouse(origin=(320, 240))
        mouse.enter(400, 200)
        self.assertEqual(mouse.drain(0), (0, 80, -40))

    def test_volver_a_entrar_entrega_el_desplazamiento_neto(self):
        # Sale por la derecha y vuelve por la izquierda: un ratón real habría
        # informado de todo ese recorrido, y el programa lo necesita.
        mouse = HostMouse(origin=(0, 0))
        mouse.enter(500, 40)
        mouse.drain(0)
        mouse.motion(510, 40)
        mouse.leave(515, 40)                # último punto conocido, en el borde
        mouse.enter(5, 200)
        mouse.motion(8, 200)
        self.assertEqual(mouse.drain(0), (0, 8 - 500, 200 - 40))

    def test_las_posiciones_fuera_de_la_ventana_se_limitan_al_borde(self):
        # Salir deprisa: Tk da una coordenada muy fuera. Lo que no cabe en la
        # pantalla del programa no se debe entregar, o no se recupera.
        mouse = HostMouse(origin=(600, 400), bounds=(640, 480))
        mouse.leave(900, 700)
        self.assertEqual(mouse.drain(0), (0, 39, 79))          # hasta (639, 479)

    def test_reentrar_tras_salir_lejos_deja_el_pincel_en_el_puntero(self):
        # Simula al programa: recorta su pincel a la pantalla, como la demo.
        mouse = HostMouse(origin=(320, 240), bounds=(640, 480))
        brush = [320, 240]
        pointer_path = [("enter", 100, 100), ("motion", 600, 300), ("leave", 1500, -400),
                        ("enter", 5, 470), ("motion", 40, 420), ("leave", -90, 420),
                        ("enter", 300, 5), ("motion", 310, 9)]
        for action, x, y in pointer_path:
            getattr(mouse, action)(x, y)
            _, dx, dy = mouse.drain(0) or (0, 0, 0)
            brush[0] = max(0, min(639, brush[0] + dx))
            brush[1] = max(0, min(479, brush[1] + dy))
        self.assertEqual(brush, [310, 9])

    def test_los_movimientos_con_boton_fuera_tambien_se_limitan(self):
        mouse = HostMouse(origin=(320, 240), bounds=(640, 480))
        mouse.motion(-50, 240)                              # arrastre fuera, por la izquierda
        self.assertEqual(mouse.drain(0), (0, -320, 0))

    def test_salir_cuenta_hasta_el_borde(self):
        mouse = HostMouse(origin=(100, 100))
        mouse.leave(120, 100)
        self.assertEqual(mouse.drain(0), (0, 20, 0))

    def test_el_recorrido_fuera_no_se_inventa(self):
        # Entrar donde se salió no mueve nada.
        mouse = HostMouse(origin=(0, 0))
        mouse.enter(50, 50)
        mouse.drain(0)
        mouse.leave(60, 50)
        mouse.drain(0)
        mouse.enter(60, 50)
        self.assertIsNone(mouse.drain(0))

    def test_drain_funde_y_vacia(self):
        mouse = HostMouse()
        mouse.enter(0, 0)
        for x in range(1, 11):
            mouse.motion(x, 0)
        self.assertEqual(mouse.drain(0), (0, 10, 0))
        self.assertIsNone(mouse.drain(0))

    def test_botones_de_tk(self):
        mouse = HostMouse()
        mouse.button(1, True)
        mouse.button(3, True)
        mouse.button(2, True)
        self.assertEqual(mouse.buttons, 0b111)       # izq, der, central
        mouse.button(1, False)
        self.assertEqual(mouse.buttons, 0b110)

    def test_un_boton_solo_es_un_report(self):
        mouse = HostMouse()
        mouse.button(1, True)
        self.assertEqual(mouse.drain(0), (1, 0, 0))
        self.assertIsNone(mouse.drain(1))

    def test_botones_desconocidos_se_ignoran(self):
        mouse = HostMouse()
        mouse.button(4, True)
        self.assertEqual(mouse.buttons, 0)

    def test_perder_el_foco_suelta_los_botones(self):
        mouse = HostMouse()
        mouse.button(1, True)
        mouse.release_all()
        self.assertEqual(mouse.drain(1), (0, 0, 0))


class WithInputDeviceTest(unittest.TestCase):
    """Los reports llegan a `InputDevice` y producen los eventos de §25."""

    def test_shift_a_con_teclado_y_dispositivo(self):
        from tools.sim_devices import InputDevice
        device = InputDevice()
        device.connect_keyboard()
        keyboard = HostKeyboard(device.keyboard_report)
        keyboard.set_modifiers({usage("LSHIFT")})
        keyboard.press(usage("A"))
        keyboard.release(usage("A"))
        keyboard.set_modifiers(set())
        events = []
        while device.fifo:
            events.append(InputDevice.decode_event(device.read(InputDevice.EVENT_DATA)))
        self.assertEqual([e["type"] for e in events],
                         ["modifiers", "key", "key", "modifiers"])
        self.assertEqual(events[1], {"type": "key", "usage": 4, "down": True, "modifiers": 2})

    def test_raton_fundido_llega_como_un_evento(self):
        from tools.sim_devices import InputDevice
        device = InputDevice()
        device.connect_mouse()
        mouse = HostMouse()
        mouse.enter(0, 0)
        for x in range(1, 101):
            mouse.motion(x, x // 2)
        buttons, dx, dy = mouse.drain(device.mouse_buttons)
        device.mouse_report(buttons, dx, dy)
        self.assertEqual(len(device.fifo), 1)
        self.assertEqual(InputDevice.decode_event(device.fifo[0]),
                         {"type": "move", "dx": 100, "dy": 50})


if __name__ == "__main__":
    unittest.main()
