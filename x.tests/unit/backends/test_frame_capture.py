"""La parada por intercambios que comparten los backends FPGA de CPU y GPU."""

from __future__ import annotations

import unittest

from backends import frame_capture
from backends.frame_capture import ParadaImprecisa, Registros

REGISTROS = Registros(status=0x10, swap_count=0x18, fb_front=0x04, fb_back=0x08)
FRENTE, FONDO = 0x1000, 0x2000


class _Cliente:
    def __init__(self):
        self.leido = []

    def read_memory(self, direccion, tamano):
        self.leido.append((direccion, tamano))
        return b"frame"


def _lector(valores: dict):
    return lambda direccion: valores[direccion]


class HayQuePararTest(unittest.TestCase):
    def test_para_al_llegar_al_objetivo_contra_la_base(self):
        # El contador es del dispositivo y sobrevive a reset_cpu: ya vale 100
        # antes de arrancar, y parar en `100 >= 3` dejaria nueve frames en
        # blanco.
        leer = _lector({REGISTROS.swap_count: 102})
        self.assertFalse(frame_capture.hay_que_parar(leer, REGISTROS, 100, 3))
        leer = _lector({REGISTROS.swap_count: 103})
        self.assertTrue(frame_capture.hay_que_parar(leer, REGISTROS, 100, 3))

    def test_el_contador_puede_dar_la_vuelta(self):
        leer = _lector({REGISTROS.swap_count: 1})
        self.assertEqual(frame_capture.swaps_desde(leer, REGISTROS, 0xFFFFFFFF), 2)


class FrameTrasSwapTest(unittest.TestCase):
    def _frame(self, swaps, objetivo):
        cliente = _Cliente()
        leer = _lector({REGISTROS.fb_front: FRENTE, REGISTROS.fb_back: FONDO})
        frame_capture.frame_tras_swap(cliente, leer, REGISTROS, swaps, objetivo, 64)
        return cliente.leido[0][0]

    def test_exacto_lee_el_frontal(self):
        self.assertEqual(self._frame(3, 3), FRENTE)

    def test_uno_de_mas_lee_el_trasero(self):
        self.assertEqual(self._frame(4, 3), FONDO)

    def test_dos_de_mas_ya_no_tiene_arreglo(self):
        # Antes se corregia por paridad sin mirar cuanto: con dos de mas la
        # paridad vuelve al frontal, que es otro frame, y el caso fallaba en un
        # pixel como si fuera ruido.
        with self.assertRaises(ParadaImprecisa):
            self._frame(5, 3)

    def test_menos_de_los_pedidos_tampoco(self):
        with self.assertRaises(ParadaImprecisa):
            self._frame(2, 3)

    def test_sin_objetivo_no_se_corrige_nada(self):
        self.assertEqual(self._frame(17, None), FRENTE)


class ReintentosTest(unittest.TestCase):
    def test_repite_hasta_que_sale_bien(self):
        intentos = []

        def ejecutar():
            intentos.append(1)
            if len(intentos) < 3:
                raise ParadaImprecisa("de mas")
            return {"ok": True}

        self.assertEqual(frame_capture.con_reintentos(ejecutar), {"ok": True})
        self.assertEqual(len(intentos), 3)

    def test_el_ultimo_intento_propaga(self):
        def ejecutar():
            raise ParadaImprecisa("de mas")

        with self.assertRaises(ParadaImprecisa):
            frame_capture.con_reintentos(ejecutar, intentos=2)

    def test_otros_errores_no_se_reintentan(self):
        intentos = []

        def ejecutar():
            intentos.append(1)
            raise TimeoutError("colgado")

        with self.assertRaises(TimeoutError):
            frame_capture.con_reintentos(ejecutar)
        self.assertEqual(len(intentos), 1)


if __name__ == "__main__":
    unittest.main()
