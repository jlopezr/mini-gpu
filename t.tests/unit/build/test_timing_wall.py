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


def netlist():
    """Un `hardware.json` aplanado minimo: tres flip-flops de `cpu.v` y uno del buffer.

    Bits 10-13: `if_instruction` (4 bits), y `if_rd` es un trozo suyo.
    Bits 20-21: `register_write_data`, que llega como puerto a `register_file_i`.
    Bits 30-31: `id_instruction`, y `id_offset` lo extiende con signo y le pone un cero.
    Bit 40: un registro del buffer que tambien es un puerto de `cpu_i`.
    """
    def ff(bit, src):
        return {'type': 'TRELLIS_FF', 'attributes': {'src': f'{src}|cells_map_trellis.v:83.1-83.2'},
                'connections': {'Q': [bit]}}

    def wire(bits, src):
        return {'hide_name': 0, 'bits': bits, 'attributes': {'src': src}}
    cells = {f'$auto$ff.cc:337:slice${b}': ff(b, 'cpu.v:493.3-724.6') for b in (10, 11, 12, 13, 20, 21, 30, 31)}
    cells['$auto$ff.cc:337:slice$40'] = ff(40, 'instruction_buffer.v:144.3-236.6')
    cells['$abc$lut$1'] = {'type': 'LUT4', 'attributes': {}, 'connections': {'Z': [50]}}
    return {'modules': {'top': {'attributes': {'top': '00000000000000000000000000000001'}, 'cells': cells,
                                'netnames': {
        'cpu_i.if_instruction': wire([10, 11, 12, 13], 'cpu.v:144.14-144.28'),
        'cpu_i.if_rd': wire([12, 13], 'cpu.v:278.14-278.19'),
        'cpu_i.register_write_data': wire([20, 21], 'cpu.v:125.14-125.33'),
        'cpu_i.register_file_i.write_data': wire([20, 21], 'register_file.v:46.18-46.28'),
        'cpu_i.id_instruction': wire([30, 31], 'cpu.v:148.14-148.28'),
        'cpu_i.id_offset': wire([31, 31, 31, 30, 31, '0'], 'cpu.v:198.15-198.28'),
        'cpu_i.imem_read_data': wire([40], 'cpu.v:28.18-28.32'),
        'instruction_buffer_i.cpu_imem_read_data': wire([40], 'instruction_buffer.v:53.24-53.42'),
        '$abc$hidden': {'hide_name': 1, 'bits': [10], 'attributes': {}},
    }}}}


