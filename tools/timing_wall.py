"""El "muro" de caminos casi criticos de un build de nextpnr, por modulo y registro.

Un build que cierra timing con poca holgura no suele tener UN camino malo: tiene
cientos casi igual de malos, y arreglar el peor solo descubre el siguiente.
Esto lo enseña de un vistazo -- que registros de destino llegan tarde, de que
modulos son y cuantos son-- y permite comparar dos builds para ver si un cambio
mueve el muro o solo el primer camino.

Lee el informe que nextpnr escribe con `--detailed-timing-report`
(`detailed_net_timings` dentro de `hardware.pnr`): un build normal no lo trae,
pero TODA semilla de `build-sweep` si. Sin detalle, con `--prototype` se usa el
ultimo barrido.

`LLEGADA` es el tiempo acumulado hasta el destino, contado desde el flanco de
reloj, como el ultimo numero de un camino critico. El periodo es el del reloj
elegido (el de menos margen si no se dice), asi que `HOLGURA = periodo - llegada`.
El resto de dominios y las rutas de entrada y salida de pin no se miran.

Yosys aplana el diseño, asi que los registros de la CPU no llevan el nombre de su
modulo y el agrupado por modulo los deja en `(anonimo)`. `--by-register` les
devuelve el nombre del RTL con el `hardware.json` de Yosys (ver `register_names`), y
`--stages` los resume por etapa (atributo `pipeline_stage` del RTL o prefijo del
nombre), y `--stage-matrix` sigue el netlist hacia atras para ver de que etapa sale
cada camino (ver `input_cones`). `--path` enseña
el camino critico completo del reloj, salto a salto, con el fichero y la linea de
cada red con nombre y la distancia que recorre en la FPGA.
"""
import argparse
import collections
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.prototype import PrototypeResolutionError, find_repo_root, resolve_prototype  # noqa: E402

# Fracciones del periodo a partir de las cuales un destino cuenta como casi
# critico. A 80 MHz son 10,0 y 11,25 ns.
NEAR = 0.80
HARD = 0.90


def load_pnr(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f'No se puede leer {path}: {exc}')


def has_detail(pnr):
    return bool(pnr.get('detailed_net_timings'))


