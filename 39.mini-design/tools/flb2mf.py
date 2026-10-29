#!/usr/bin/env python3
"""NewsMaster 1.5 FLB -> MiniFont v1 and PNG glyph contact sheet.
Only covers the confirmed 34-font library layout; character mapping is assumed
ASCII for table indices 33..126 (127 in Bremen). Originals are not bundled.
"""
import argparse
import struct
from pathlib import Path

HEADER = '<4sHHIIIhhhH4s'
GLYPH = '<IIhhHHhHI'

def catalogue(data):
    if len(data) < 10: raise ValueError('file too short')
    count = struct.unpack_from('<H', data, 2)[0]
    start = struct.unpack_from('<I', data, 6)[0]
    if count != 34 or start != 3132:
        raise ValueError('not a recognized NewsMaster 1.5 library')
    entries=[]; pos=start
    for i in range(count):
        p=10+i*92
        name=data[p:p+52].split(b'\0')[0].decode('latin-1')
        a,t,b,first,last=struct.unpack_from('<IIIHH',data,p+52)
        if first>last or t!=(last-first+1)*16 or pos+a+t+b>len(data):
            raise ValueError(f'bad font record {i}')
        entries.append(dict(index=i,name=name,base=pos,atlas=a,table=t,bitmap=b,first=first,last=last))
        pos+=a+t+b
    if pos!=len(data): raise ValueError('trailing or missing bytes')
    return entries

def decode(data,font):
    tab=font['base']+font['atlas']; bitbase=tab+font['table']; size=font['bitmap']
    decoded=[]
    for cp in range(font['first'],font['last']+1):
        values=struct.unpack_from('<8H',data,tab+(cp-font['first'])*16)
        bx,w,h,by,adv,other,lo,hi=values
        off=lo+(hi<<16)
        rowsize=(w+7)//8
        if off+rowsize*h>size: raise ValueError(f'char {cp}: bitmap outside font')
        raw=data[bitbase+off:bitbase+off+rowsize*h]
        rows=[]
        for y in range(h):
            v=raw[y*rowsize:(y+1)*rowsize]
            rows.append([1 if v[x//8] & (0x80>>(x%8)) else 0 for x in range(w)])
        # left offset field likely signed; validated samples have zero
        if bx>=32768: bx-=65536
        if by>=32768: by-=65536
        if adv>=32768: adv-=65536
        decoded.append(dict(cp=cp,w=w,h=h,bx=bx,by=by,advance=adv,rows=rows,raw_descriptor=values))
    return decoded

def export_mf(glyphs,path):
    table=bytearray(); bitmaps=bytearray()
    for g in glyphs:
        stride=(g['w']+7)//8; blob=bytearray()
        for row in g['rows']:
            for at in range(0,len(row),8):
                chunk=row[at:at+8]
                blob.append(sum(v<<(7-i) for i,v in enumerate(chunk)))
        assert len(blob)==stride*g['h']
        table.extend(struct.pack(GLYPH,g['cp'],len(bitmaps),g['bx'],g['by'],g['w'],g['h'],g['advance'],0,len(blob)))
        bitmaps.extend(blob)
    ascent=max((g['by'] for g in glyphs),default=0)
    descent=max((g['h']-g['by'] for g in glyphs),default=0)
    nominal=ascent+descent
    header=struct.pack(HEADER,b'MFNT',1,0,len(glyphs),32,32+len(table),ascent,descent,0,nominal,b'\0'*4)
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_bytes(header+table+bitmaps)

def sheet(glyphs, path, scale=3, cols=10):
    """Render glyphs at a common baseline in dynamically sized cells.

    No glyph is resized independently. Each cell reserves space for the
    largest bearings and dimensions encountered in the selected font.
    """
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise SystemExit('PNG sheet needs Pillow: python3 -m pip install pillow') from exc
    if not glyphs:
        raise ValueError('empty font')
    if scale < 1 or cols < 1:
        raise ValueError('scale and columns must be positive')

    # Pixel extents relative to the pen origin and the baseline.
    left = min(0, *(g['bx'] for g in glyphs))
    right = max(0, *(g['bx'] + g['w'] for g in glyphs))
    above = max(0, *(g['by'] for g in glyphs))
    below = max(0, *(g['h'] - g['by'] for g in glyphs))
    pad = 8
    label_h = 18
    cellw = max(74, (right-left)*scale + pad*2)
    cellh = label_h + (above+below)*scale + pad*2
    rows = (len(glyphs) + cols - 1)//cols
    image = Image.new('RGB', (cols*cellw, rows*cellh), '#fbfbfb')
    draw = ImageDraw.Draw(image)
    for k, g in enumerate(glyphs):
        ox = (k%cols)*cellw
        oy = (k//cols)*cellh
        draw.rectangle((ox, oy, ox+cellw-1, oy+cellh-1), outline='#cccccc')
        label = chr(g['cp']) if 33 <= g['cp'] <= 126 else '?'
        draw.text((ox+4, oy+3), f"{g['cp']:03d} {label}", fill='#182735')
        baseline = oy + label_h + pad + above*scale
        x0 = ox + pad + (g['bx'] - left)*scale
        y0 = baseline - g['by']*scale
        # The bottom border is outside the font's reserved vertical extent.
        for y, row in enumerate(g['rows']):
            for x, on in enumerate(row):
                if on:
                    xx, yy = x0+x*scale, y0+y*scale
                    draw.rectangle((xx, yy, xx+scale-1, yy+scale-1), fill='#182735')
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    image.save(path)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('flb');p.add_argument('--list',action='store_true');p.add_argument('--font',default='park 10')
    p.add_argument('--output',help='MiniFont .mf output');p.add_argument('--sheet',help='PNG contact sheet')
    p.add_argument('--sheet-scale',type=int,default=3,help='pixel scale in sheet (default: 3)')
    p.add_argument('--sheet-cols',type=int,default=10,help='sheet columns (default: 10)')
    p.add_argument('--all',metavar='DIR',help="export every regular font to DIR/<name>.mf ('glyphs' libraries are skipped)")
    p.add_argument('--sheets',action='store_true',help='with --all, also write DIR/<name>.png')
    a=p.parse_args();data=Path(a.flb).read_bytes(); fonts=catalogue(data)
    if a.list:
        for f in fonts:print(f"{f['index']:2d}: {f['name']:18} ASCII {f['first']}..{f['last']}")
        return
    if a.all:
        out=Path(a.all);out.mkdir(parents=True,exist_ok=True);n=0
        for f in fonts:
            if f['name'].startswith('glyphs'):continue
            glyphs=decode(data,f);stem=f['name'].replace(' ','')
            export_mf(glyphs,out/f'{stem}.mf');n+=1
            if a.sheets:sheet(glyphs,out/f'{stem}.png',a.sheet_scale,a.sheet_cols)
        print(f"Extracted {n} fonts -> {out}/");return
    matches=[f for f in fonts if f['name'].lower()==a.font.lower()]
    if len(matches)!=1:raise SystemExit('font not found or ambiguous; use --list')
    glyphs=decode(data,matches[0]);out=a.output or f"{a.font.replace(' ','_')}.mf"
    export_mf(glyphs,out);print(f"Extracted {len(glyphs)} glifos: {a.font} -> {out}")
    if a.sheet:sheet(glyphs,a.sheet,a.sheet_scale,a.sheet_cols);print('Contact sheet:',a.sheet)
if __name__=='__main__':main()