class PorRegistroTest(unittest.TestCase):
    def test_cada_flip_flop_toma_el_nombre_de_su_registro_y_no_el_de_un_alias(self):
        n = tw.register_names(netlist())
        self.assertEqual(n['$auto$ff.cc:337:slice$12'], 'cpu_i.if_instruction')        # no el trozo if_rd
        self.assertEqual(n['$auto$ff.cc:337:slice$20'], 'cpu_i.register_write_data')   # no el puerto de abajo
        self.assertEqual(n['$auto$ff.cc:337:slice$31'], 'cpu_i.id_instruction')        # no la extension de signo
        self.assertEqual(n['$auto$ff.cc:337:slice$40'], 'instruction_buffer_i.cpu_imem_read_data')
        self.assertNotIn('$abc$lut$1', n)                                              # no es un flip-flop

    def test_analyze_agrupa_por_registro_y_filtra_por_prefijo(self):
        nombres = tw.register_names(netlist())
        pnr = informe(nets=[net('d', '$auto$ff.cc:337:slice$10', 11.0),
                            net('d', '$auto$ff.cc:337:slice$12', 10.5),
                            net('d', '$auto$ff.cc:337:slice$30', 6.0),
                            net('d', '$auto$ff.cc:337:slice$40', 9.0),
                            net('d', 'ram_i.mem.0.1', 4.0)])            # sin nombre en el netlist: la celda
        a = tw.analyze(pnr, names=nombres)
        self.assertEqual(a['families']['cpu_i.if_instruction']['endpoints'], 2)
        self.assertAlmostEqual(a['families']['cpu_i.if_instruction']['worst'], 11.0)
        self.assertEqual(a['families']['cpu_i.if_instruction']['module'], 'cpu_i')
        self.assertIn('ram_i.mem', a['families'])
        solo_cpu = tw.analyze(pnr, names=nombres, prefix='cpu_i.')
        self.assertEqual(set(solo_cpu['families']), {'cpu_i.if_instruction', 'cpu_i.id_instruction'})
        self.assertEqual(solo_cpu['endpoints'], 3)

    def test_resumen_por_etapa_y_lo_que_no_encaja_va_a_otros(self):
        a = tw.analyze(informe(nets=[net('d', 'c1', 11.0), net('d', 'c2', 6.0), net('d', 'c3', 5.0),
                                     net('d', 'c4', 7.5)]),
                       names={'c1': 'cpu_i.if_pc', 'c2': 'cpu_i.ex_result', 'c3': 'cpu_i.ex_rd',
                              'c4': 'cpu_i.running'})
        texto = '\n'.join(tw.stage_lines(a, *tw.parse_stages('if_,ex_,wb_')))
        self.assertRegex(texto, r'\nIF\s+11\.00\s+88\s+1\s+1\s+1\s+0')
        self.assertRegex(texto, r'\nEX\s+6\.00\s+48\s+2\s+2\s+0\s+0')
        self.assertNotIn('wb_', texto)                                   # sin registros, no sale
        self.assertIn('(sin etapa): running 7.50', texto)

    def test_ports_separa_dato_de_enable(self):
        def ep(cell, port, arrival):
            return {'driver': 'd', 'net': 'd', 'event': 'posedge $glbnet$sdram_clk$TRELLIS_IO_OUT',
                    'endpoints': [{'cell': cell, 'delay': arrival, 'port': port}]}
        a = tw.analyze(informe(nets=[ep('c1', 'M', 2.5), ep('c1', 'CE', 11.0), ep('c1', 'LSR', 4.0),
                                     ep('c2', 'DI', 10.6), ep('c2', 'CE', 7.0),
                                     ep('ram_i.mem.0.1', 'WAD0', 5.0)]),
                       names={'c1': 'cpu_i.if_instruction', 'c2': 'cpu_i.ex_result'})
        f = a['families']
        self.assertEqual(f['cpu_i.if_instruction']['ports'], {'dato': 2.5, 'enable': 11.0, 'otras': 4.0})
        self.assertEqual(f['ram_i.mem']['ports'], {'dato': 0.0, 'enable': 0.0, 'otras': 5.0})
        texto = '\n'.join(tw.report_lines(a, top=5, ports=True))
        self.assertRegex(texto, r'cpu_i\.if_instruction\s+cpu_i\s+11\.00\s+\+1\.50\s+2\.50\s+11\.00\s+4\.00')
        self.assertRegex(texto, r'ram_i\.mem\s+ram_i\s+5\.00\s+\+7\.50\s+-\s+-\s+5\.00')
        self.assertNotIn('ENABLE', '\n'.join(tw.report_lines(a, top=5)))      # sin --ports, como antes
        etapas = '\n'.join(tw.stage_lines(a, *tw.parse_stages('if_,ex_'), ports=True))
        self.assertRegex(etapas, r'\nIF\s+11\.00\s+88\s+2\.50\s+11\.00\s+4\.00')
        self.assertRegex(etapas, r'\nEX\s+10\.60\s+85\s+10\.60\s+7\.00\s+-')

    def test_el_netlist_se_busca_junto_al_informe_o_en_la_carpeta_del_barrido(self):
        with tempfile.TemporaryDirectory() as temp:
            barrido = Path(temp) / 'sweep-1'
            pnr = escribir(barrido / 'seed-2', 'hardware.pnr', informe())
            with self.assertRaises(SystemExit):
                tw.netlist_for(pnr)
            escribir(barrido, 'hardware.json', netlist())
            self.assertEqual(tw.netlist_for(pnr), (barrido / 'hardware.json').resolve())
            junto = escribir(barrido / 'seed-2', 'hardware.json', netlist())
            self.assertEqual(tw.netlist_for(pnr), junto.resolve())

    def test_main_con_stages_nombra_los_registros(self):
        with tempfile.TemporaryDirectory() as temp:
            carpeta = Path(temp) / 'build'
            pnr = escribir(carpeta, 'hardware.pnr', informe(nets=[net('d', '$auto$ff.cc:337:slice$10', 11.0)]))
            escribir(carpeta, 'hardware.json', netlist())
            salida = io.StringIO()
            with patch.object(sys, 'stdout', salida):
                self.assertEqual(tw.main([str(pnr), '--stages', 'if_,id_', '--filter', 'cpu_i.']), 0)
            texto = salida.getvalue()
            self.assertIn('cpu_i.if_instruction', texto)
            self.assertNotIn('slice$10', texto)
            self.assertIn('solo cpu_i.', texto)
            self.assertRegex(texto, r'\nIF\s+11\.00')


