"""Pinta por el monitor una pantalla de prueba de la consola: cajas simples, dobles y mixtas,
sombras, acentos, flechas y linea base (asignacion CP437).

Uso, desde esta carpeta y con la placa programada:
    python console_charset_demo.py [PUERTO]
"""
import sys
from pathlib import Path

PROTO = Path(__file__).resolve().parent
sys.path.insert(0, str(PROTO))
sys.path.insert(0, str(PROTO.parent))
import serial  # noqa: E402
import monitor  # noqa: E402

PALETTE = 0x80201000
CONFIG = 0x80200040
COMMIT = 0x8020000C
TEXT = 0x80206000
W, H = 80, 30

# Glifos de 0x01..0x1F que str.encode('cp437') no da.
LOW = {"☺": 1, "♥": 3, "♦": 4, "♪": 0x0D, "►": 0x10, "◄": 0x11, "▲": 0x1E, "▼": 0x1F,
       "↑": 0x18, "↓": 0x19, "→": 0x1A, "←": 0x1B, "•": 7}


def enc(text):
    return bytes(LOW[c] if c in LOW else c.encode("cp437")[0] for c in text)


screen = [[(0x20, 0x1F)] * W for _ in range(H)]  # blanco sobre azul


def put(x, y, text, attr=0x1F):
    for i, code in enumerate(enc(text)):
        screen[y][x + i] = (code, attr)


def box(x, y, w, h, tl, tr, bl, br, hz, vt, title="", attr=0x1F):
    put(x, y, tl + hz * (w - 2) + tr, attr)
    for r in range(1, h - 1):
        put(x, y + r, vt + " " * (w - 2) + vt, attr)
    put(x, y + h - 1, bl + hz * (w - 2) + br, attr)
    if title:
        put(x + 2, y, " " + title + " ", attr | 0x0E)


put(2, 1, "MiniGPU 30 - consola 80x30 - fuente CP437", 0x1E)
box(2, 3, 24, 6, "┌", "┐", "└", "┘", "─", "│", "simple")
put(4, 5, "Caja simple")
box(28, 3, 24, 6, "╔", "╗", "╚", "╝", "═", "║", "doble")
put(30, 5, "Caja doble")
# Tablas con uniones mixtas
for i, line in enumerate(["╒═══════╤═══════╕", "│ Nombre│ Valor │", "╞═══════╪═══════╡",
                          "│ x     │   10  │", "╘═══════╧═══════╛"]):
    put(54, 3 + i, line)
for i, line in enumerate(["╔═══════╤═══════╗", "║ Nombre│ Valor ║", "╟───────┼───────╢",
                          "║ y     │   20  ║", "╚═══════╧═══════╝"]):
    put(54, 9 + i, line)
for i, line in enumerate(["╓───────╥───────╖", "║ Nombre║ Valor ║", "╠═══════╬═══════╣",
                          "║ z     ║   30  ║", "╙───────╨───────╜"]):
    put(54, 15 + i, line)
put(2, 10, "Sombras y bloques: ░░▒▒▓▓██ ▀▄▌▐ ■")
put(2, 12, "Acentos: á é í ó ú à è ñ Ñ ç Ç ü Ü ä ö ¿ ¡ « »")
put(2, 14, "Flechas: ► ◄ ▲ ▼ ↑ ↓ → ←    Otros: ☺ ♥ ♪ ° ± ≥ ≤ ≈ ∞ π Σ α ß")
put(2, 16, "Linea base: . , ; : _ - g j p q y Q   Cursor: _")
put(2, 18, "ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz 0123456789")
put(2, 19, "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
box(2, 21, 50, 6, "╔", "╗", "╚", "╝", "═", "║", "marco con texto", 0x2F)
put(4, 23, "Uniones: ┌┬┐ ├┼┤ └┴┘  ╔╦╗ ╠╬╣ ╚╩╝", 0x2F)
put(4, 24, "Mixtas: ╒╤╕ ╞╪╡ ╘╧╛  ╓╥╖ ╟╫╢ ╙╨╜", 0x2F)

palette = [0x000000, 0x0000AA, 0x00AA00, 0x00AAAA, 0xAA0000, 0xAA00AA, 0xAA5500, 0xAAAAAA,
           0x555555, 0x5555FF, 0x55FF55, 0x55FFFF, 0xFF5555, 0xFF55FF, 0xFFFF55, 0xFFFFFF]

port = sys.argv[1] if len(sys.argv) > 1 else monitor.detect_port()
with serial.Serial(port=port, baudrate=monitor.BAUDRATE, timeout=2.0, write_timeout=2.0) as conn:
    client = monitor.MonitorClient(conn)
    for i, color in enumerate(palette):
        client.write_word(PALETTE + 4 * i, color)
    for y in range(H):
        for x in range(W):
            code, attr = screen[y][x]
            fg, bg = attr & 0x0F, attr >> 4
            client.write_word(TEXT + 4 * (y * W + x), (bg << 12) | (fg << 8) | code)
    client.write_word(CONFIG, 4)      # TEXT_ENABLE
    client.write_word(COMMIT, 2)      # STATE_COMMIT
    for _ in range(100):
        if client.read_word(COMMIT) == 0:
            break
print("pantalla de prueba escrita")