def best_seed_folder(sweep_folder):
    """La semilla de un barrido con mas margen en su reloj mas justo."""
    sweep_folder = Path(sweep_folder)
    try:
        results = json.loads((sweep_folder / 'results.json').read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        results = []
    if not results:
        raise SystemExit(f'{sweep_folder} no tiene results.json con semillas.')
    margin = lambda r: min(v['achieved'] / v['constraint'] for v in r['clocks'].values())  # noqa: E731
    return sweep_folder / f'seed-{max(results, key=margin)["seed"]}'


def pnr_from_path(path):
    """Un .pnr, una carpeta seed-N, o un barrido (se toma su mejor semilla)."""
    path = Path(path)
    if path.is_file():
        return path
    if (path / 'hardware.pnr').is_file():
        return path / 'hardware.pnr'
    if (path / 'results.json').is_file():
        return best_seed_folder(path) / 'hardware.pnr'
    raise SystemExit(f'{path} no es un hardware.pnr, una carpeta seed-N ni un barrido.')


def sweeps_of(prototype_dir):
    return sorted((Path(prototype_dir) / 'reports').glob('*/sweep-*'), key=lambda d: d.name)


def resolve_source(prototype_dir, sweep=None, seed=None):
    """(ruta al .pnr, nota) para un prototipo: el ultimo build, o un barrido."""
    prototype_dir = Path(prototype_dir)
    if sweep is not None:
        candidates = sweeps_of(prototype_dir)
        if sweep == 'latest':
            matches = candidates[-1:]
        elif Path(sweep).is_dir():
            matches = [Path(sweep)]
        else:
            matches = [d for d in candidates if sweep in d.name]
        if len(matches) != 1:
            raise SystemExit(f'"{sweep}" coincide con {len(matches)} barridos; '
                             f'usa build-sweep --list para ver los nombres.')
        folder = matches[0] / f'seed-{seed}' if seed is not None else best_seed_folder(matches[0])
        return folder / 'hardware.pnr', f'barrido {matches[0].name}, {folder.name}'
    builds = sorted(d for d in (prototype_dir / 'reports').glob('*') if (d / 'hardware.pnr').is_file())
    if builds:
        return builds[-1] / 'hardware.pnr', f'build {builds[-1].name}'
    raise SystemExit(f'{prototype_dir.name} no tiene builds archivados.')


def pick_clock(pnr, wanted=None):
    """(nombre, exigido MHz, alcanzado MHz) del reloj pedido o del de menos margen."""
    fmax = pnr.get('fmax', {})
    if not fmax:
        raise SystemExit('El informe no trae fmax: no se sabe que reloj mirar.')
    if wanted:
        # Un nombre exacto gana al trozo: `clk` esta dentro de `clk_pix`, pero el
        # reloj completo (`$glbnet$clk`) solo puede ser uno.
        matches = [c for c in fmax if c == wanted] or [c for c in fmax if wanted in c]
        if len(matches) != 1:
            raise SystemExit(f'"{wanted}" coincide con {len(matches)} relojes: {", ".join(fmax)}')
        name = matches[0]
    else:
        name = min(fmax, key=lambda c: fmax[c]['achieved'] / fmax[c]['constraint'])
    return name, fmax[name]['constraint'], fmax[name]['achieved']


def family(cell):
    """`dmem_adapter_i.wb_data_TRELLIS_FF_Q_107` -> `dmem_adapter_i.wb_data`."""
    cell = re.sub(r'_TRELLIS_FF_Q.*|_TRELLIS_RAMW.*|\.\d+.*$', '', cell)
    cell = re.sub(r'\[\d+\]', '', cell)
    return re.sub(r'_\d+$', '', cell)


def module(cell):
    match = re.match(r'([A-Za-z_][A-Za-z0-9_]*)\.', cell)
    return match.group(1) if match else '(anonimo)'


# Entradas de un TRELLIS_FF por las que llega el camino. Separarlas dice si un
# registro llega tarde porque CALCULA algo (dato) o porque ESPERA la decision de
# si se actualiza (enable): en una CPU segmentada, IF e ID suelen copiar el dato
# en pocos ns y llegar tarde solo por el enable, que viene de la etapa que
# decide saltos y paradas. Lo que no es dato ni enable (reset, puertos de
# escritura de RAM distribuida, multiplicadores) va a `otras`.
PORT_KINDS = ('dato', 'enable', 'otras')
_PORT_KIND = {'DI': 'dato', 'M': 'dato', 'D': 'dato', 'CE': 'enable'}


def port_kind(port):
    return _PORT_KIND.get(port, 'otras')


def _ports_cells(ports, p):
    return tuple(_arrival_cell(ports[k], p) if ports[k] else '-' for k in PORT_KINDS)


# ---- nombres del RTL (--by-register) --------------------------------------

def netlist_for(pnr_path, explicit=None):
    """El `hardware.json` de Yosys que va con un informe: junto a el o en una carpeta de encima.

    `build` lo archiva junto al `.pnr`; en un barrido la sintesis es una sola, asi
    que puede estar en la carpeta del barrido y no en la de cada semilla.
    """
    if explicit is not None:
        if not Path(explicit).is_file():
            raise SystemExit(f'No existe {explicit}.')
        return Path(explicit)
    folder = Path(pnr_path).resolve().parent
    for candidate in (folder, *list(folder.parents)[:2]):
        if (candidate / 'hardware.json').is_file():
            return candidate / 'hardware.json'
    raise SystemExit(f'No hay hardware.json junto a {pnr_path} ni dos carpetas por encima: '
                     f'indicalo con --netlist.')


STAGE_ATTRIBUTE = 'pipeline_stage'


def _source_file(attrs):
    return (attrs.get('src') or '').split(':', 1)[0]


def top_module(netlist):
    modules = netlist.get('modules', {})
    top = next((m for m in modules.values() if m.get('attributes', {}).get('top')), None)
    if top is None and len(modules) == 1:
        top = next(iter(modules.values()))
    if top is None:
        raise SystemExit('El netlist no tiene un modulo top aplanado.')
    return top


def register_names(netlist):
    """Celda de flip-flop -> nombre del registro del RTL al que pertenece su salida.

    El informe de nextpnr solo nombra celdas (`$auto$ff.cc:337:slice$N` en un
    diseño aplanado). En el netlist de Yosys la salida `Q` de cada celda es un
    numero de bit, y `netnames` dice que señales contienen ese bit. Suele haber
    varias, porque un `wire` que corta trozos de un registro (`if_rd =
    if_instruction[25:21]`) comparte sus bits, los puertos de los modulos que lo
    reciben tambien, y el netlist no distingue un `reg` de un `wire`. Se elige,
    por este orden:

    1. una señal declarada en el mismo fichero que el `always` que escribe el
       flip-flop (el `src` de la celda): `cpu_i.register_write_data` y no el
       puerto `register_file_i.write_data` que la recibe;
    2. una señal con atributo `pipeline_stage`: si el RTL la ha etiquetado, es
       el registro (`architectural_pc` y no `assign debug_pc = architectural_pc`);
    3. una señal *pura*: todos sus bits salen de flip-flops, sin constantes ni
       bits repetidos (descarta extensiones de signo y `{x, 2'b00}`);
    4. la mas ancha (el registro entero gana al trozo);
    5. la mas profunda en la jerarquia;
    6. la de nombre mas corto.

    Las celdas que no son flip-flops (RAM distribuida, multiplicadores) no
    salen: para ellas se sigue usando el nombre de la celda.
    """
    top = top_module(netlist)
    q_of = {}
    for cell, info in top.get('cells', {}).items():
        q = info.get('connections', {}).get('Q')
        if q and isinstance(q[0], int):
            q_of[cell] = (q[0], _source_file(info.get('attributes', {})))
    ff_bits = {bit for bit, _ in q_of.values()}
    candidates = collections.defaultdict(list)
    for name, info in top.get('netnames', {}).items():
        if info.get('hide_name'):
            continue
        bits = info.get('bits', [])
        ints = [b for b in bits if isinstance(b, int)]
        if not any(b in ff_bits for b in ints):
            continue
        attrs = info.get('attributes', {})
        pure = len(ints) == len(bits) and len(set(ints)) == len(ints) and all(b in ff_bits for b in ints)
        entry = (_source_file(attrs),
                 (STAGE_ATTRIBUTE in attrs, pure, len(bits), name.count('.'), -len(name)), name)
        for b in set(ints):
            if b in ff_bits:
                candidates[b].append(entry)
    names = {}
    for cell, (bit, cell_file) in q_of.items():
        if candidates[bit]:
            names[cell] = max(candidates[bit], key=lambda c: (c[0] == cell_file, c[1]))[2]
    return names


def register_tags(netlist):
    """Registro -> valor de su atributo `(* pipeline_stage = "..." *)` en el RTL.

    Yosys conserva los atributos de las señales al aplanar y sintetizar (no los
    de las memorias). Ver `stage_label` para como se combinan con los prefijos.
    """
    return {name: info['attributes'][STAGE_ATTRIBUTE]
            for name, info in top_module(netlist).get('netnames', {}).items()
            if STAGE_ATTRIBUTE in info.get('attributes', {})}


def load_netlist(pnr_path, explicit=None):
    path = netlist_for(pnr_path, explicit)
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f'No se puede leer {path}: {exc}')


