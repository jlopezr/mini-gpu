#!/usr/bin/env python3
"""BDF -> MiniFont v2. One strike per file, monochrome row-aligned."""
import argparse, struct
from pathlib import Path

HEADER = '<4sHHIIIhhhHhHH6s'  # 40 bytes
HEADER_SIZE = 40
GLYPH = '<IIhhHHhHI'        # 24 bytes

def parse_bdf(path):
    ascent=descent=None; pixel_size=0; res=[72,72]; glyphs=[]; current=None; rows=False
    for raw in Path(path).read_text(encoding='latin1').splitlines():
        line=raw.strip()
        if line.startswith('FONT_ASCENT '): ascent=int(line.split()[1])
        elif line.startswith('FONT_DESCENT '): descent=int(line.split()[1])
        elif line.startswith('PIXEL_SIZE '): pixel_size=int(line.split()[1])
        elif line.startswith('SIZE '):
            parts=list(map(int,line.split()[1:4]))
            if not pixel_size: pixel_size=parts[0]
            if len(parts)==3: res=parts[1:]
        elif line.startswith('RESOLUTION_X '): res[0]=int(line.split()[1])
        elif line.startswith('RESOLUTION_Y '): res[1]=int(line.split()[1])
        elif line.startswith('FONTBOUNDINGBOX ') and ascent is None:
            parts=list(map(int,line.split()[1:])); fallback=(parts[1]+parts[3],-parts[3])
        elif line.startswith('STARTCHAR '): current={'cp':-1,'width':0,'height':0,'bx':0,'by':0,'adv':0,'rows':[]}; rows=False
        elif current is not None:
            if line.startswith('ENCODING '): current['cp']=int(line.split()[1])
            elif line.startswith('DWIDTH '): current['adv']=int(line.split()[1])
            elif line.startswith('BBX '):
                w,h,x,y=map(int,line.split()[1:5]); current.update(width=w,height=h,bx=x,by=y+h)
            elif line=='BITMAP': rows=True
            elif line=='ENDCHAR':
                if current['cp']>=0 and current['cp']<=0x10ffff: glyphs.append(current)
                current=None; rows=False
            elif rows: current['rows'].append(line)
    if ascent is None or descent is None:
        ascent,descent=locals().get('fallback',(pixel_size,0))
    if not 0<=ascent<=32767 or not 0<=descent<=32767 or not 0<=pixel_size<=65535 or not all(0<r<=65535 for r in res): raise ValueError('invalid metrics')
    return ascent,descent,pixel_size,res,glyphs

def convert(src,dst):
    ascent,descent,size,res,entries=parse_bdf(src)
    entries=sorted(entries,key=lambda g:g['cp'])
    if len({g['cp'] for g in entries})!=len(entries): raise ValueError('duplicate Unicode codepoint')
    table=bytearray(); blobs=bytearray()
    for g in entries:
        w,h=g['width'],g['height']; stride=(w+7)//8
        if w<0 or h<0 or len(g['rows'])!=h: raise ValueError('invalid bitmap height')
        data=bytearray()
        for row in g['rows']:
            b=bytes.fromhex(row)
            if len(b)<stride: raise ValueError('short BDF bitmap row')
            data+=b[:stride]
            if w%8 and data[-1]&((1<<(8-w%8))-1): raise ValueError('nonzero padding bits')
        offset=len(blobs); blobs+=data
        table+=struct.pack(GLYPH,g['cp'],offset,g['bx'],g['by'],w,h,g['adv'],0,len(data))
    header=struct.pack(HEADER,b'MFNT',2,0,len(entries),HEADER_SIZE,HEADER_SIZE+len(table),ascent,descent,0,size,0,res[0],res[1],b'\0'*6)
    Path(dst).write_bytes(header+table+blobs)
    print(f'{dst}: {len(entries)} glyphs, {len(header)+len(table)+len(blobs)} bytes')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('bdf');p.add_argument('output');a=p.parse_args();convert(a.bdf,a.output)
