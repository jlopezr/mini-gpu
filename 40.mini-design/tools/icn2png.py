#!/usr/bin/env python3
"""Extract NewsMaster NEWS.ICN icons; retain original 40x20, optionally correct aspect."""
import argparse
import struct
from pathlib import Path
from PIL import Image, ImageDraw


def extract(path):
    data = Path(path).read_bytes()
    offset = 0
    images = []
    while offset < len(data):
        if offset + 4 > len(data):
            raise ValueError('Truncated ICN header')
        width, height = struct.unpack_from('<HH', data, offset)
        if not (0 < width <= 4096 and 0 < height <= 4096):
            raise ValueError(f'Invalid ICN dimensions at {offset}')
        row_bytes = (width + 7)//8
        end = offset + 4 + row_bytes * height
        if end > len(data):
            raise ValueError('Truncated ICN bitmap')
        bitmap = data[offset+4:end]
        image = Image.new('1', (width,height), 1)
        for y in range(height):
            for x in range(width):
                # ICN: zero bit = black, one bit = white
                if not (bitmap[y * row_bytes + x // 8] & (0x80 >> (x % 8))):
                    image.putpixel((x,y),0)
        images.append(image)
        offset = end
    return images


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('icn', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--correct-aspect', action='store_true', help='Produce 40x40 (or corresponding) square-pixel images in corrected/; originals remain unchanged')
    p.add_argument('--scale', type=int, default=2, help='Catalogue scale, default 2 horizontally, 4 vertically')
    args = p.parse_args()
    if args.scale < 1:
        p.error('--scale must be >= 1')
    images = extract(args.icn)
    args.output.mkdir(parents=True, exist_ok=True)
    corrected = args.output/'corrected'
    if args.correct_aspect:
        corrected.mkdir(exist_ok=True)
    cols = 8
    cell_w = max(im.width for im in images)*args.scale+20
    cell_h = max(im.height for im in images)*args.scale*2+28
    rows = (len(images)+cols-1)//cols
    sheet = Image.new('RGB', (cols*cell_w,rows*cell_h),'white')
    d = ImageDraw.Draw(sheet)
    for i, im in enumerate(images):
        im.save(args.output/f'icon_{i:02}.png')
        if args.correct_aspect:
            im.resize((im.width,im.height*2),Image.Resampling.NEAREST).save(corrected/f'icon_{i:02}.png')
        scaled = im.resize((im.width*args.scale, im.height*args.scale*2), Image.Resampling.NEAREST)
        x, y = i%cols*cell_w, i//cols*cell_h
        sheet.paste(scaled.convert('RGB'), (x+(cell_w-scaled.width)//2,y+3))
        d.text((x+6,y+cell_h-19),f'{i:02}',fill='black')
    sheet.save(args.output/'catalog.png')
    print(f'Extracted {len(images)} icons to {args.output}')


if __name__ == '__main__':
    main()
