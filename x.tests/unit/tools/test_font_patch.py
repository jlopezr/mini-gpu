"""Parcheo de la fuente de la consola (`tools/font_patch.py`): sin placa ni build reales.

Lo que se comprueba, sobre un `.config` sintetico con cuatro EBR de fuente:

  - el reparto de bits (bit b -> porcion b div 36, posicion b mod 36);
  - que `locate` solo reconoce la fuente que el config lleva de verdad;
  - que `rewrite` cambia unicamente las lineas de los cuatro EBR y conserva el
    final de linea (el .config de nextpnr usa CRLF), y que ida y vuelta es exacta.
"""

import random
import tempfile
import unittest
from pathlib import Path

from tools.font_patch import (FontPatchError, GLYPHS, LINES_PER_FONT, SLICES,
                              encode, load_font, locate, rewrite)

FONT_EBRS = {0: 12, 1: 11, 2: 10, 3: 9}  # porcion -> EBR, como en el build real


def random_font(seed):
    rng = random.Random(seed)
    return [rng.getrandbits(128) for _ in range(GLYPHS)]


def fake_config(font, eol="\r"):
    lines = [".device LFE5U-85F" + eol, ""]
    lines += [f".bram_init 3{eol}"] + ["000 " * 8 + eol for _ in range(256)]
    for slice_index, ebr in FONT_EBRS.items():
        tokens = encode(font, slice_index)
        lines.append(f".bram_init {ebr}{eol}")
        lines += ["".join(f"{t:03x} " for t in tokens[8 * row:8 * row + 8]) + eol
                  for row in range(LINES_PER_FONT)]
        lines += ["000 " * 8 + eol for _ in range(256 - LINES_PER_FONT)]
        lines.append("")
    lines.append(".comment end" + eol)
    return lines


class EncodeTest(unittest.TestCase):
    def test_bit_layout(self):
        font = [0] * GLYPHS
        font[0] = 1            # bit 0 -> porcion 0, posicion 0
        font[1] = 1 << 36      # bit 36 -> porcion 1, posicion 0
        font[2] = 1 << 127     # bit 127 -> porcion 3, posicion 19
        self.assertEqual(encode(font, 0)[0], 1)
        # Direccion 1 = bits 36..71 de la palabra: tokens 4..7 de la fila.
        self.assertEqual(encode(font, 1)[4], 1)
        flat_index = 2 * 36 + 19
        self.assertEqual(encode(font, 3)[flat_index // 9], 1 << (flat_index % 9))

    def test_token_count(self):
        self.assertEqual(len(encode(random_font(1), 0)), GLYPHS * 36 // 9)

    def test_bits_beyond_glyph_are_zero(self):
        # La porcion 3 solo tiene 20 bits utiles: el resto de la palabra es cero.
        tokens = encode([(1 << 128) - 1] * GLYPHS, 3)
        for glyph in range(GLYPHS):
            bits = [(tokens[(36 * glyph + p) // 9] >> ((36 * glyph + p) % 9)) & 1 for p in range(36)]
            self.assertEqual(bits, [1] * 20 + [0] * 16)


class LocateTest(unittest.TestCase):
    def test_finds_the_font_it_carries(self):
        a, b = random_font(1), random_font(2)
        lines = fake_config(a)
        self.assertEqual(locate(lines, a), FONT_EBRS)
        self.assertIsNone(locate(lines, b))

    def test_font_differing_in_one_bit_is_not_found(self):
        a = random_font(1)
        b = list(a)
        b[200] ^= 1 << 77
        self.assertIsNone(locate(fake_config(a), b))


class RewriteTest(unittest.TestCase):
    def test_rewrite_swaps_only_font_lines(self):
        a, b = random_font(1), random_font(2)
        lines = fake_config(a)
        patched = rewrite(lines, FONT_EBRS, b)
        self.assertEqual(locate(patched, b), FONT_EBRS)
        self.assertIsNone(locate(patched, a))
        changed = [i for i, (x, y) in enumerate(zip(lines, patched)) if x != y]
        self.assertTrue(changed)
        self.assertEqual(len(patched), len(lines))
        self.assertTrue(all(patched[i].endswith(" \r") for i in changed))
        self.assertEqual(patched[0], lines[0])
        self.assertEqual(patched[-1], lines[-1])

    def test_round_trip_is_exact(self):
        a, b = random_font(1), random_font(2)
        lines = fake_config(a)
        self.assertEqual(rewrite(rewrite(lines, FONT_EBRS, b), FONT_EBRS, a), lines)

    def test_unrelated_ebr_is_untouched(self):
        a, b = random_font(1), random_font(2)
        lines = fake_config(a)
        patched = rewrite(lines, FONT_EBRS, b)
        self.assertEqual(patched[2:2 + 257], lines[2:2 + 257])  # EBR 3


class LoadFontTest(unittest.TestCase):
    def test_wrong_length_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "short.hex"
            path.write_text("00\n" * 10)
            with self.assertRaises(FontPatchError):
                load_font(path)

    def test_reads_hex_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.hex"
            path.write_text("\n".join(f"{i:032x}" for i in range(GLYPHS)) + "\n")
            self.assertEqual(load_font(path)[255], 255)


if __name__ == "__main__":
    unittest.main()
