"""INPUT (teclado y ratón, `1.isa/mmio.md` §25) en los simuladores funcionales.

Cada regla de §25 tiene su test: el dispositivo es el oráculo con el que se
contrastará el RTL, así que tiene que decir exactamente lo que dice el contrato.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "1.isa"))
sys.path.insert(0, str(ROOT / "2.cpu-sim-func"))
sys.path.insert(0, str(ROOT / "11.gpu-sim-func"))
from mini_asm import assemble_bytes
from tools.sim_devices import InputDevice
import minicpu_sim
import minigpu_sim

# Usage IDs HID (Usage Page 0x07) de §25.1.
KEY_A, KEY_B, KEY_SPACE = 0x04, 0x05, 0x2C
LCTRL, LSHIFT, RGUI = 0xE0, 0xE1, 0xE7

LEFT, RIGHT, MIDDLE = 0, 1, 2


def present_device(keyboard=True, mouse=True):
    device = InputDevice()
    if keyboard:
        device.connect_keyboard()
    if mouse:
        device.connect_mouse()
    return device


def drain(device):
    """Lee la FIFO entera por MMIO, como lo haría un programa, y decodifica."""
    events = []
    while device.read(InputDevice.STATUS) & InputDevice.STATUS_COUNT_MASK:
        events.append(InputDevice.decode_event(device.read(InputDevice.EVENT_DATA)))
    return events


def key(usage, down, modifiers=0):
    return {"type": "key", "usage": usage, "down": down, "modifiers": modifiers}


def modifiers(bitmap):
    return {"type": "modifiers", "modifiers": bitmap}


def button(number, down):
    return {"type": "button", "button": number, "down": down}


def move(dx, dy):
    return {"type": "move", "dx": dx, "dy": dy}


class RegistersTest(unittest.TestCase):
    def test_reset_deja_todo_a_cero(self):
        device = InputDevice()
        self.assertEqual(device.read(InputDevice.STATUS), 0)
        self.assertEqual(device.read(InputDevice.EVENT_DATA), 0)
        self.assertEqual(device.read(InputDevice.MOUSE_BUTTONS), 0)
        for word in range(8):
            self.assertEqual(device.read(InputDevice.KEY_STATE0 + 4 * word), 0)

    def test_registros_reservados_dan_error(self):
        device = InputDevice()
        for offset in (0x0C, 0x14 + 0x1C + 4, 0x34, 0x100, 0xFFFC):
            with self.subTest(offset=offset), self.assertRaises(RuntimeError):
                device.read(offset)
            with self.subTest(offset=offset, writing=True), self.assertRaises(RuntimeError):
                device.write(offset, 0)

    def test_event_ctrl_es_solo_escritura(self):
        with self.assertRaises(RuntimeError):
            InputDevice().read(InputDevice.EVENT_CTRL)

    def test_los_registros_de_lectura_no_se_pueden_escribir(self):
        device = InputDevice()
        for offset in (InputDevice.EVENT_DATA, InputDevice.STATUS,
                       InputDevice.KEY_STATE0, InputDevice.KEY_STATE0 + 28,
                       InputDevice.MOUSE_BUTTONS):
            with self.subTest(offset=offset), self.assertRaises(RuntimeError):
                device.write(offset, 0)

    def test_event_ctrl_con_bits_reservados_no_ejecuta_nada(self):
        device = present_device()
        device.key_down(KEY_A)
        device.overflow = True
        for value in (0b100, 0b111, 0x8000_0000):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                device.write(InputDevice.EVENT_CTRL, value)
        self.assertEqual(device.read(InputDevice.STATUS) & 0xFFFF, 1)
        self.assertTrue(device.overflow)

    def test_escribir_cero_en_event_ctrl_no_hace_nada(self):
        device = present_device()
        device.key_down(KEY_A)
        device.write(InputDevice.EVENT_CTRL, 0)
        self.assertEqual(device.read(InputDevice.STATUS) & 0xFFFF, 1)


class KeyboardStateTest(unittest.TestCase):
    def test_key_state_es_un_bitmap_de_256_bits(self):
        device = present_device()
        device.keyboard_report({KEY_A, KEY_SPACE, 0x52, LSHIFT, RGUI, 0xFF})
        self.assertEqual(device.read(InputDevice.KEY_STATE0), 1 << KEY_A)
        # 0x2C: registro 1, bit 12.
        self.assertEqual(device.read(InputDevice.KEY_STATE0 + 4), 1 << (KEY_SPACE & 31))
        # 0x52: registro 2, bit 18.
        self.assertEqual(device.read(InputDevice.KEY_STATE0 + 8), 1 << (0x52 & 31))
        # Los modificadores 0xE0..0xE7 viven en KEY_STATE7, y 0xFF también.
        self.assertEqual(device.read(InputDevice.KEY_STATE0 + 28),
                         (1 << 1) | (1 << 7) | (1 << 31))

    def test_soltar_limpia_el_bit(self):
        device = present_device()
        device.key_down(KEY_A)
        device.key_up(KEY_A)
        self.assertEqual(device.read(InputDevice.KEY_STATE0), 0)

    def test_usage_id_invalido(self):
        device = present_device()
        for usage in (0, 256, -1):
            with self.subTest(usage=usage), self.assertRaises(ValueError):
                device.keyboard_report({usage})


class KeyEventsTest(unittest.TestCase):
    def test_pulsar_y_soltar(self):
        device = present_device()
        device.key_down(KEY_A)
        device.key_up(KEY_A)
        self.assertEqual(drain(device), [key(KEY_A, True), key(KEY_A, False)])

    def test_codificacion_de_la_palabra(self):
        device = present_device()
        device.key_down(KEY_A)
        # KEY=0x04, DOWN=1, MODIFIERS=0, TYPE_KEY=0x00.
        self.assertEqual(device.read(InputDevice.EVENT_DATA), 0x0000_0104)

    def test_modificador_genera_un_evento_key_cero(self):
        device = present_device()
        device.key_down(LSHIFT)
        self.assertEqual(drain(device), [modifiers(0x02)])
        # La codificación: KEY=0, DOWN=0, MODIFIERS=0x02.
        device.key_up(LSHIFT)
        self.assertEqual(device.read(InputDevice.EVENT_DATA), 0x0000_0000)

    def test_varios_modificadores_en_un_report_son_un_solo_evento(self):
        device = present_device()
        device.keyboard_report({LCTRL, LSHIFT, RGUI})
        self.assertEqual(drain(device), [modifiers(0x01 | 0x02 | 0x80)])

    def test_las_teclas_normales_no_se_reemiten_al_cambiar_un_modificador(self):
        device = present_device()
        device.key_down(KEY_A)
        drain(device)
        device.key_down(LSHIFT)
        self.assertEqual(drain(device), [modifiers(0x02)])

    def test_orden_del_report_up_modificadores_down(self):
        device = present_device()
        device.keyboard_report({KEY_A, LSHIFT})
        drain(device)
        # A y Shift sueltos; B y Ctrl pulsadas, todo en el mismo report.
        device.keyboard_report({KEY_B, LCTRL})
        self.assertEqual(drain(device), [
            key(KEY_A, False, 0x01),        # UP, con los modificadores NUEVOS
            modifiers(0x01),
            key(KEY_B, True, 0x01),
        ])

    def test_up_y_down_ascendentes_por_usage_id(self):
        device = present_device()
        device.keyboard_report({0x1E, 0x04, 0x2C})
        drain(device)
        device.keyboard_report({0x05, 0x1F})
        self.assertEqual([e["usage"] for e in drain(device)],
                         [0x04, 0x1E, 0x2C, 0x05, 0x1F])
        # 0x04, 0x1E y 0x2C son UP (ascendentes) y 0x05, 0x1F son DOWN.

    def test_el_down_lleva_los_modificadores_del_nuevo_report(self):
        device = present_device()
        device.keyboard_report({LSHIFT, KEY_A})
        self.assertEqual(drain(device), [modifiers(0x02), key(KEY_A, True, 0x02)])

    def test_report_sin_cambios_no_genera_eventos(self):
        device = present_device()
        device.keyboard_report({KEY_A, LCTRL})
        drain(device)
        device.keyboard_report({KEY_A, LCTRL})
        self.assertEqual(drain(device), [])

    def test_un_report_exige_teclado_presente(self):
        device = present_device(keyboard=False)
        with self.assertRaises(ValueError):
            device.key_down(KEY_A)
        self.assertEqual(device.read(InputDevice.KEY_STATE0), 0)


class MouseTest(unittest.TestCase):
    def test_botones_up_y_down_ascendentes_y_despues_el_movimiento(self):
        device = present_device()
        device.mouse_report(1 << RIGHT | 1 << 31)
        drain(device)
        device.mouse_report(1 << LEFT | 1 << MIDDLE, dx=5, dy=-3)
        self.assertEqual(drain(device), [
            button(RIGHT, False), button(31, False),
            button(LEFT, True), button(MIDDLE, True),
            move(5, -3),
        ])

    def test_mouse_buttons_es_el_estado_actual(self):
        device = present_device()
        device.mouse_button(LEFT, True)
        device.mouse_button(31, True)
        self.assertEqual(device.read(InputDevice.MOUSE_BUTTONS), 1 | (1 << 31))
        device.mouse_button(LEFT, False)
        self.assertEqual(device.read(InputDevice.MOUSE_BUTTONS), 1 << 31)

    def test_codificacion_de_boton_y_movimiento(self):
        device = present_device()
        device.mouse_button(2, True)
        self.assertEqual(device.read(InputDevice.EVENT_DATA), 0x0100_0000 | 0x100 | 2)
        device.mouse_move(-1, 1)
        # DX=-1 → 0xFFF en 11:0; DY=+1 → 1 en 23:12; TYPE_MOUSE_MOVE=0x02.
        self.assertEqual(device.read(InputDevice.EVENT_DATA), 0x0200_0000 | (1 << 12) | 0xFFF)

    def test_movimiento_cero_no_genera_evento(self):
        device = present_device()
        device.mouse_move(0, 0)
        self.assertEqual(drain(device), [])

    def test_un_eje_a_cero_si_genera_evento(self):
        device = present_device()
        device.mouse_move(0, 7)
        self.assertEqual(drain(device), [move(0, 7)])

    def test_movimiento_grande_se_parte_conservando_la_suma(self):
        device = present_device()
        device.mouse_move(5000, -3000)
        events = drain(device)
        self.assertGreater(len(events), 1)
        for event in events:
            self.assertTrue(-2048 <= event["dx"] <= 2047)
            self.assertTrue(-2048 <= event["dy"] <= 2047)
        self.assertEqual(sum(e["dx"] for e in events), 5000)
        self.assertEqual(sum(e["dy"] for e in events), -3000)

    def test_limites_del_rango_signed12(self):
        device = present_device()
        device.mouse_move(-2048, 2047)
        self.assertEqual(drain(device), [move(-2048, 2047)])
        device.mouse_move(2048, 0)
        self.assertEqual(drain(device), [move(2047, 0), move(1, 0)])

    def test_un_report_exige_raton_presente(self):
        device = present_device(mouse=False)
        with self.assertRaises(ValueError):
            device.mouse_move(1, 1)

    def test_boton_fuera_de_rango(self):
        with self.assertRaises(ValueError):
            present_device().mouse_button(32, True)

    def test_no_hay_posicion_ni_acumuladores(self):
        # Dos movimientos son dos eventos: INPUT no los suma ni guarda X/Y.
        device = present_device()
        device.mouse_move(3, 0)
        device.mouse_move(4, 0)
        self.assertEqual(drain(device), [move(3, 0), move(4, 0)])


class FifoTest(unittest.TestCase):
    def fill(self, device, count):
        for index in range(count):
            device.mouse_move(index + 1, 0)

    def test_leer_event_data_consume(self):
        device = present_device()
        self.fill(device, 2)
        self.assertEqual(device.read(InputDevice.STATUS) & 0xFFFF, 2)
        device.read(InputDevice.EVENT_DATA)
        self.assertEqual(device.read(InputDevice.STATUS) & 0xFFFF, 1)

    def test_cola_vacia_devuelve_cero_y_no_tiene_efecto(self):
        device = present_device()
        before = device.read(InputDevice.STATUS)
        self.assertEqual(device.read(InputDevice.EVENT_DATA), 0)
        self.assertEqual(device.read(InputDevice.STATUS), before)

    def test_drop_new_con_la_cola_llena(self):
        device = present_device()
        self.fill(device, InputDevice.FIFO_DEPTH + 1)
        status = device.read(InputDevice.STATUS)
        self.assertEqual(status & 0xFFFF, InputDevice.FIFO_DEPTH)
        self.assertTrue(status & InputDevice.STATUS_OVERFLOW)
        # Se conserva lo más antiguo y se pierde lo nuevo.
        events = drain(device)
        self.assertEqual([e["dx"] for e in events], list(range(1, 17)))

    def test_state_se_actualiza_aunque_se_pierdan_eventos(self):
        device = present_device()
        self.fill(device, InputDevice.FIFO_DEPTH)
        device.key_down(KEY_A)
        device.mouse_button(LEFT, True)
        self.assertTrue(device.read(InputDevice.STATUS) & InputDevice.STATUS_OVERFLOW)
        self.assertEqual(device.read(InputDevice.KEY_STATE0), 1 << KEY_A)
        self.assertEqual(device.read(InputDevice.MOUSE_BUTTONS), 1)

    def test_un_report_entra_hasta_donde_quepa(self):
        device = present_device()
        self.fill(device, InputDevice.FIFO_DEPTH - 1)
        device.keyboard_report({KEY_A, KEY_B, 0x06})        # tres DOWN, cabe uno
        events = drain(device)
        self.assertEqual(len(events), InputDevice.FIFO_DEPTH)
        self.assertEqual(events[-1], key(KEY_A, True))
        self.assertTrue(device.overflow)

    def test_overflow_es_pegajoso_y_no_bloquea(self):
        device = present_device()
        self.fill(device, InputDevice.FIFO_DEPTH + 1)
        drain(device)
        self.assertTrue(device.read(InputDevice.STATUS) & InputDevice.STATUS_OVERFLOW)
        device.key_down(KEY_A)                  # vuelve a haber sitio
        self.assertEqual(drain(device), [key(KEY_A, True)])
        self.assertTrue(device.read(InputDevice.STATUS) & InputDevice.STATUS_OVERFLOW)

    def test_pop_con_la_cola_llena_deja_sitio_sin_overflow(self):
        device = present_device()
        self.fill(device, InputDevice.FIFO_DEPTH)
        device.read(InputDevice.EVENT_DATA)
        device.mouse_move(99, 0)
        self.assertFalse(device.read(InputDevice.STATUS) & InputDevice.STATUS_OVERFLOW)
        self.assertEqual(device.read(InputDevice.STATUS) & 0xFFFF, InputDevice.FIFO_DEPTH)


class EventCtrlTest(unittest.TestCase):
    def overflowed(self):
        device = present_device()
        for index in range(InputDevice.FIFO_DEPTH + 1):
            device.mouse_move(index + 1, 0)
        device.key_down(KEY_A)
        return device

    def test_flush_vacia_la_cola_y_no_toca_overflow_ni_state(self):
        device = self.overflowed()
        device.write(InputDevice.EVENT_CTRL, InputDevice.CTRL_FLUSH)
        status = device.read(InputDevice.STATUS)
        self.assertEqual(status & 0xFFFF, 0)
        self.assertTrue(status & InputDevice.STATUS_OVERFLOW)
        self.assertTrue(status & InputDevice.STATUS_KEYBOARD_PRESENT)
        self.assertTrue(status & InputDevice.STATUS_MOUSE_PRESENT)
        self.assertEqual(device.read(InputDevice.KEY_STATE0), 1 << KEY_A)

    def test_clear_overflow_no_toca_la_cola(self):
        device = self.overflowed()
        device.write(InputDevice.EVENT_CTRL, InputDevice.CTRL_CLEAR_OVERFLOW)
        status = device.read(InputDevice.STATUS)
        self.assertEqual(status & 0xFFFF, InputDevice.FIFO_DEPTH)
        self.assertFalse(status & InputDevice.STATUS_OVERFLOW)

    def test_los_dos_bits_a_la_vez(self):
        device = self.overflowed()
        device.write(InputDevice.EVENT_CTRL,
                     InputDevice.CTRL_FLUSH | InputDevice.CTRL_CLEAR_OVERFLOW)
        self.assertEqual(device.read(InputDevice.STATUS) & 0x1FFFF, 0)


class ConnectionTest(unittest.TestCase):
    def test_reset_deja_presencia_a_cero(self):
        device = present_device()
        device.key_down(KEY_A)
        device.reset()
        self.assertEqual(device.read(InputDevice.STATUS), 0)
        self.assertEqual(device.read(InputDevice.KEY_STATE0), 0)

    def test_conexion_inicial_con_teclas_pulsadas_genera_eventos(self):
        device = InputDevice()
        device.connect_keyboard({KEY_B, KEY_A, LCTRL})
        device.connect_mouse(1 << RIGHT | 1 << LEFT)
        self.assertEqual(drain(device), [
            modifiers(0x01),
            key(KEY_A, True, 0x01),
            key(KEY_B, True, 0x01),
            button(LEFT, True), button(RIGHT, True),
        ])
        status = device.read(InputDevice.STATUS)
        self.assertTrue(status & InputDevice.STATUS_KEYBOARD_PRESENT)
        self.assertTrue(status & InputDevice.STATUS_MOUSE_PRESENT)

    def test_desconexion_del_teclado_libera_y_deja_state_a_cero(self):
        device = present_device()
        device.keyboard_report({KEY_B, KEY_A, LSHIFT})
        drain(device)
        device.disconnect_keyboard()
        self.assertEqual(drain(device), [
            key(KEY_A, False), key(KEY_B, False), modifiers(0)])
        status = device.read(InputDevice.STATUS)
        self.assertFalse(status & InputDevice.STATUS_KEYBOARD_PRESENT)
        self.assertTrue(status & InputDevice.STATUS_MOUSE_PRESENT)
        for word in range(8):
            self.assertEqual(device.read(InputDevice.KEY_STATE0 + 4 * word), 0)

    def test_desconexion_sin_modificadores_no_genera_evento_de_modificadores(self):
        device = present_device()
        device.key_down(KEY_A)
        drain(device)
        device.disconnect_keyboard()
        self.assertEqual(drain(device), [key(KEY_A, False)])

    def test_desconexion_del_raton_libera_botones(self):
        device = present_device()
        device.mouse_report(1 << MIDDLE | 1 << LEFT)
        drain(device)
        device.disconnect_mouse()
        self.assertEqual(drain(device), [button(LEFT, False), button(MIDDLE, False)])
        self.assertEqual(device.read(InputDevice.MOUSE_BUTTONS), 0)
        self.assertFalse(device.read(InputDevice.STATUS) & InputDevice.STATUS_MOUSE_PRESENT)

    def test_los_eventos_de_desconexion_siguen_la_politica_de_overflow(self):
        device = present_device()
        device.keyboard_report({KEY_A, KEY_B})
        for index in range(InputDevice.FIFO_DEPTH):
            device.mouse_move(index + 1, 0)
        device.disconnect_keyboard()
        status = device.read(InputDevice.STATUS)
        self.assertTrue(status & InputDevice.STATUS_OVERFLOW)
        self.assertFalse(status & InputDevice.STATUS_KEYBOARD_PRESENT)
        self.assertEqual(device.read(InputDevice.KEY_STATE0), 0)

    def test_invariante_sin_presencia_state_es_cero(self):
        device = InputDevice()
        self.assertEqual(device.read(InputDevice.KEY_STATE0), 0)
        self.assertEqual(device.read(InputDevice.MOUSE_BUTTONS), 0)


class SimulatorWiringTest(unittest.TestCase):
    """Un programa real ve INPUT en los simuladores funcionales."""

    PROGRAM = """MOVHI R1, 0x8060
