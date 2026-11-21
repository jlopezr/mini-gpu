"""Modelo funcional (no de ciclos) del ROP de la CPU.

Los trabajos se encolan con una instantánea de P0..P9/PMODE y se consumen
entre instrucciones de CPU. Conserva el orden y los errores asíncronos; no
modela el fabric ni sus latencias.
"""

MASK32 = 0xffffffff
ROP_DEPTH = 16


def s32(value):
    value &= MASK32
    return value - (1 << 32) if value & 0x80000000 else value


class Rop:
    # Codon only infers fields assigned directly in __init__, not in reset().
    params: list[int]
    mode: int
    queue: list[tuple[int, int, list[int]]]
    sticky_error: bool
    config: list[int]
    config_written: int

    def __init__(self):
        self.reset()

    def reset(self):
        self.params = [0] * 10
        self.mode = 0
        self.queue = []
        self.sticky_error = False
        self.config = [0] * 9
        self.config_written = 0

    def set_pair(self, ia, a, ib, b):
        if ia != 15:
            if ia == 10:
                self.mode = a & 0xffff
            else:
                self.params[ia] = a & MASK32
        if ib != 15:
            if ib == 10:
                self.mode = b & 0xffff
            else:
                self.params[ib] = b & MASK32

    def submit(self, op, ia, a, ib, b):
        self.set_pair(ia, a, ib, b)
        if len(self.queue) < ROP_DEPTH:
            self.queue.append((op, self.mode, self.params[:]))

    def status(self):
        return ((ROP_DEPTH - len(self.queue)) << 8) | (4 if self.sticky_error else 0) | (1 if self.queue else 0)

    def tick(self, cpu):
        if not self.queue:
            return
        op, mode, p = self.queue.pop(0)
        try:
            self._execute(cpu, op, mode, p)
        except RuntimeError:
            self.sticky_error = True
        except ValueError:
            self.sticky_error = True
        except IndexError:
            self.sticky_error = True

    def drain(self, cpu):
        while self.queue:
            self.tick(cpu)

    def _read(self, cpu, address, size):
        if size == 2:
            return cpu.read_sub(address, 2)
        return cpu.read_u32(address)

    def _write(self, cpu, address, size, value):
        if size == 2:
            cpu.write_sub(address, 2, value)
        else:
            cpu.write_u32(address, value)

    def _execute(self, cpu, op, mode, p):
        if op == 0:  # FILL
            if not p[1] or not p[2] or any(x & 15 for x in (p[0], p[1], p[3])):
                raise ValueError()
            for row in range(p[2]):
                start = p[0] + row * p[3]
                for column in range(0, p[1], 4):
                    cpu.write_u32(start + column, p[4])
        elif op == 1:  # COPY
            if not p[2] or not p[3] or any(x & 15 for x in (p[0], p[1], p[2], p[4], p[5])):
                raise ValueError()
            for row in range(p[3]):
                src = p[0] + row * p[4]
                dst = p[1] + row * p[5]
                cpu.memory[dst:dst + p[2]] = cpu.memory[src:src + p[2]]
        elif op == 3:  # SPAN explícito o compacto sobre CONFIG
            compact = mode & 0x1000
            if compact:
                # En compacto solo [12:8] tiene significado: los cuatro
                # overrides y el bit COMPACT. P8/P9 quedan reservados.
                if mode & ~0x1f00 or self.config_written != 0x1f or p[8] or p[9]:
                    raise ValueError()
                render_mode = self.config[8]
                color, z = self.config[0] + p[0], self.config[1] + p[1]
                cstride, zstride = self.config[2], self.config[3]
                value = p[4] if mode & 0x0100 else self.config[4]
                initial = p[5] if mode & 0x0200 else self.config[5]
                dx = p[6] if mode & 0x0400 else self.config[6]
                dy = p[7] if mode & 0x0800 else self.config[7]
            else:
                if mode & 0xd000:
                    raise ValueError()
                render_mode = mode
                color, z = p[0], p[1]
                cstride, zstride = p[4], p[5]
                value, initial, dx, dy = p[6], p[7], p[8], p[9]
            if (render_mode & 0xc000 or render_mode & 0x1000 or not p[2] or not p[3] or
                    not (render_mode & 0x60) or (render_mode & 7) == 7 or
                    ((render_mode & 0x2000) and ((render_mode & 0x10) or (render_mode & 0x80)))):
                raise ValueError()
            csize, zsize = (4 if render_mode & 8 else 2), (4 if render_mode & 16 else 2)
            if color % csize or z % zsize:
                raise ValueError()
            for row in range(p[3]):
                for col in range(p[2]):
                    zraw = (initial + col * dx + row * dy) & MASK32
                    shifted = s32(zraw) >> ((render_mode >> 8) & 15)
                    if zsize == 2 and render_mode & 0x2000:
                        newz = max(0, min(0xffff, shifted))
                    else:
                        newz = shifted & ((1 << (8 * zsize)) - 1)
                    za = z + row * zstride + col * zsize
                    ca = color + row * cstride + col * csize
                    old = self._read(cpu, za, zsize)
                    a = s32(newz) if render_mode & 0x80 and zsize == 4 else (newz ^ (0x8000 if render_mode & 0x80 else 0) if zsize == 2 else newz)
                    b = s32(old) if render_mode & 0x80 and zsize == 4 else (old ^ (0x8000 if render_mode & 0x80 else 0) if zsize == 2 else old)
                    cmp = render_mode & 7
                    passed = (cmp == 0 or (cmp == 1 and a == b) or (cmp == 2 and a != b) or
                              (cmp == 3 and a < b) or (cmp == 4 and a <= b) or
                              (cmp == 5 and a > b) or (cmp == 6 and a >= b))
                    if passed:
                        if render_mode & 0x20: self._write(cpu, za, zsize, newz)
                        if render_mode & 0x40: self._write(cpu, ca, csize, value)
        elif op == 5:  # CONFIG
            if mode & ~31 or not mode:
                raise ValueError()
            groups = [[0, 1], [2, 3], [4], [5, 6, 7], [8]]
            for bit, indices in enumerate(groups):
                if mode & (1 << bit):
                    for i in indices: self.config[i] = p[i]
                    self.config_written |= 1 << bit
        else:
            raise ValueError()
