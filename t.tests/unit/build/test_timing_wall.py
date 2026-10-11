"""`tools/timing_wall.py`: el muro de caminos casi criticos de un build.

Se prueba con informes de nextpnr fabricados a mano, que llevan solo lo que la
herramienta lee: `fmax` y `detailed_net_timings`. Los numeros son los de un
reloj de 80 MHz (periodo 12,5 ns), donde el 80 % son 10,0 ns y el 90 % 11,25.
"""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import timing_wall as tw


def net(driver, cell, arrival, event='posedge $glbnet$sdram_clk$TRELLIS_IO_OUT'):
    return {'driver': driver, 'net': driver, 'event': event,
            'endpoints': [{'cell': cell, 'delay': [arrival - 0.1, arrival], 'event': event, 'port': 'M'}]}


def informe(achieved=87.0, constraint=80.0, nets=None, other_clock=None):
    fmax = {'$glbnet$sdram_clk$TRELLIS_IO_OUT': {'constraint': constraint, 'achieved': achieved}}
    if other_clock:
        fmax['$glbnet$clk_pix'] = other_clock
    return {'fmax': fmax, 'detailed_net_timings': nets if nets is not None else [
        net('a_i.x', 'wide_i.buffer_TRELLIS_FF_Q_1', 11.3),
        net('a_i.x', 'wide_i.buffer_TRELLIS_FF_Q_2', 11.2),
        net('a_i.x', 'wide_i.buffer_TRELLIS_FF_Q_3', 10.4),
        net('a_i.x', 'small_i.state_TRELLIS_FF_Q', 6.0),
        net('a_i.x', 'pin$tr_io', 12.4),                                   # pin: no cuenta
        net('a_i.x', 'video_i.px_TRELLIS_FF_Q', 11.9, 'posedge $glbnet$clk_pix'),   # otro reloj
    ]}


def escribir(carpeta, nombre, pnr):
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / nombre
    ruta.write_text(json.dumps(pnr))
    return ruta


