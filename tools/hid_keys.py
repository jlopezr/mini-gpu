"""Nombres de tecla y Usage IDs HID (Usage Page 0x07) para INPUT.

INPUT identifica teclas físicas por su Usage ID (`1.isa/mmio.md` §25.1). Este
módulo es la única tabla del repositorio entre nombres legibles y esos códigos:
la usan los guiones de entrada (`tools/input_script.py`) y, más adelante, la
traducción de las teclas del anfitrión.

`ASCII_US` da, para cada carácter imprimible, la tecla y si lleva Shift en un
teclado US. El contrato no define layouts --son política del software--; esto
es solo comodidad para escribir texto en un guion.
"""

KEY_NAMES: dict[str, int] = {}


def _add(name: str, usage: int) -> None:
    KEY_NAMES[name] = usage


for _i, _letter in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _add(_letter, 0x04 + _i)
for _i, _digit in enumerate("1234567890"):
    _add(_digit, 0x1E + _i)
for _name, _usage in (
        ("ENTER", 0x28), ("ESC", 0x29), ("BACKSPACE", 0x2A), ("TAB", 0x2B),
        ("SPACE", 0x2C), ("MINUS", 0x2D), ("EQUAL", 0x2E), ("LBRACKET", 0x2F),
        ("RBRACKET", 0x30), ("BACKSLASH", 0x31), ("SEMICOLON", 0x33),
        ("QUOTE", 0x34), ("GRAVE", 0x35), ("COMMA", 0x36), ("DOT", 0x37),
        ("SLASH", 0x38), ("CAPSLOCK", 0x39), ("PRINTSCREEN", 0x46),
        ("SCROLLLOCK", 0x47), ("PAUSE", 0x48), ("INSERT", 0x49), ("HOME", 0x4A),
        ("PAGEUP", 0x4B), ("DELETE", 0x4C), ("END", 0x4D), ("PAGEDOWN", 0x4E),
        ("RIGHT", 0x4F), ("LEFT", 0x50), ("DOWN", 0x51), ("UP", 0x52),
        ("NUMLOCK", 0x53), ("KP_SLASH", 0x54), ("KP_STAR", 0x55),
        ("KP_MINUS", 0x56), ("KP_PLUS", 0x57), ("KP_ENTER", 0x58),
        ("KP_DOT", 0x63),
        ("LCTRL", 0xE0), ("LSHIFT", 0xE1), ("LALT", 0xE2), ("LGUI", 0xE3),
        ("RCTRL", 0xE4), ("RSHIFT", 0xE5), ("RALT", 0xE6), ("RGUI", 0xE7)):
    _add(_name, _usage)
for _i in range(12):
    _add(f"F{_i + 1}", 0x3A + _i)
for _i in range(9):
    _add(f"KP{_i + 1}", 0x59 + _i)
_add("KP0", 0x62)

MODIFIER_FIRST = 0xE0
MODIFIER_LAST = 0xE7

_NAME_OF = {usage: name for name, usage in reversed(list(KEY_NAMES.items()))}


def usage_of(name: str) -> int:
    """Usage ID de un nombre (`A`, `ENTER`, `LSHIFT`...) o de un literal numérico."""
    key = name.strip().upper()
    if key in KEY_NAMES:
        return KEY_NAMES[key]
    try:
        usage = int(key, 0)
    except ValueError:
        raise ValueError(f"tecla desconocida: {name!r}") from None
    if not 1 <= usage <= 0xFF:
        raise ValueError(f"Usage ID fuera de rango (1..255): {name!r}")
    return usage


def name_of(usage: int) -> str:
    """Nombre de un Usage ID, o su valor en hexadecimal si no tiene."""
    return _NAME_OF.get(usage, f"0x{usage:02X}")


# Carácter -> (nombre de tecla, con Shift). Teclado US, solo ASCII imprimible
# más Enter y Tab.
ASCII_US: dict[str, tuple[str, bool]] = {" ": ("SPACE", False),
                                         "\n": ("ENTER", False),
                                         "\t": ("TAB", False)}
for _letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    ASCII_US[_letter.lower()] = (_letter, False)
    ASCII_US[_letter] = (_letter, True)
for _digit, _shifted in zip("1234567890", "!@#$%^&*()"):
    ASCII_US[_digit] = (_digit, False)
    ASCII_US[_shifted] = (_digit, True)
for _plain, _shifted, _name in (("-", "_", "MINUS"), ("=", "+", "EQUAL"),
                                ("[", "{", "LBRACKET"), ("]", "}", "RBRACKET"),
                                ("\\", "|", "BACKSLASH"), (";", ":", "SEMICOLON"),
                                ("'", '"', "QUOTE"), ("`", "~", "GRAVE"),
                                (",", "<", "COMMA"), (".", ">", "DOT"),
                                ("/", "?", "SLASH")):
    ASCII_US[_plain] = (_name, False)
    ASCII_US[_shifted] = (_name, True)


def keystrokes(text: str):
    """Pulsaciones (lista de nombres a pulsar a la vez) que teclean `text`."""
    strokes = []
    for char in text:
        if char not in ASCII_US:
            raise ValueError(f"carácter no tecleable en un teclado US: {char!r}")
        name, shift = ASCII_US[char]
        strokes.append(["LSHIFT", name] if shift else [name])
    return strokes