def netlist_conos():
    """Un netlist con logica entre registros, para los conos de entrada.

        if_instruction (bit 1) --RAD--> RAM --DO(11)--+
        id_instruction (bit 2) -----------------------+--LUT--> ex_result.DI
        ex_result      (bit 3) --LUT--> if_instruction.CE            (hacia atras)
        if_instruction (bit 1) --CCU2C A0, COUT--> CIN de otro CCU2C, cuyo A0 es
        id_instruction (bit 2); su S0 --> wb_result.DI                (carry: CIN no cuenta)
        wb_result      (bit 4) --> register_write_data.DI (_WR, por atributo) --LUT--> id_instruction.CE
    """
    def cell(kind, conns, dirs, src='cpu.v:1.1-1.2'):
        return {'type': kind, 'attributes': {'src': src}, 'port_directions': dirs, 'connections': conns}

    def ff(q, di=None, ce=None):
        conns, dirs = {'Q': [q]}, {'Q': 'output'}
        for port, bit in (('DI', di), ('CE', ce)):
            if bit is not None:
                conns[port], dirs[port] = [bit], 'input'
        return cell('TRELLIS_FF', conns, dirs)

    def lut(z, *inputs):
        conns = {'Z': [z], **{p: [b] for p, b in zip('ABCD', inputs)}}
        return cell('LUT4', conns, {p: ('output' if p == 'Z' else 'input') for p in conns})

    def wire(bits, attrs=None):
        return {'hide_name': 0, 'bits': bits, 'attributes': {'src': 'cpu.v:9.1-9.2', **(attrs or {})}}
    cells = {
        'ff_if': ff(1, ce=12), 'ff_id': ff(2, ce=16), 'ff_ex': ff(3, di=10), 'ff_wb': ff(4, di=14),
        'ff_wr': ff(5, di=4),
        'lut_alu': lut(10, 2, 11), 'lut_back': lut(12, 3), 'lut_wr': lut(16, 5),
        'cpu_i.register_file_i.registers.0.0': cell(
            'TRELLIS_DPR16X4', {'RAD0': [1], 'WAD0': [3], 'DO0': [11]},
            {'RAD0': 'input', 'WAD0': 'input', 'DO0': 'output'}),
        'ccu_low': cell('CCU2C', {'A0': [1], 'COUT': [13]}, {'A0': 'input', 'COUT': 'output'}),
        'ccu_high': cell('CCU2C', {'A0': [2], 'CIN': [13], 'S0': [14]},
                         {'A0': 'input', 'CIN': 'input', 'S0': 'output'}),
    }
    netnames = {'cpu_i.if_instruction': wire([1]), 'cpu_i.id_instruction': wire([2]),
                'cpu_i.ex_result': wire([3]), 'cpu_i.wb_result': wire([4]),
                'cpu_i.register_write_data': wire([5], {'pipeline_stage': '_WR'})}
    return {'modules': {'top': {'attributes': {'top': '1'}, 'cells': cells, 'netnames': netnames}}}