def load_register_names(pnr_path, explicit=None):
    return register_names(load_netlist(pnr_path, explicit))


def analyze(pnr, clock=None, names=None, prefix=None):
    """Familias de registros de destino de un reloj, con su peor llegada y cuantos pasan de 80 % y 90 %.

    Con `names` (celda -> registro del RTL, de `register_names`) la familia es el
    registro; sin el, el nombre de la celda limpio. `prefix` deja solo las
    familias que empiezan asi (p. ej. `cpu_i.`).
    """
    if not has_detail(pnr):
        raise SystemExit('Este informe no trae detalle por red (`detailed_net_timings`): '
                         'hace falta un barrido, o `--detailed-timing-report` en el apio.ini.')
    name, constraint, achieved = pick_clock(pnr, clock)
    period = 1000.0 / constraint
    families = {}
    hops = {}
    endpoints = 0
    names = names or {}
    for net in pnr['detailed_net_timings']:
        if name not in net.get('event', ''):
            continue
        for ep in net.get('endpoints', []):
            cell = ep.get('cell', '')
            if '$tr_io' in cell:      # pines: el rutado hasta ellos no se cronometra aqui
                continue
            key = names.get(cell) or family(cell)
            if prefix and not key.startswith(prefix):
                continue
            delay = ep['delay']
            arrival = max(delay) if isinstance(delay, list) else delay
            entry = families.setdefault(key, dict(module=module(key), worst=0.0,
                                                  near=0, hard=0, endpoints=0,
                                                  ports={k: 0.0 for k in PORT_KINDS}))
            entry['worst'] = max(entry['worst'], arrival)
            kind = port_kind(ep.get('port', ''))
            entry['ports'][kind] = max(entry['ports'][kind], arrival)
            entry['near'] += arrival >= NEAR * period
            entry['hard'] += arrival >= HARD * period
            entry['endpoints'] += 1
            endpoints += 1
            hop = hops.setdefault((module(net.get('driver', '')), module(key)),
                                  dict(worst=0.0, near=0, hard=0))
            hop['worst'] = max(hop['worst'], arrival)
            hop['near'] += arrival >= NEAR * period
            hop['hard'] += arrival >= HARD * period
    return dict(clock=name, constraint=constraint, achieved=achieved, period=period,
                endpoints=endpoints, families=families, hops=hops,
                near=sum(f['near'] for f in families.values()),
                hard=sum(f['hard'] for f in families.values()))


def critical_path(pnr, clock=None):
    """El camino critico completo del reloj, salto a salto, con fichero y posicion.

    `detailed_net_timings` solo trae los destinos finales (registros y RAM), asi
    que no permite reconstruir el camino de cada uno: las LUT intermedias no
    salen. El camino critico de `critical_paths` si es completo, y cada red con
    nombre conserva `sources` (fichero:linea donde se declara). Las redes que crea
    ABC no tienen fuente y salen sin ella, pero la posicion (`loc`) deja ver si
    el camino cruza media FPGA.
    """
    name, constraint, achieved = pick_clock(pnr, clock)
    edge = lambda event: re.sub(r'^(posedge|negedge) ', '', event or '')  # noqa: E731
    paths = [p for p in pnr.get('critical_paths', [])
             if edge(p.get('from')) == name and edge(p.get('to')) == name]
    if not paths:
        raise SystemExit(f'El informe no trae camino critico propio del reloj {name}.')
    hops, total = [], 0.0
    for step in paths[0]['path']:
        total += step['delay']
        source = (step.get('sources') or [''])[0]
        if 'share/yosys' in source.replace('\\', '/'):    # la celda de la biblioteca, no es RTL nuestro
            source = ''
        hops.append(dict(kind=step['type'], delay=step['delay'], total=total,
                         net=step.get('net', ''), source=source,
                         start=tuple(step['from'].get('loc', ())), end=tuple(step['to'].get('loc', ()))))
    return dict(clock=name, constraint=constraint, achieved=achieved, period=1000.0 / constraint,
                hops=hops, total=total)