class AnalisisTest(unittest.TestCase):
    def test_agrupa_por_familia_y_cuenta_cerca_del_periodo(self):
        a = tw.analyze(informe())
        self.assertAlmostEqual(a['period'], 12.5)
        f = a['families']
        self.assertEqual(set(f), {'wide_i.buffer', 'small_i.state'})     # sin pines ni otro reloj
        self.assertEqual(f['wide_i.buffer']['endpoints'], 3)
        self.assertEqual(f['wide_i.buffer']['near'], 3)                   # 11,3 / 11,2 / 10,4 >= 10,0
        self.assertEqual(f['small_i.state']['near'], 0)
        self.assertEqual((a['near'], a['endpoints']), (3, 4))

    def test_el_umbral_del_90_por_ciento_son_11_25_ns(self):
        f = tw.analyze(informe())['families']['wide_i.buffer']
        # 11,3 pasa de 11,25; 11,2 y 10,4 no.
        self.assertEqual(f['hard'], 1)

    def test_sin_detalle_por_red_dice_que_hace_falta(self):
        with self.assertRaises(SystemExit) as error:
            tw.analyze({'fmax': {'clk': {'constraint': 80, 'achieved': 90}}})
        self.assertIn('detalle por red', str(error.exception))

    def test_el_reloj_por_defecto_es_el_de_menos_margen(self):
        pnr = informe(other_clock={'constraint': 25.0, 'achieved': 26.0})   # 4 % de margen
        self.assertEqual(tw.pick_clock(pnr)[0], '$glbnet$clk_pix')
        self.assertEqual(tw.pick_clock(pnr, 'sdram')[0], '$glbnet$sdram_clk$TRELLIS_IO_OUT')
        with self.assertRaises(SystemExit):
            tw.pick_clock(pnr, 'glbnet')                                    # ambiguo

    def test_informe_ordenado_por_llegada_y_con_modulos(self):
        texto = '\n'.join(tw.report_lines(tw.analyze(informe()), top=5, source='x', color=False))
        self.assertIn('exigido 80.0 MHz (periodo 12.50 ns)', texto)
        self.assertLess(texto.index('wide_i.buffer'), texto.index('small_i.state'))
        self.assertIn('HOLGURA', texto)
        self.assertNotIn('\033', texto)
        self.assertRegex(texto, r'wide_i\s+11\.30\s+3\s+1')                 # resumen por modulo

    def test_con_color_los_que_pasan_del_90_van_en_amarillo(self):
        texto = '\n'.join(tw.report_lines(tw.analyze(informe()), top=5, color=True))
        self.assertIn('\033[33m11.30\033[0m', texto)

    def test_cruce_atribuye_al_modulo_que_maneja_la_ultima_red(self):
        a = tw.analyze(informe(nets=[net('serial_i.rx_LUT4_Z', 'mmio_decoder_i.read_data_TRELLIS_FF_Q_7', 11.2),
                                     net('serial_i.rx_LUT4_Z', 'mmio_decoder_i.read_data_TRELLIS_FF_Q_2', 10.5),
                                     net('cpu_i.pc_LUT4_Z', 'cpu_i.pc_TRELLIS_FF_Q_1', 6.0)]))
        self.assertEqual(a['hops'][('serial_i', 'mmio_decoder_i')]['near'], 2)
        self.assertEqual(a['hops'][('cpu_i', 'cpu_i')]['near'], 0)
        texto = '\n'.join(tw.cross_lines(a))
        self.assertRegex(texto, r'serial_i\s+mmio_decoder_i\s+11\.20\s+2\s+0')
        self.assertNotIn('cpu_i', texto.split('\n', 1)[1])                  # sin destinos cerca, no sale

    def test_path_enseña_el_camino_critico_con_fuente_distancia_y_porcentaje_de_ruteo(self):
        def paso(tipo, retardo, red='', fuente=None, inicio=(10, 10), fin=(10, 10)):
            p = {'type': tipo, 'delay': retardo, 'from': {'cell': 'c', 'loc': list(inicio), 'port': 'Q'},
                 'to': {'cell': 'c', 'loc': list(fin), 'port': 'D'}}
            if red:
                p['net'] = red
            if fuente:
                p['sources'] = [fuente]
            return p
        pnr = informe()
        pnr['fmax'] = {'$glbnet$clk': {'constraint': 80.0, 'achieved': 70.0},
                       '$glbnet$clk_pix': {'constraint': 25.0, 'achieved': 60.0}}
        pnr['critical_paths'] = [
            {'from': 'posedge $glbnet$clk_pix', 'to': 'posedge $glbnet$clk_pix',
             'path': [paso('routing', 9.0, 'pix')]},
            {'from': 'posedge $glbnet$clk', 'to': 'posedge $glbnet$clk', 'path': [
                paso('clk-to-q', 0.5),
                paso('routing', 1.0, 'cpu_imem_address[3]', 'instruction_buffer.v:111.23-111.26', (10, 10), (13, 12)),
                paso('logic', 0.25),
                paso('routing', 2.25, '$abc$lut', 'C:\\x\\share/yosys/lattice/cells_map_trellis.v:108.23-108.24',
                     (13, 12), (40, 12))]}]
        camino = tw.critical_path(pnr)
        self.assertEqual(camino['clock'], '$glbnet$clk')                 # no el pix, que lo contiene
        self.assertAlmostEqual(camino['total'], 4.0)
        texto = '\n'.join(tw.path_lines(camino))
        self.assertIn('instruction_buffer.v:111', texto)
        self.assertNotIn('cells_map_trellis', texto)                     # la biblioteca no es nuestro RTL
        self.assertRegex(texto, r'routing\s+1\.00\s+1\.50\s+5\s+cpu_imem_address')   # 3 + 2 de distancia
        self.assertRegex(texto, r'routing\s+2\.25\s+4\.00\s+27')
        self.assertIn('0.25 de logica y 3.25 de ruteo (81 % ruteo', texto)

    def test_path_sin_camino_propio_del_reloj_lo_dice(self):
        with self.assertRaises(SystemExit) as error:
            tw.critical_path(dict(informe(), critical_paths=[]))
        self.assertIn('camino critico', str(error.exception))

    def test_comparar_enseña_la_bajada_y_el_total_de_destinos(self):
        malo = tw.analyze(informe(78.0, nets=[net('d', 'wide_i.buffer_TRELLIS_FF_Q_1', 12.4),
                                              net('d', 'wide_i.buffer_TRELLIS_FF_Q_2', 11.9)]))
        bueno = tw.analyze(informe(88.0, nets=[net('d', 'wide_i.buffer_TRELLIS_FF_Q_1', 11.0),
                                               net('d', 'other_i.q_TRELLIS_FF_Q', 9.0)]))
        texto = '\n'.join(tw.compare_lines(malo, bueno, top=5, color=False))
        self.assertIn('78.00 MHz -> B 88.00 MHz', texto)
        self.assertIn('Destinos >= 80 % del periodo: 2 -> 1', texto)
        self.assertRegex(texto, r'wide_i\.buffer\s+12\.40\s+11\.00\s+-1\.40')
        self.assertRegex(texto, r'other_i\.q\s+-\s+9\.00')                 # solo existe en B