LOAD R2, R1, 4
LOAD R3, R1, 0
LOAD R4, R1, 0x10
MOVI R5, 256
STORE R2, R5, 0
STORE R3, R5, 4
STORE R4, R5, 8
HALT"""

    def test_cpu_lee_status_evento_y_estado(self):
        device = present_device()
        device.key_down(KEY_A)
        cpu = minicpu_sim.CPU(input_device=device)
        cpu.load_program(assemble_bytes(self.PROGRAM))
        cpu.run(1000)
        self.assertFalse(cpu.error)
        status, event, state = (int.from_bytes(cpu.memory[256 + 4 * i:260 + 4 * i], "little")
                                for i in range(3))
        self.assertEqual(status & 0xFFFF, 1)
        self.assertEqual(status & (InputDevice.STATUS_KEYBOARD_PRESENT
                                   | InputDevice.STATUS_MOUSE_PRESENT),
                         InputDevice.STATUS_KEYBOARD_PRESENT | InputDevice.STATUS_MOUSE_PRESENT)
        self.assertEqual(event, 0x0000_0104)
        self.assertEqual(state, 1 << KEY_A)
        self.assertEqual(device.read(InputDevice.STATUS) & 0xFFFF, 0)    # el LOAD consumió

    def test_cpu_sin_dispositivo_da_error(self):
        cpu = minicpu_sim.CPU()
        cpu.load_program(assemble_bytes(self.PROGRAM))
        cpu.run(1000)
        self.assertTrue(cpu.error)

    def test_cpu_acceso_a_registro_reservado_da_error(self):
        cpu = minicpu_sim.CPU(input_device=present_device())
        cpu.load_program(assemble_bytes("MOVHI R1, 0x8060\nLOAD R2, R1, 0x34\nHALT"))
        cpu.run(1000)
        self.assertTrue(cpu.error)

    def test_cpu_escribir_event_ctrl_vacia_la_cola(self):
        device = present_device()
        device.key_down(KEY_A)
        cpu = minicpu_sim.CPU(input_device=device)
        cpu.load_program(assemble_bytes(
            "MOVHI R1, 0x8060\nMOVI R2, 1\nSTORE R2, R1, 8\nHALT"))
        cpu.run(1000)
        self.assertFalse(cpu.error)
        self.assertEqual(device.read(InputDevice.STATUS) & 0xFFFF, 0)

    def test_cpu_acceso_por_bytes_da_error(self):
        cpu = minicpu_sim.CPU(input_device=present_device())
        cpu.load_program(assemble_bytes("MOVHI R1, 0x8060\nLOADB R2, R1, 4\nHALT"))
        cpu.run(1000)
        self.assertTrue(cpu.error)

    def test_gpu_funcional_resuelve_la_direccion(self):
        device = present_device()
        system = minigpu_sim.System(input_device=device)
        self.assertIs(system.device_for(InputDevice.BASE), device)
        self.assertIsNone(minigpu_sim.System().device_for(InputDevice.BASE))


if __name__ == "__main__":
    unittest.main()
