"""Tests de regresión para FLB solo si se dispone del fichero original."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import flb2mf

source=Path(sys.argv[1])
data=source.read_bytes()
fonts=flb2mf.catalogue(data)
assert len(fonts)==34
park=flb2mf.decode(data,fonts[0])
a=next(g for g in park if g['cp']==65)
assert (a['w'],a['h'])==(11,8)
assert [''.join('#' if x else '.' for x in row) for row in a['rows']] == [
 '....###....','...##.##...','..##...##..','..##...##..',
 '.##.....##.','.#########.','##.......##','##.......##']
assert sum(1 for f in fonts if not f['name'].startswith('glyphs'))==30
# Campos del registro, medidos en capturas de NewsMaster: espaciado (+80),
# interlineado extra (+82) y ancho del espacio (+84) son por fuente.
by_name={f['name']:f for f in fonts}
assert [by_name['park 10'][k] for k in ('spacing','leading','space','size','x_height')]==[2,1,5,10,6]
assert [by_name['park 24'][k] for k in ('spacing','leading','space','size')]==[2,3,11,24]
assert (by_name['news 10']['spacing'],by_name['twig']['spacing'])==(1,3)
for f in fonts:
 if f['name'].startswith('glyphs'):continue
 assert (f['res_x'],f['res_y'])==(120,72)
 glyphs=flb2mf.decode(data,f)
 assert len(glyphs)==f['last']-f['first']+1
 assert f['size']==f['ascent']+f['descent']==max(g['by'] for g in glyphs)+max(g['h']-g['by'] for g in glyphs)
print('FLB checks passed: 30 regular fonts at 120x72 dpi, Park 10 A verified, metrics per font')