def path_lines(path, source=None, color=False):
    lines = []
    if source:
        lines.append(f'Fuente: {source}')
    lines.append(f'Reloj: {path["clock"]}   exigido {path["constraint"]:.1f} MHz '
                 f'(periodo {path["period"]:.2f} ns)   alcanzado {path["achieved"]:.2f} MHz')
    rows = [('TIPO', 'NS', 'ACUM', 'DISTANCIA', 'RED', 'DONDE SE DECLARA')]
    logic = routing = 0.0
    for h in path['hops']:
        if h['kind'] == 'routing':
            routing += h['delay']
        elif h['kind'] == 'logic':
            logic += h['delay']
        far = ''
        if h['kind'] == 'routing' and len(h['start']) == 2 and len(h['end']) == 2:
            far = str(abs(h['start'][0] - h['end'][0]) + abs(h['start'][1] - h['end'][1]))
        slow = h['kind'] == 'routing' and h['delay'] >= 1.5
        rows.append((h['kind'], (f'{h["delay"]:.2f}', '33' if slow else None), f'{h["total"]:.2f}', far,
                     h['net'][:60], h['source']))
    lines += [''] + _table(rows, color)
    lines += ['', f'Camino de {path["total"]:.2f} ns: {logic:.2f} de logica y {routing:.2f} de ruteo '
                  f'({100 * routing / max(path["total"], 1e-9):.0f} % ruteo; el resto es clk-a-q y setup).',
              'DISTANCIA es la suma de columnas y filas entre los extremos de cada salto de ruteo.']
    return lines


def by_module(analysis):
    modules = collections.defaultdict(lambda: dict(worst=0.0, near=0, hard=0))
    for entry in analysis['families'].values():
        m = modules[entry['module']]
        m['worst'] = max(m['worst'], entry['worst'])
        m['near'] += entry['near']
        m['hard'] += entry['hard']
    return modules


# ---- presentacion ---------------------------------------------------------

def _use_color():
    return sys.stdout.isatty() and 'NO_COLOR' not in os.environ


def _paint(text, code, color):
    return f'\033[{code}m{text}\033[0m' if color and code else text


def _table(rows, color):
    """Filas de celdas (texto o (texto, codigo ANSI)); se rellena el texto plano y luego se pinta."""
    grid = [[c if isinstance(c, tuple) else (c, None) for c in row] for row in rows]
    widths = [max(len(r[i][0]) for r in grid) for i in range(len(grid[0]))]
    return [('  '.join(_paint(t, c, color) + ' ' * (w - len(t))
                        for (t, c), w in zip(row, widths))).rstrip() for row in grid]


def _arrival_cell(value, period):
    code = '31' if value >= period else '33' if value >= HARD * period else None
    return f'{value:.2f}', code


def _header(analysis, source=None):
    p = analysis['period']
    lines = []
    if source:
        lines.append(f'Fuente: {source}')
    lines.append(f'Reloj: {analysis["clock"]}   exigido {analysis["constraint"]:.1f} MHz '
                 f'(periodo {p:.2f} ns)   alcanzado {analysis["achieved"]:.2f} MHz '
                 f'({1000 / analysis["achieved"]:.2f} ns)')
    lines.append(f'Destinos con llegada >= {int(NEAR * 100)} % del periodo ({NEAR * p:.2f} ns): '
                 f'{analysis["near"]} de {analysis["endpoints"]}; '
                 f'>= {int(HARD * 100)} % ({HARD * p:.2f} ns): {analysis["hard"]}')
    return lines


def report_lines(analysis, top=20, source=None, color=False, ports=False):
    p = analysis['period']
    lines = _header(analysis, source) + ['']
    ranked = sorted(analysis['families'].items(), key=lambda kv: -kv[1]['worst'])[:top]
    extra = tuple(k.upper() for k in PORT_KINDS) if ports else ()
    rows = [('REGISTRO DE DESTINO', 'MODULO', 'LLEGADA', 'HOLGURA', *extra, '>=80 %', '>=90 %')]
    for name, e in ranked:
        rows.append((name, e['module'], _arrival_cell(e['worst'], p), f'{p - e["worst"]:+.2f}',
                     *(_ports_cells(e['ports'], p) if ports else ()),
                     str(e['near']), str(e['hard'])))
    lines += _table(rows, color) + ['']
    if ports:
        lines += ['DATO: entrada de dato (DI/M); ENABLE: CE, la decision de si el registro se actualiza; '
                  'OTRAS: reset y puertos de RAM.', '']
    rows = [('MODULO', 'LLEGADA', '>=80 %', '>=90 %')]
    modules = sorted(by_module(analysis).items(), key=lambda kv: -kv[1]['worst'])
    for name, m in modules[:12]:
        rows.append((name, _arrival_cell(m['worst'], p), str(m['near']), str(m['hard'])))
    return lines + _table(rows, color)


UNSTAGED = '(sin etapa)'
DEFAULT_STAGES = 'if_,id_,ex_,wb_,ctl_=_CTL'
OUTSIDE = '(fuera)'
RAM_GROUP = '_RAM'


def parse_stages(text):
    """`if_,id_,ex_,wb_,ctl_=_CTL,_WR` -> ({'if_': 'IF', ..., 'ctl_': '_CTL'}, ['IF', ..., '_CTL', '_WR']).

    Un elemento que acaba en `_` y va en minusculas es un prefijo de nombre, y
    su etiqueta es el prefijo en mayusculas sin el `_`. `prefijo=ETIQUETA` da
    la etiqueta a mano, p. ej. `ctl_=_CTL` para un grupo que no es etapa.
    Cualquier otro es una etiqueta de atributo (`_WR`, `_CTL`) y solo fija su
    sitio en el orden.
    """
    prefixes, order = {}, []
    for token in (t.strip() for t in text.split(',')):
        if not token:
            continue
        if '=' in token:
            prefix, label = (x.strip() for x in token.split('=', 1))
            prefixes[prefix] = label
        elif token.endswith('_') and token == token.lower() and not token.startswith('_'):
            prefixes[token] = token.rstrip('_').upper()
            label = prefixes[token]
        else:
            label = token
        if label not in order:
            order.append(label)
    return prefixes, order