class EtapasTest(unittest.TestCase):
    def test_las_llegadas_van_por_tipo_porque_nextpnr_cambia_di_por_m(self):
        ev = 'posedge $glbnet$clk'
        pnr = {'detailed_net_timings': [{'event': ev, 'endpoints': [
            {'cell': 'ff', 'port': 'M', 'delay': 3.0}, {'cell': 'ff', 'port': 'LSR', 'delay': 5.0},
            {'cell': 'ff', 'port': 'CE', 'delay': 4.0}, {'cell': 'ram', 'port': 'WAD0', 'delay': 9.0}]}]}
        self.assertEqual(tw.endpoint_arrivals(pnr, '$glbnet$clk'),
                         {('ff', 'dato'): 3.0, ('ff', 'control'): 5.0})


    def test_parse_stages_separa_prefijos_de_etiquetas(self):
        prefijos, orden = tw.parse_stages('if_,id_,ex_,wb_,_WR')
        self.assertEqual(prefijos, {'if_': 'IF', 'id_': 'ID', 'ex_': 'EX', 'wb_': 'WB'})
        self.assertEqual(orden, ['IF', 'ID', 'EX', 'WB', '_WR'])

    def test_parse_stages_prefijo_con_etiqueta_a_mano(self):
        prefijos, orden = tw.parse_stages(tw.DEFAULT_STAGES)
        self.assertEqual(prefijos['ctl_'], '_CTL')
        self.assertEqual(orden, ['IF', 'ID', 'EX', 'WB', '_CTL'])
        self.assertEqual(tw.stage_label('cpu_i.ctl_step_active', prefijos), '_CTL')

    def test_el_atributo_gana_al_prefijo_y_sin_ninguno_no_hay_etapa(self):
        prefijos, _ = tw.parse_stages('if_,ex_')
        etiquetas = {'cpu_i.fetch_request_pc': 'IF', 'cpu_i.ex_raro': 'WB'}
        self.assertEqual(tw.stage_label('cpu_i.if_pc', prefijos, etiquetas), 'IF')
        self.assertEqual(tw.stage_label('cpu_i.fetch_request_pc', prefijos, etiquetas), 'IF')
        self.assertEqual(tw.stage_label('cpu_i.ex_raro', prefijos, etiquetas), 'WB')
        self.assertIsNone(tw.stage_label('cpu_i.running', prefijos, etiquetas))

    def test_register_tags_y_el_registro_etiquetado_gana_al_alias(self):
        n = netlist_conos()
        n['modules']['top']['netnames']['cpu_i.debug_wr'] = {
            'hide_name': 0, 'bits': [5], 'attributes': {'src': 'cpu.v:2.1-2.2'}}
        self.assertEqual(tw.register_tags(n), {'cpu_i.register_write_data': '_WR'})
        self.assertEqual(tw.register_names(n)['ff_wr'], 'cpu_i.register_write_data')   # y no el alias corto

    def test_conos_cuentan_lut_ram_y_carry(self):
        n = netlist_conos()
        conos, donde, rams = tw.input_cones(n, tw.register_names(n), 'cpu_i.')
        self.assertEqual(conos[('cpu_i.ex_result', 'dato')],
                         {'cpu_i.id_instruction': 1, 'cpu_i.register_file_i.registers': 2,
                          'cpu_i.if_instruction': 2})                  # RAD -> RAM (1) -> LUT (1)
        self.assertNotIn('cpu_i.ex_result', conos[('cpu_i.ex_result', 'dato')])   # WAD no es lectura
        self.assertEqual(conos[('cpu_i.if_instruction', 'control')], {'cpu_i.ex_result': 1})
        self.assertEqual(conos[('cpu_i.wb_result', 'dato')],
                         {'cpu_i.id_instruction': 1, 'cpu_i.if_instruction': 1})   # CIN no suma
        self.assertEqual(rams, {'cpu_i.register_file_i.registers'})
        self.assertEqual(donde[('cpu_i.if_instruction', 'control')], [('ff_if', 'control')])

    def test_matriz_marca_direccion_y_grupos(self):
        n = netlist_conos()
        conos, donde, rams = tw.input_cones(n, tw.register_names(n), 'cpu_i.')
        llegadas = {('ff_ex', 'dato'): 9.0, ('ff_if', 'control'): 11.0, ('ff_id', 'control'): 8.0}
        prefijos, orden = tw.parse_stages('if_,id_,ex_,wb_,_WR')
        r = tw.stage_matrix(conos, donde, rams, llegadas, prefijos, orden, tw.register_tags(n), 'cpu_i.')
        self.assertEqual(r['matrix'][('ID', 'EX', 'dato')], {'depth': 1, 'worst': 9.0})
        self.assertEqual(r['matrix'][('_RAM', 'EX', 'dato')], {'depth': 2, 'worst': 9.0})
        self.assertEqual(r['matrix'][('EX', 'IF', 'control')], {'depth': 1, 'worst': 11.0})
        self.assertEqual(r['matrix'][('_WR', 'ID', 'control')], {'depth': 1, 'worst': 8.0})
        self.assertEqual(tw.direction('EX', 'IF', r['order']), 'atras')
        self.assertEqual(tw.direction('ID', 'EX', r['order']), 'adelante')
        self.assertEqual(tw.direction('_WR', 'ID', r['order']), 'aux')
        texto = '\n'.join(tw.matrix_lines(r, 12.5))
        self.assertRegex(texto, r'\nEX\s+1/11\.0 <')                       # control: EX -> IF hacia atras
        self.assertRegex(texto, r'cpu_i\.ex_result\s+EX\s+cpu_i\.if_instruction\s+control\s+IF\s+1\s+11\.00')
        self.assertNotRegex(texto, r'cpu_i\.register_write_data\s+_WR')   # un grupo `_` no es "hacia atras"


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
