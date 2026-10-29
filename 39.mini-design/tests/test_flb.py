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
for f in fonts:
 if f['name'].startswith('glyphs'):continue
 assert len(flb2mf.decode(data,f))==f['last']-f['first']+1
print('FLB checks passed: 30 regular fonts, Park 10 A verified')
