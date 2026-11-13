"""MiniISA FP32 reference arithmetic (RNE, DAZ/FTZ, canonical NaN).

Integer intermediates fit in 64 bits so the CPU core also compiles with Codon.
The architectural values are bit patterns, never Python floats.
"""


def shift_jam(value: int, amount: int) -> int:
    if amount <= 0:
        return value
    if amount >= 63:
        return int(value != 0)
    return (value >> amount) | int((value & ((1 << amount) - 1)) != 0)


def pack_fp32(sign: int, exponent: int, mantissa: int) -> int:
    if exponent <= 0:
        mantissa = shift_jam(mantissa, 1 - exponent)
        exponent = 1
    rounded = (mantissa >> 3) + int((mantissa & 4) != 0 and
                                  ((mantissa & 3) != 0 or (mantissa & 8) != 0))
    if rounded >= (1 << 24):
        rounded >>= 1
        exponent += 1
    if exponent >= 255:
        return (sign << 31) | 0x7F800000
    if rounded < (1 << 23):
        return sign << 31
    return (sign << 31) | (exponent << 23) | (rounded & 0x7FFFFF)


def fp32_binary(op: int, a: int, b: int) -> int:
    """op 0/1/2/3: FADD/FSUB/FMUL/FDIV, as in fp32_alu.sv."""
    ea, eb = (a >> 23) & 255, (b >> 23) & 255
    sa, sb = a >> 31, b >> 31
    ma, mb = a & 0x7FFFFF, b & 0x7FFFFF
    if (ea == 255 and ma != 0) or (eb == 255 and mb != 0):
        return 0x7FC00000
    ia, ib = ea == 255, eb == 255
    za, zb = ea == 0, eb == 0
    ma = 0 if za else ma | 0x800000
    mb = 0 if zb else mb | 0x800000
    if op <= 1:
        sb ^= op
        if ia and ib and sa != sb:
            return 0x7FC00000
        if ia or ib:
            return ((sa if ia else sb) << 31) | 0x7F800000
        if ea < eb or (ea == eb and ma < mb):
            ea, eb, ma, mb, sa, sb = eb, ea, mb, ma, sb, sa
        large, small = ma << 3, shift_jam(mb << 3, ea - eb)
        if sa == sb:
            result = large + small
            if result >= (1 << 27):
                result = shift_jam(result, 1)
                ea += 1
        else:
            result = large - small
            if result == 0:
                return 0
            while result < (1 << 26):
                result <<= 1
                ea -= 1
        return pack_fp32(sa, ea, result)
    sign = sa ^ sb
    if op == 2:
        if (ia and zb) or (ib and za):
            return 0x7FC00000
        if ia or ib:
            return (sign << 31) | 0x7F800000
        if za or zb:
            return sign << 31
        product = ma * mb
        high = product >= (1 << 47)
        return pack_fp32(sign, ea + eb - 127 + int(high),
                         shift_jam(product, 21 if high else 20))
    if (za and zb) or (ia and ib):
        return 0x7FC00000
    if ia or zb:
        return (sign << 31) | 0x7F800000
    if za or ib:
        return sign << 31
    low = ma < mb
    numerator = ma << (27 if low else 26)
    quotient = numerator // mb
    return pack_fp32(sign, ea - eb + 127 - int(low),
                     quotient | int(numerator % mb != 0))