def is_pseudo(label):
    """Las etiquetas que empiezan por `_` son grupos que no son etapas del pipeline (`_WR`, `_CTL`)."""
    return label.startswith('_') or label.startswith('(')


def stage_label(register, prefixes, tags=None):
    """Etapa de un registro: su atributo `pipeline_stage` si lo tiene; si no, su prefijo; si no, None."""
    if tags and register in tags:
        return tags[register]
    short = register.rsplit('.', 1)[-1]
    return next((label for prefix, label in prefixes.items() if short.startswith(prefix)), None)


def _full_order(order, labels):
    """El orden pedido, luego las etapas reales que falten y luego los grupos `_`, `(fuera)` y `(sin etapa)`."""
    extra = sorted(set(labels) - set(order) - {UNSTAGED, OUTSIDE})
    return order + [x for x in extra if not is_pseudo(x)] + [x for x in extra if is_pseudo(x)] + \
        [x for x in (OUTSIDE, UNSTAGED) if x in labels]


def stage_lines(analysis, prefixes, order, tags=None, color=False, ports=False):
    """Resumen por etapa: los registros se reparten por su atributo o por el prefijo de su nombre.

    La etapa no se deduce del circuito: sale del RTL, del atributo
    `(* pipeline_stage = "..." *)` o, si no lo hay, de la convencion de nombres
    (`if_*`, `id_*`...). Lo que no tiene ninguna de las dos va a `(sin etapa)`
    y se lista, para que se vea que ha quedado sin clasificar. Con `ports`,
    ademas, la peor llegada por tipo de entrada (ver `PORT_KINDS`).
    """
    p = analysis['period']
    groups = collections.defaultdict(lambda: dict(worst=0.0, registers=0, bits=0, near=0, hard=0,
                                                  ports={k: 0.0 for k in PORT_KINDS}))
    others = []
    for register, e in analysis['families'].items():
        stage = stage_label(register, prefixes, tags)
        if stage is None:
            stage = UNSTAGED
            others.append((register, e['worst']))
        g = groups[stage]
        g['worst'] = max(g['worst'], e['worst'])
        g['registers'] += 1
        g['bits'] += e['endpoints']
        g['near'] += e['near']
        g['hard'] += e['hard']
        for k in PORT_KINDS:
            g['ports'][k] = max(g['ports'][k], e['ports'][k])
    extra = tuple(k.upper() for k in PORT_KINDS) if ports else ()
    rows = [('ETAPA', 'LLEGADA', '% PERIODO', *extra, 'REGISTROS', 'DESTINOS', '>=80 %', '>=90 %')]
    for stage in _full_order(order, groups):
        g = groups.get(stage)
        if not g or not g['registers']:
            continue
        rows.append((stage, _arrival_cell(g['worst'], p),
                     f'{100 * g["worst"] / p:.0f}', *(_ports_cells(g['ports'], p) if ports else ()),
                     str(g['registers']), str(g['bits']), str(g['near']), str(g['hard'])))
    lines = ['Por etapa (atributo pipeline_stage, o prefijo del nombre; `_` = grupo que no es etapa):']
    lines += _table(rows, color)
    if others:
        others.sort(key=lambda o: -o[1])
        shown = ', '.join(f'{r.rsplit(".", 1)[-1]} {w:.2f}' for r, w in others[:12])
        more = f' y {len(others) - 12} mas' if len(others) > 12 else ''
        lines.append(f'{UNSTAGED}: {shown}{more}')
    return lines


# ---- conos de entrada (--stage-matrix) -------------------------------------

# Cuantas LUT cuenta cada celda al cruzarla. El carry (CCU2C) cuenta una al
# entrar por A/B/C/D y ninguna a lo largo de la cadena (CIN), que es rapida; los
# multiplexores de slice (PFUMX, L6MUX21) no cuentan. La lectura asincrona de
# la RAM distribuida (de RAD a DO) cuenta una, como una LUT.
_LUT_STEP = {'LUT4': 1, 'TRELLIS_DPR16X4': 1}


def _cone_kind(port):
    """dato (DI/M/D) o control (CE/LSR); None para lo demas (puertos de RAM...)."""
    return 'dato' if port in ('DI', 'M', 'D') else 'control' if port in ('CE', 'LSR') else None


def endpoint_arrivals(pnr, clock_name):
    """(celda, dato|control) -> peor llegada, para los destinos del reloj.

    Por tipo y no por puerto: nextpnr puede mover el dato de DI a M al colocar el
    flip-flop, asi que el puerto del netlist de Yosys no siempre es el del informe.
    """
    out = {}
    for net in pnr.get('detailed_net_timings', []):
        if clock_name not in net.get('event', ''):
            continue
        for ep in net.get('endpoints', []):
            delay = ep['delay']
            arrival = max(delay) if isinstance(delay, list) else delay
            kind = _cone_kind(ep.get('port', ''))
            if kind is None:
                continue
            key = (ep.get('cell', ''), kind)
            out[key] = max(out.get(key, 0.0), arrival)
    return out


