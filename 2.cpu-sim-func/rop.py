"""Modelo funcional (no de ciclos) del ROP de la CPU.

Los trabajos se encolan con una instantánea de P0..P9/PMODE y se consumen
entre instrucciones de CPU. Conserva el orden y los errores asíncronos; no
modela el fabric ni sus latencias.
"""

MASK32 = 0xffffffff


def s32(value):
    value &= MASK32
    return value - (1 << 32) if value & 0x80000000 else value


class Rop:
    DEPTH = 16

    def __init__(self, cpu):
        self.cpu = cpu
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
        if len(self.queue) < self.DEPTH:
            self.queue.append((op, self.mode, self.params[:]))

    def status(self):
        return ((self.DEPTH - len(self.queue)) << 8) | (4 if self.sticky_error else 0) | (1 if self.queue else 0)

    def tick(self):
        if not self.queue:
            return
        op, mode, p = self.queue.pop(0)
        try:
            self._execute(op, mode, p)
        except (RuntimeError, ValueError, IndexError):
            self.sticky_error = True

    def drain(self):
        while self.queue:
            self.tick()

    def _read(self, address, size):
        if size == 2:
            return self.cpu.read_sub(address, 2)
        return self.cpu.read_u32(address)

    def _write(self, address, size, value):
        if size == 2:
            self.cpu.write_sub(address, 2, value)
        else:
            self.cpu.write_u32(address, value)

    def _execute(self, op, mode, p):
        if op == 0:  # FILL
            if not p[1] or not p[2] or any(x & 15 for x in (p[0], p[1], p[3])):
                raise ValueError()
            data = (p[4].to_bytes(4, "little") * (p[1] // 4))
            for row in range(p[2]):
                start = p[0] + row * p[3]
                self.cpu.memory[start:start + p[1]] = data
        elif op == 1:  # COPY
            if not p[2] or not p[3] or any(x & 15 for x in (p[0], p[1], p[2], p[4], p[5])):
                raise ValueError()
            for row in range(p[3]):
                src = p[0] + row * p[4]
                dst = p[1] + row * p[5]
                self.cpu.memory[dst:dst + p[2]] = self.cpu.memory[src:src + p[2]]
        elif op == 3:  # SPAN explícito
            if mode & 0xc000 or mode & 0x1000 or not p[2] or not p[3] or not (mode & 0x60) or (mode & 7) == 7:
                raise ValueError()
            csize, zsize = (4 if mode & 8 else 2), (4 if mode & 16 else 2)
            if p[0] % csize or p[1] % zsize:
                raise ValueError()
            for row in range(p[3]):
                for col in range(p[2]):
                    zraw = (p[7] + col * p[8] + row * p[9]) & MASK32
                    shifted = s32(zraw) >> ((mode >> 8) & 15)
                    if zsize == 2 and mode & 0x2000:
                        newz = max(0, min(0xffff, shifted))
                    else:
                        newz = shifted & ((1 << (8 * zsize)) - 1)
                    za = p[1] + row * p[5] + col * zsize
                    ca = p[0] + row * p[4] + col * csize
                    old = self._read(za, zsize)
                    a = s32(newz) if mode & 0x80 and zsize == 4 else (newz ^ (0x8000 if mode & 0x80 else 0) if zsize == 2 else newz)
                    b = s32(old) if mode & 0x80 and zsize == 4 else (old ^ (0x8000 if mode & 0x80 else 0) if zsize == 2 else old)
                    cmp = mode & 7
                    passed = (cmp == 0 or (cmp == 1 and a == b) or (cmp == 2 and a != b) or
                              (cmp == 3 and a < b) or (cmp == 4 and a <= b) or
                              (cmp == 5 and a > b) or (cmp == 6 and a >= b))
                    if passed:
                        if mode & 0x20: self._write(za, zsize, newz)
                        if mode & 0x40: self._write(ca, csize, p[6])
        elif op == 5:  # CONFIG
            if mode & ~31 or not mode:
                raise ValueError()
            groups = ((0, 1), (2, 3), (4,), (5, 6, 7), (8,))
            for bit, indices in enumerate(groups):
                if mode & (1 << bit):
                    for i in indices: self.config[i] = p[i]
                    self.config_written |= 1 << bit
        else:
            raise ValueError()
