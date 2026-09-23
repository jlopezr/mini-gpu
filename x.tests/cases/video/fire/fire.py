from pathlib import Path
import argparse


WIDTH = 64
HEIGHT = 120
DECAY = 2
MASK32 = 0xFFFFFFFF


class Fire:
    def __init__(self, width=WIDTH, height=HEIGHT, decay=DECAY):
        self.width = width
        self.height = height
        self.decay = decay
        self.rng = 0x2545F491
        self.current = bytearray(width * height)
        self.next = bytearray(width * height)

    def random32(self):
        self.rng ^= (self.rng << 13) & MASK32
        self.rng ^= self.rng >> 17
        self.rng ^= (self.rng << 5) & MASK32
        self.rng &= MASK32
        return self.rng

    def generate_source(self):
        base = (self.height - 1) * self.width
        for x in range(self.width):
            value = self.random32() & 0xFF
            self.current[base + x] = value if value > 80 else 0

    def step(self):
        self.generate_source()

        for y in range(self.height - 1):
            src = (y + 1) * self.width
            dst = y * self.width

            for x in range(self.width):
                left = self.current[src + max(0, x - 1)]
                center = self.current[src + x]
                right = self.current[src + min(self.width - 1, x + 1)]

                heat = (left + center + center + right) // 4
                self.next[dst + x] = max(0, heat - self.decay)

        bottom = (self.height - 1) * self.width
        self.next[bottom:bottom + self.width] = \
            self.current[bottom:bottom + self.width]

        self.current, self.next = self.next, self.current

    def write_pgm(self, path):
        with Path(path).open("wb") as output:
            output.write(f"P5\n{self.width} {self.height}\n255\n".encode())
            output.write(self.current)

    @staticmethod
    def rgb565(heat):
        if heat < 64:
            red, green, blue = heat >> 1, 0, 0
        elif heat < 192:
            red, green, blue = 31, (heat - 64) >> 1, 0
        else:
            red, green, blue = 31, 63, (heat - 192) >> 1
        return (red << 11) | (green << 5) | blue

    def render_rgb565(self):
        """Devuelve el mismo framebuffer 320x240 que genera fire.asm."""
        frame = bytearray()
        for y in range(self.height):
            row = bytearray()
            base = y * self.width
            for heat in self.current[base:base + self.width]:
                row.extend(self.rgb565(heat).to_bytes(2, "little") * 5)
            frame.extend(row)
            frame.extend(row)
        return bytes(frame)

    def write_rgb565(self, path):
        Path(path).write_bytes(self.render_rgb565())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=1)
    parser.add_argument("--output", default="fire.pgm")
    parser.add_argument("--rgb565-output",
                        help="framebuffer RGB565 320x240 para comparar con el simulador")
    args = parser.parse_args()

    fire = Fire()

    for _ in range(args.frames):
        fire.step()

    fire.write_pgm(args.output)
    if args.rgb565_output:
        fire.write_rgb565(args.rgb565_output)


if __name__ == "__main__":
    main()