def input_cones(netlist, names, scope=None):
    """Para cada flip-flop (dentro de `scope`) y cada entrada: registros de los que sale y cuantas LUT cruza.

    Recorre el netlist de Yosys hacia atras desde las entradas DI/M/CE/LSR del
    flip-flop, por la logica combinacional, hasta dar con salidas de flip-flops
    (el origen es su registro, via `names`) o con una RAM distribuida (el origen
    es la propia memoria: su contenido; y se sigue por la direccion de lectura).
    Devuelve {(registro destino, tipo de entrada): {registro origen: maximo de LUT}},
    {(registro destino, tipo de entrada): [(celda, tipo)]} para buscar llegadas,
    y el conjunto de origenes que son memorias.
    No da tiempos por par: eso exigiria un analisis de timing propio.
    """
    top = top_module(netlist)
    cells = top.get('cells', {})
    driver = {}
    for cell, info in cells.items():
        for port, direction in info.get('port_directions', {}).items():
            if direction == 'output':
                for b in info.get('connections', {}).get(port, []):
                    if isinstance(b, int):
                        driver[b] = (cell, port)
    memo = {}
    busy = set()
    rams = set()

    def cone(bit):
        if not isinstance(bit, int) or bit not in driver:
            return {}
        if bit in memo:
            return memo[bit]
        if bit in busy:                       # bucle combinacional: no deberia haberlo
            return {}
        busy.add(bit)
        cell, _ = driver[bit]
        info = cells[cell]
        kind = info['type']
        result = {}
        if kind == 'TRELLIS_FF':
            result = {names.get(cell, family(cell)): 0}
        else:
            if kind == 'TRELLIS_DPR16X4':
                result[family(cell)] = 1
                rams.add(family(cell))
            for port, direction in info.get('port_directions', {}).items():
                if direction != 'input':
                    continue
                if kind == 'TRELLIS_DPR16X4' and not port.startswith('RAD'):
                    continue                 # escritura: secuencial, no forma parte del cono de lectura
                step = _LUT_STEP.get(kind, 0)
                if kind == 'CCU2C':
                    step = 0 if port == 'CIN' else 1
                for b in info.get('connections', {}).get(port, []):
                    for src, depth in cone(b).items():
                        if depth + step > result.get(src, -1):
                            result[src] = depth + step
        busy.discard(bit)
        memo[bit] = result
        return result

    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(limit, 20000))
    try:
        cones, where = {}, collections.defaultdict(list)
        for cell, info in cells.items():
            if info['type'] != 'TRELLIS_FF':
                continue
            dest = names.get(cell, family(cell))
            if scope and not dest.startswith(scope):
                continue
            for port in ('DI', 'M', 'CE', 'LSR'):
                bits = info.get('connections', {}).get(port)
                if not bits:
                    continue
                key = (dest, _cone_kind(port))
                if (cell, key[1]) not in where[key]:
                    where[key].append((cell, key[1]))
                acc = cones.setdefault(key, {})
                for b in bits:
                    for src, depth in cone(b).items():
                        acc[src] = max(acc.get(src, 0), depth)
    finally:
        sys.setrecursionlimit(limit)
    return cones, where, rams


def stage_matrix(cones, where, rams, arrivals, prefixes, order, tags, scope=None):
    """Matriz etapa origen x etapa destino, y la lista de caminos entre etapas.

    Cada casilla: el maximo de LUT de un camino de esa etapa a esa otra, y la
    peor llegada de los destinos que reciben alguno de esos caminos. La llegada
    es del destino, no del par (nextpnr no da tiempos por par): si un destino
    recibe caminos de dos etapas, las dos casillas comparten su llegada; las LUT
    si son de cada par.
    """
    def label(register, is_ram=False):
        if scope and not register.startswith(scope):
            return OUTSIDE
        if is_ram:
            return RAM_GROUP
        return stage_label(register, prefixes, tags) or UNSTAGED

    matrix, edges = {}, []
    for (dest, kind), sources in cones.items():
        dst_stage = label(dest)
        arrival = max((arrivals.get(cp, 0.0) for cp in where[(dest, kind)]), default=0.0)
        for src, depth in sources.items():
            src_stage = label(src, src in rams)
            cell = matrix.setdefault((src_stage, dst_stage, kind), dict(depth=0, worst=0.0))
            cell['depth'] = max(cell['depth'], depth)
            cell['worst'] = max(cell['worst'], arrival)
            edges.append(dict(src=src, dst=dest, kind=kind, depth=depth, arrival=arrival,
                              src_stage=src_stage, dst_stage=dst_stage))
    labels = {s for key in matrix for s in key[:2]}
    return dict(matrix=matrix, edges=edges, order=_full_order(order, labels))


def direction(src_stage, dst_stage, order):
    """adelante / misma / atras entre etapas reales; `aux` si alguna es un grupo (`_`, `(...)`)."""
    if is_pseudo(src_stage) or is_pseudo(dst_stage):
        return 'aux'
    real = [s for s in order if not is_pseudo(s)]
    if src_stage not in real or dst_stage not in real:
        return 'aux'
    delta = real.index(dst_stage) - real.index(src_stage)
    return 'misma' if delta == 0 else 'adelante' if delta > 0 else 'atras'