class RutasTest(unittest.TestCase):
    def test_un_barrido_se_resuelve_a_su_mejor_semilla(self):
        with tempfile.TemporaryDirectory() as temp:
            barrido = Path(temp) / 'sweep-1'
            barrido.mkdir()
            (barrido / 'results.json').write_text(json.dumps([
                {'seed': 1, 'clocks': {'c': {'achieved': 79.0, 'constraint': 80.0}}, 'passes': False},
                {'seed': 2, 'clocks': {'c': {'achieved': 88.0, 'constraint': 80.0}}, 'passes': True},
            ]))
            escribir(barrido / 'seed-2', 'hardware.pnr', informe())
            self.assertEqual(tw.pnr_from_path(barrido), barrido / 'seed-2' / 'hardware.pnr')
            self.assertEqual(tw.pnr_from_path(barrido / 'seed-2'), barrido / 'seed-2' / 'hardware.pnr')
            with self.assertRaises(SystemExit):
                tw.pnr_from_path(Path(temp) / 'no-existe')

    def test_resolve_source_prefiere_el_ultimo_build_y_busca_barridos_por_trozo(self):
        with tempfile.TemporaryDirectory() as temp:
            proto = Path(temp)
            escribir(proto / 'reports' / '20260101-000000-build', 'hardware.pnr', informe())
            escribir(proto / 'reports' / '20260102-000000-build', 'hardware.pnr', informe())
            self.assertIn('20260102', str(tw.resolve_source(proto)[0]))
            escribir(proto / 'reports' / '20260102-000000-build' / 'sweep-20260102-101010-1' / 'seed-3',
                     'hardware.pnr', informe())
            ruta, nota = tw.resolve_source(proto, '101010', 3)
            self.assertTrue(str(ruta).endswith(str(Path('seed-3') / 'hardware.pnr')))
            self.assertIn('sweep-20260102-101010', nota)
            with self.assertRaises(SystemExit):
                tw.resolve_source(proto, 'no-hay', 1)

    def test_prototype_sin_detalle_en_el_build_usa_el_ultimo_barrido(self):
        with tempfile.TemporaryDirectory() as temp:
            proto = Path(temp) / '30.x'
            sin_detalle = {'fmax': informe()['fmax']}
            escribir(proto / 'reports' / '20260102-000000-build', 'hardware.pnr', sin_detalle)
            barrido = proto / 'reports' / '20260102-000000-build' / 'sweep-20260102-101010-1'
            barrido.mkdir(parents=True)
            (barrido / 'results.json').write_text(json.dumps([
                {'seed': 4, 'clocks': {'c': {'achieved': 90.0, 'constraint': 80.0}}, 'passes': True}]))
            escribir(barrido / 'seed-4', 'hardware.pnr', informe())
            salida = io.StringIO()
            with patch.object(tw, 'resolve_prototype', return_value=proto), \
                 patch.object(tw, 'find_repo_root', return_value=Path(temp)), \
                 patch.object(sys, 'stdout', salida):
                self.assertEqual(tw.main(['-p', '30']), 0)
            self.assertIn('no trae detalle por red', salida.getvalue())
            self.assertIn('wide_i.buffer', salida.getvalue())

    def test_sin_fuente_pide_una(self):
        with self.assertRaises(SystemExit), patch.object(sys, 'stderr', io.StringIO()):
            tw.main([])


if __name__ == '__main__':
    unittest.main()
