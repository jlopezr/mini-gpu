#!/usr/bin/env python3
"""Extract NewsMaster 1.5 SHP/SDX/SDR monochrome clipart into PNG."""
import argparse
import csv
import struct
from pathlib import Path
from PIL import Image, ImageDraw


def extract(shp_path, sdx_path, sdr_path):
    shp = Path(shp_path).read_bytes()
    idx = Path(sdx_path).read_bytes()
    names = Path(sdr_path).read_bytes()
    if len(idx) % 4 or not idx:
        raise ValueError('SDX must contain 32-bit little-endian offsets')
    offsets = [x[0] for x in struct.iter_unpack('<I', idx)]
    if offsets[0] != 0 or any(a >= b for a, b in zip(offsets, offsets[1:])):
        raise ValueError('Invalid SHP offset table')
    if len(names) != 16 * len(offsets):
        raise ValueError('SDR must contain one 16-byte record per image')
    result = []
    for i, start in enumerate(offsets):
        end = offsets[i + 1] if i + 1 < len(offsets) else len(shp)
        if start + 5 > end or end > len(shp):
            raise ValueError(f'Invalid shape offset {i}')
        row_bytes, height, width = struct.unpack_from('<BBH', shp, start)
        if not width or not height or row_bytes < (width + 7) // 8:
            raise ValueError(f'Invalid shape dimensions {i}')
        payload_end = start + 4 + row_bytes * height
        if payload_end + 1 != end:
            raise ValueError(f'Unexpected shape record length {i}')
        bits = shp[start + 4:payload_end]
        image = Image.new('1', (width, height), 1)
        for y in range(height):
            for x in range(width):
                if bits[y * row_bytes + x // 8] & (0x80 >> (x % 8)):
                    image.putpixel((x, y), 0)
        name = names[i * 16:(i + 1) * 16].split(b'\0', 1)[0].decode('cp437', errors='replace')
        result.append((name, image))
    return result


def catalog(items, target, columns=6):
    from math import ceil
    width, height = 180, 155
    sheet = Image.new('RGB', (columns * width, ceil(len(items)/columns) * height), 'white')
    d = ImageDraw.Draw(sheet)
    for i, (name, im) in enumerate(items):
        ox, oy = (i % columns) * width, (i // columns) * height
        sample = im.copy()
        sample.thumbnail((width - 14, height - 34), Image.Resampling.NEAREST)
        sheet.paste(sample.convert('RGB'), (ox + (width - sample.width)//2, oy + 5))
        d.text((ox + 6, oy + height - 21), f'{i:03} {name}'[:28], fill='black')
    sheet.save(target)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('shp', type=Path)
    p.add_argument('sdx', type=Path)
    p.add_argument('sdr', type=Path)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    items = extract(args.shp, args.sdx, args.sdr)
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output/'catalog.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['index','name','width','height','filename'])
        for i, (name, im) in enumerate(items):
            filename = f'shp_{i:03}.png'
            im.save(args.output/filename)
            w.writerow([i,name,*im.size,filename])
    catalog(items, args.output/'catalog.png')
    print(f'Extracted {len(items)} shapes to {args.output}')


if __name__ == '__main__':
    main()