def _matrix_table(m, kind, order, period, color):
    rows = [('ORIGEN \\ DESTINO', *order)]
    for src in order:
        row = [src]
        for dst in order:
            c = m.get((src, dst, kind))
            if not c:
                row.append('·')
                continue
            code = '31' if c['worst'] >= period else '33' if c['worst'] >= HARD * period else None
            mark = {'atras': ' <', 'misma': ' =', 'adelante': '', 'aux': ''}[direction(src, dst, order)]
            row.append((f'{c["depth"]}/{c["worst"]:.1f}{mark}', code))
        if any(m.get((src, d, kind)) for d in order):
            rows.append(tuple(row))
    return _table(rows, color)


def matrix_lines(result, period, top=15, color=False):
    order = result['order']
    m = result['matrix']
    lines = ['Matrices origen -> destino: LUT maximas del camino / peor llegada de la entrada del destino (ns).',
             'La llegada es del destino, no del par. `<` hacia atras, `=` dentro de la etapa, `·` sin camino.',
             '', 'DATO (DI/M): lo que el registro calcula']
    lines += _matrix_table(m, 'dato', order, period, color)
    lines += ['', 'CONTROL (CE/LSR): si el registro se actualiza o se pone a cero']
    lines += _matrix_table(m, 'control', order, period, color) + ['']
    back = sorted((e for e in result['edges'] if direction(e['src_stage'], e['dst_stage'], order) == 'atras'),
                  key=lambda e: (-e['depth'], -e['arrival']))
    rows = [('ORIGEN', 'ETAPA', 'DESTINO', 'ENTRADA', 'ETAPA', 'LUT', 'LLEGADA')]
    for e in back[:top]:
        rows.append((e['src'], e['src_stage'], e['dst'], e['kind'], e['dst_stage'], str(e['depth']),
                     _arrival_cell(e['arrival'], period)))
    lines.append(f'Caminos hacia atras, {min(top, len(back))} de {len(back)}, por LUT:')
    return lines + _table(rows, color)


def cross_lines(analysis, top=12, color=False):
    """Ultimo salto -> modulo destino, para los destinos casi criticos.

    El origen es el modulo que maneja la ULTIMA red antes del registro destino
    (por el nombre de su celda), no el registro que lanza la senal: el informe de
    nextpnr no trae la ruta completa, solo red a red. Un LUT de `serial_i` que
    alimenta un registro de `mmio_decoder_i` dice de quien es la logica de ese
    ultimo tramo, que es lo que el agrupado por destino esconde.
    """
    p = analysis['period']
    ranked = sorted(((k, v) for k, v in analysis['hops'].items() if v['near']),
                    key=lambda kv: (-kv[1]['near'], -kv[1]['worst']))[:top]
    rows = [('ULTIMO SALTO (modulo)', 'DESTINO (modulo)', 'LLEGADA', '>=80 %', '>=90 %')]
    for (src, dst), h in ranked:
        rows.append((src, dst, _arrival_cell(h['worst'], p), str(h['near']), str(h['hard'])))
    return ['Ultimo salto: modulo que maneja la ultima red antes del destino (no el registro de origen).'] \
        + _table(rows, color)


def compare_lines(a, b, top=20, source_a=None, source_b=None, color=False):
    """Familias de dos builds lado a lado: baja la llegada, o baja el numero de destinos?"""
    p = a['period']
    lines = [f'A: {source_a or "(primero)"}', f'B: {source_b or "(segundo)"}',
             f'Reloj {a["clock"]}: A {a["achieved"]:.2f} MHz -> B {b["achieved"]:.2f} MHz',
             f'Destinos >= {int(NEAR * 100)} % del periodo: {a["near"]} -> {b["near"]};  '
             f'>= {int(HARD * 100)} %: {a["hard"]} -> {b["hard"]}', '']
    names = set(a['families']) | set(b['families'])
    empty = dict(module='', worst=0.0, near=0, hard=0)
    score = lambda n: max(a['families'].get(n, empty)['worst'], b['families'].get(n, empty)['worst'])  # noqa: E731
    rows = [('REGISTRO DE DESTINO', 'LLEGADA A', 'LLEGADA B', 'DELTA', '>=80 % A', '>=80 % B')]
    for name in sorted(names, key=score, reverse=True)[:top]:
        fa, fb = a['families'].get(name, empty), b['families'].get(name, empty)
        delta = fb['worst'] - fa['worst']
        code = '32' if delta <= -0.2 else '31' if delta >= 0.2 else None
        rows.append((name, _arrival_cell(fa['worst'], p) if fa['worst'] else '-',
                     _arrival_cell(fb['worst'], p) if fb['worst'] else '-',
                     (f'{delta:+.2f}' if fa['worst'] and fb['worst'] else '-', code),
                     str(fa['near']), str(fb['near'])))
    return lines + _table(rows, color)


