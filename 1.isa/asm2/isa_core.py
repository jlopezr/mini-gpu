#!/usr/bin/env python3
"""
Generic declarative ISA infrastructure.

This module deliberately knows nothing about MiniGPU opcodes, formats or
pseudoinstructions. It only provides the machinery to describe fields,
operands and instructions, then validate, encode and decode them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


class ISAError(ValueError):
    """Base error for ISA definitions, encoding and decoding."""


class ISAValidationError(ISAError):
    """Invalid ISA definition."""


class ISAEncodingError(ISAError):
    """Invalid operand value or instruction encoding."""


class ISADecodingError(ISAError):
    """Instruction cannot be decoded."""


def mask_bits(width: int) -> int:
    if width < 0:
        raise ISAValidationError(f"invalid bit width: {width}")
    return (1 << width) - 1


def sign_extend(value: int, bits: int) -> int:
    value &= mask_bits(bits)
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign


def check_signed(value: int, bits: int, what: str = "value") -> int:
    lo = -(1 << (bits - 1))
    hi = (1 << (bits - 1)) - 1
    if not lo <= value <= hi:
        raise ISAEncodingError(f"{what} outside signed{bits}: {value}")
    return value & mask_bits(bits)


def check_unsigned(value: int, bits: int, what: str = "value") -> int:
    hi = mask_bits(bits)
    if not 0 <= value <= hi:
        raise ISAEncodingError(f"{what} outside unsigned{bits}: {value}")
    return value


@dataclass(frozen=True)
class Field:
    name: str
    lsb: int
    width: int

    @property
    def mask(self) -> int:
        return mask_bits(self.width) << self.lsb

    @property
    def value_mask(self) -> int:
        return mask_bits(self.width)

    @property
    def msb(self) -> int:
        return self.lsb + self.width - 1

    def extract(self, word: int) -> int:
        return (word >> self.lsb) & self.value_mask

    def insert(self, word: int, value: int) -> int:
        if not isinstance(value, int):
            raise ISAEncodingError(
                f"{self.name}: expected integer, got {type(value).__name__}"
            )
        if value & ~self.value_mask:
            raise ISAEncodingError(
                f"{self.name}: 0x{value:x} does not fit in {self.width} bits"
            )
        word &= ~self.mask
        word |= (value & self.value_mask) << self.lsb
        return word

    def encode(self, value: int) -> int:
        return self.insert(0, value)

    def decode(self, word: int) -> int:
        return self.extract(word)

    def validate(self, word_bits: int) -> None:
        if self.lsb < 0:
            raise ISAValidationError(f"{self.name}: negative bit position")
        if self.width <= 0:
            raise ISAValidationError(f"{self.name}: width must be positive")
        if self.msb >= word_bits:
            raise ISAValidationError(f"{self.name}: field exceeds instruction width")


@dataclass(frozen=True)
class Format:
    name: str
    fields: tuple[Field, ...]
    word_bits: int = 32

    def validate(self) -> None:
        if self.word_bits <= 0:
            raise ISAValidationError(f"{self.name}: invalid instruction width")

        names: set[str] = set()
        used = 0
        for field in self.fields:
            field.validate(self.word_bits)
            if field.name in names:
                raise ISAValidationError(f"{self.name}: duplicate field {field.name}")
            if used & field.mask:
                raise ISAValidationError(f"{self.name}: overlapping field {field.name}")
            names.add(field.name)
            used |= field.mask

    def field(self, name: str) -> Field:
        for field in self.fields:
            if field.name == name:
                return field
        raise KeyError(name)


@dataclass(frozen=True)
class Operand:
    name: str
    field: Field
    kind: str
    bits: int | None = None
    scale: int = 1
    pc_relative: bool = False
    pc_bias: int = 0

    @property
    def width(self) -> int:
        return self.bits or self.field.width

    @property
    def signed(self) -> bool:
        return self.kind in {"simm", "signed", "branch"}

    def limits(self) -> tuple[int, int]:
        if self.signed:
            return -(1 << (self.width - 1)), (1 << (self.width - 1)) - 1
        return 0, mask_bits(self.width)

    def encode_value(self, value: int) -> int:
        if not isinstance(value, int):
            raise ISAEncodingError(f"{self.name}: expected integer")
        lo, hi = self.limits()
        if not lo <= value <= hi:
            raise ISAEncodingError(f"{self.name}: {value} outside [{lo}, {hi}]")
        return value & mask_bits(self.width)

    def encode(self, value: int) -> int:
        return self.field.encode(self.encode_value(value))

    def decode(self, word: int, pc: int = 0) -> int:
        raw = self.field.extract(word)
        if self.signed:
            raw = sign_extend(raw, self.width)
        return self.to_architectural(raw, pc)

    def to_architectural(self, encoded_value: int, pc: int = 0) -> int:
        value = encoded_value * self.scale
        if self.pc_relative:
            value += pc + self.pc_bias
        return value

    def from_architectural(self, value: int, pc: int = 0) -> int:
        if self.pc_relative:
            value -= pc + self.pc_bias
        if value % self.scale:
            raise ISAEncodingError(
                f"{self.name}: value is not aligned to scale {self.scale}"
            )
        return value // self.scale

    def validate(self) -> None:
        if self.width <= 0:
            raise ISAValidationError(f"{self.name}: invalid operand width")
        if self.width > self.field.width:
            raise ISAValidationError(
                f"{self.name}: operand width exceeds field width"
            )
        if self.kind not in {"reg", "simm", "uimm", "branch", "signed", "unsigned", "uint"}:
            raise ISAValidationError(
                f"{self.name}: unknown operand kind {self.kind}"
            )
        if self.scale <= 0:
            raise ISAValidationError(f"{self.name}: scale must be positive")


@dataclass(frozen=True)
class Instruction:
    name: str
    opcode: int
    fmt: Format
    operands: tuple[Operand, ...]
    syntax: str
    description: str
    fixed_mask: int = 0
    fixed_value: int = 0
    category: str = ""

    @property
    def opcode_field(self) -> Field:
        try:
            return self.fmt.field("opcode")
        except KeyError as error:
            raise ISAValidationError(
                f"{self.name}: format {self.fmt.name} has no opcode field"
            ) from error

    @property
    def match_mask(self) -> int:
        return self.opcode_field.mask | self.fixed_mask

    @property
    def match_value(self) -> int:
        return self.opcode_field.encode(self.opcode) | self.fixed_value

    def matches(self, word: int) -> bool:
        return (word & self.match_mask) == self.match_value

    def encode(self, **operands: int) -> int:
        expected = {operand.name for operand in self.operands}
        provided = set(operands)

        missing = expected - provided
        if missing:
            raise ISAEncodingError(
                f"{self.name}: missing operands {sorted(missing)}"
            )

        extra = provided - expected
        if extra:
            raise ISAEncodingError(
                f"{self.name}: unexpected operands {sorted(extra)}"
            )

        word = self.match_value
        occupied = self.match_mask
        for operand in self.operands:
            encoded = operand.encode(operands[operand.name])
            if encoded & self.fixed_mask:
                raise ISAEncodingError(
                    f"{self.name}: operand {operand.name} overlaps fixed bits"
                )
            if encoded & (occupied & ~operand.field.mask):
                raise ISAEncodingError(
                    f"{self.name}: operand {operand.name} overlaps existing bits"
                )
            word |= encoded
            occupied |= operand.field.mask

        return word & mask_bits(self.fmt.word_bits)

    def decode_operands(self, word: int, pc: int = 0) -> list[int]:
        if not self.matches(word):
            raise ISADecodingError(f"{self.name}: instruction does not match")
        return [operand.decode(word, pc) for operand in self.operands]

    def validate(self) -> None:
        self.fmt.validate()
        word_mask = mask_bits(self.fmt.word_bits)

        if not 0 <= self.opcode <= self.opcode_field.value_mask:
            raise ISAValidationError(f"{self.name}: opcode out of range")
        if self.fixed_mask & ~word_mask:
            raise ISAValidationError(f"{self.name}: fixed mask exceeds word width")
        if self.fixed_value & ~self.fixed_mask:
            raise ISAValidationError(
                f"{self.name}: fixed value contains bits outside fixed mask"
            )
        if self.fixed_mask & self.opcode_field.mask:
            raise ISAValidationError(f"{self.name}: fixed bits overlap opcode")

        names: set[str] = set()
        used = 0
        for operand in self.operands:
            operand.validate()
            if operand.name in names:
                raise ISAValidationError(
                    f"{self.name}: duplicate operand {operand.name}"
                )
            if operand.field not in self.fmt.fields:
                raise ISAValidationError(
                    f"{self.name}: operand {operand.name} uses field outside format"
                )
            if used & operand.field.mask:
                raise ISAValidationError(f"{self.name}: overlapping operands")
            if self.fixed_mask & operand.field.mask:
                raise ISAValidationError(
                    f"{self.name}: operand {operand.name} overlaps fixed bits"
                )
            names.add(operand.name)
            used |= operand.field.mask


class ISA:
    """Generic instruction set container."""

    def __init__(self, instructions: Iterable[Instruction]):
        self.instructions = tuple(instructions)
        self.by_name: dict[str, Instruction] = {}
        self.by_opcode: dict[int, tuple[Instruction, ...]] = {}

        for instruction in self.instructions:
            key = instruction.name.upper()
            if key in self.by_name:
                raise ISAValidationError(f"duplicate instruction: {instruction.name}")
            self.by_name[key] = instruction

        opcodes = sorted({instruction.opcode for instruction in self.instructions})
        for opcode in opcodes:
            candidates = tuple(
                sorted(
                    (
                        instruction
                        for instruction in self.instructions
                        if instruction.opcode == opcode
                    ),
                    key=lambda instruction: instruction.match_mask.bit_count(),
                    reverse=True,
                )
            )
            self.by_opcode[opcode] = candidates

        self.validate()

    def instruction(self, name: str) -> Instruction:
        try:
            return self.by_name[name.upper()]
        except KeyError:
            raise KeyError(f"unknown instruction: {name}") from None

    def encode(self, name: str, **operands: int) -> int:
        return self.instruction(name).encode(**operands)

    def decode(self, word: int) -> Instruction | None:
        word &= 0xFFFFFFFF
        for candidates in self.by_opcode.values():
            for instruction in candidates:
                if instruction.matches(word):
                    return instruction
        return None

    def validate(self) -> None:
        for instruction in self.instructions:
            instruction.validate()

        for index, a in enumerate(self.instructions):
            for b in self.instructions[index + 1:]:
                common = a.match_mask & b.match_mask
                if ((a.match_value ^ b.match_value) & common) == 0:
                    raise ISAValidationError(
                        f"ambiguous encodings: {a.name} and {b.name}"
                    )
