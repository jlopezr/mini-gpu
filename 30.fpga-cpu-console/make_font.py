"""Genera una imagen EBR de 256 glifos 8x16.

Sin ``--ttf`` usa la fuente incluida en Pillow (perfil PC/CP437). Con una TTF
8x8 y ``--double-rows`` conserva el bitmap y duplica cada fila a 8x16.
"""
import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

parser = argparse.ArgumentParser()
parser.add_argument("--ttf", type=Path)
parser.add_argument("--output", type=Path, default=Path("fonts/font8x16_pc.hex"))
parser.add_argument("--encoding", default="cp437")
parser.add_argument("--double-rows", action="store_true")
args = parser.parse_args()

font = ImageFont.truetype(args.ttf, 8) if args.ttf else ImageFont.load_default(size=14)
rows = []
for code in range(256):
    source_height = 8 if args.double_rows else 16
    image = Image.new("1", (8, source_height), 0)
    draw = ImageDraw.Draw(image)
    try:
        char = bytes([code]).decode(args.encoding)
    except UnicodeDecodeError:
        char = " "
    box = draw.textbbox((0, 0), char, font=font)
    width, height = box[2] - box[0], box[3] - box[1]
    x = (8 - width) // 2 - box[0]
    y = (source_height - height) // 2 - box[1]
    draw.text((x, y), char, font=font, fill=1)
    packed = 0
    for gy in range(16):
        source_y = gy // 2 if args.double_rows else gy
        byte = 0
        for gx in range(8):
            byte |= int(image.getpixel((gx, source_y)) != 0) << (7 - gx)
        packed |= byte << (gy * 8)
    rows.append(f"{packed:032x}")

args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text("\n".join(rows) + "\n")