# ---- linea de comandos ----------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                                     epilog='Ejemplos:  timing-wall -p 30   |   timing-wall -p 30 --sweep latest '
                                            '--seed 5   |   timing-wall A/hardware.pnr --compare B/hardware.pnr')
    parser.add_argument('source', nargs='?', type=Path,
                        help='un hardware.pnr, una carpeta seed-N o un barrido (se toma su mejor semilla)')
    parser.add_argument('-p', '--prototype', help='usa el ultimo build de este prototipo')
    parser.add_argument('--sweep', help='con --prototype: un barrido ("latest", un trozo de su nombre o su ruta)')
    parser.add_argument('--seed', type=int, help='con --sweep: la semilla (por defecto la de mas margen)')
    parser.add_argument('--compare', type=Path, metavar='OTRO',
                        help='segundo informe (mismos tipos de ruta que SOURCE) para comparar lado a lado')
    parser.add_argument('--clock', help='trozo del nombre del reloj (por defecto, el de menos margen)')
    parser.add_argument('--top', type=int, default=20, help='cuantas familias enseñar (20)')
    parser.add_argument('--cross', action='store_true',
                        help='añade la tabla ultimo salto -> destino (quien maneja la ultima red)')
    parser.add_argument('--path', action='store_true',
                        help='enseña el camino critico completo del reloj, salto a salto, con fichero, linea y '
                             'distancia: para cuando el diseño esta aplanado y el muro sale como (anonimo)')
    parser.add_argument('--by-register', action='store_true',
                        help='nombra cada destino con su registro del RTL (cpu_i.ex_result) en vez de la celda '
                             '($auto$ff.cc:...slice$N), usando el hardware.json de Yosys del mismo build')
    parser.add_argument('--netlist', type=Path, metavar='JSON',
                        help='hardware.json a usar con --by-register (por defecto, el que esta junto al informe)')
    parser.add_argument('--filter', metavar='PREFIJO',
                        help='solo los destinos cuyo registro empieza asi (p. ej. cpu_i.); mejor con --by-register')
    parser.add_argument('--stages', metavar='P1,P2,...', nargs='?', const=DEFAULT_STAGES,
                        help='resumen por etapa: el atributo (* pipeline_stage *) del registro o, si no lo '
                             'tiene, el prefijo de su nombre corto; prefijos y orden en la lista, '
                             '`prefijo=ETIQUETA` para fijar la etiqueta '
                             f'(sin valor: {DEFAULT_STAGES}); implica --by-register')
    parser.add_argument('--stage-matrix', action='store_true',
                        help='matriz etapa origen x etapa destino con las LUT de cada camino, siguiendo el '
                             'netlist hacia atras desde cada registro, y los caminos hacia atras; implica --stages')
    parser.add_argument('--ports', action='store_true',
                        help='separa la llegada de cada registro por entrada: DATO (calcula) frente a ENABLE '
                             '(espera la decision de actualizarse) y OTRAS')
    args = parser.parse_args(argv)
    if args.ports and args.compare is not None:
        parser.error('--ports no se combina con --compare')
    if args.stage_matrix and args.stages is None:
        args.stages = DEFAULT_STAGES
    prefixes, order = parse_stages(args.stages or '')
    stages = args.stages is not None
    by_register = args.by_register or stages

    if args.source is not None:
        path, note = pnr_from_path(args.source), str(args.source)
    elif args.prototype:
        try:
            prototype_dir = resolve_prototype(args.prototype, root=find_repo_root(Path.cwd()))
        except PrototypeResolutionError as exc:
            raise SystemExit(f'error: {exc}')
        path, note = resolve_source(prototype_dir, args.sweep, args.seed)
        pnr = load_pnr(path)
        if not has_detail(pnr) and args.sweep is None:
            sweeps = sweeps_of(prototype_dir)
            if not sweeps:
                raise SystemExit(f'El ultimo build de {prototype_dir.name} no trae detalle por red y no '
                                 f'hay barridos: ejecuta build-sweep o pon --detailed-timing-report.')
            path, note = resolve_source(prototype_dir, sweeps[-1].name, None)
            note += ' (el build no trae detalle por red; se usa el ultimo barrido)'
    else:
        parser.error('indica un informe o --prototype')
    color = _use_color()
    if args.path:
        if args.compare is not None:
            parser.error('--path no se combina con --compare')
        print('\n'.join(path_lines(critical_path(load_pnr(path), args.clock), f'{note} ({path})', color)))
        return 0
    netlist = load_netlist(path, args.netlist) if by_register else None
    names = register_names(netlist) if netlist else None
    tags = register_tags(netlist) if netlist else {}
    pnr = load_pnr(path)
    analysis = analyze(pnr, args.clock, names, args.filter)
    if args.filter:
        note += f', solo {args.filter}'
    if args.compare is not None:
        other = pnr_from_path(args.compare)
        # El otro build tiene su propio netlist: los nombres de celda no coinciden entre builds.
        other_names = load_register_names(other) if by_register else None
        second = analyze(load_pnr(other), analysis['clock'], other_names, args.filter)
        print('\n'.join(compare_lines(analysis, second, args.top, f'{note} ({path})', str(other), color)))
    else:
        print('\n'.join(report_lines(analysis, args.top, f'{note} ({path})', color, args.ports)))
        if stages:
            print('\n' + '\n'.join(stage_lines(analysis, prefixes, order, tags, color, args.ports)))
        if args.stage_matrix:
            cones, where, rams = input_cones(netlist, names, args.filter)
            result = stage_matrix(cones, where, rams, endpoint_arrivals(pnr, analysis['clock']),
                                  prefixes, order, tags, args.filter)
            print('\n' + '\n'.join(matrix_lines(result, analysis['period'], args.top, color)))
        if args.cross:
            print('\n' + '\n'.join(cross_lines(analysis, color=color)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
