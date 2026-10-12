#!/usr/bin/env python3
"""Tests for the declarative MiniISA split."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

import minigpu_isa as isa
from isa_core import ISAEncodingError


ROOT = Path(__file__).resolve().parents[1]
LEGACY_ASM = ROOT / "asm1" / "mini_asm.py"

spec = importlib.util.spec_from_file_location("legacy_mini_asm", LEGACY_ASM)
assert spec is not None and spec.loader is not None
legacy_mini_asm = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = legacy_mini_asm
spec.loader.exec_module(legacy_mini_asm)


def asm_first(source: str) -> int:
    return legacy_mini_asm.assemble(source)[0]


class CompatibilityTest(unittest.TestCase):
    def test_binary_compatibility_with_current_assembler(self):
        cases = [
            ("NOP", "NOP", {}),
            ("ADD", "ADD R1, R2, R3", {"Rd": 1, "Ra": 2, "Rb": 3}),
            ("SUB", "SUB R4, R5, R6", {"Rd": 4, "Ra": 5, "Rb": 6}),
            ("MULHI", "MULHI R1, R2, R3", {"Rd": 1, "Ra": 2, "Rb": 3}),
            ("SLTU", "SLTU R1, R2, R3", {"Rd": 1, "Ra": 2, "Rb": 3}),
            ("ADDI", "ADDI R1, R2, -7", {"Rd": 1, "Ra": 2, "imm16": -7}),
            ("ANDI", "ANDI R1, R2, 0xCAFE", {"Rd": 1, "Ra": 2, "imm16": 0xCAFE}),
            ("MOVI", "MOVI R1, -1", {"Rd": 1, "imm16": -1}),
            ("MOVHI", "MOVHI R1, 0x1234", {"Rd": 1, "imm16": 0x1234}),
            ("LOAD", "LOAD R1, R2, -4", {"Rd": 1, "Ra": 2, "imm16": -4}),
            ("STOREH", "STOREH R1, R2, 6", {"Rd": 1, "Ra": 2, "imm16": 6}),
            ("SHL", "SHL R1, R2, R3", {"Rd": 1, "Ra": 2, "Rb": 3}),
            ("SHLI", "SHLI R1, R2, 5", {"Rd": 1, "Ra": 2, "imm5": 5}),
            ("SHR", "SHR R1, R2, R3", {"Rd": 1, "Ra": 2, "Rb": 3}),
            ("SHRI", "SHRI R1, R2, 5", {"Rd": 1, "Ra": 2, "imm5": 5}),
            ("SAR", "SAR R1, R2, R3", {"Rd": 1, "Ra": 2, "Rb": 3}),
            ("SARI", "SARI R1, R2, 5", {"Rd": 1, "Ra": 2, "imm5": 5}),
            ("JALR", "JALR R31, R5, -2", {"Rd": 31, "Ra": 5, "imm16": -2}),
            ("JR", "JR R5", {"Ra": 5}),
            ("BAR", "BAR", {}),
            ("EXIT", "EXIT", {}),
            ("TRAP", "TRAP", {}),
            ("HALT", "HALT", {}),
        ]

        for name, source, operands in cases:
            with self.subTest(name=name):
                self.assertEqual(isa.encode(name, **operands), asm_first(source))

    def test_branch_binary_compatibility_with_current_assembler(self):
        cases = [
            ("BEQ", "BEQ R1, R2, target\nNOP\ntarget:\nNOP", {"Ra": 1, "Rb": 2, "target": 1}),
            ("BNE", "BNE R1, R2, target\nNOP\ntarget:\nNOP", {"Ra": 1, "Rb": 2, "target": 1}),
            ("BLT", "BLT R1, R2, target\nNOP\ntarget:\nNOP", {"Ra": 1, "Rb": 2, "target": 1}),
            ("BGE", "BGE R1, R2, target\nNOP\ntarget:\nNOP", {"Ra": 1, "Rb": 2, "target": 1}),
            ("BLTU", "BLTU R1, R2, target\nNOP\ntarget:\nNOP", {"Ra": 1, "Rb": 2, "target": 1}),
            ("BGEU", "BGEU R1, R2, target\nNOP\ntarget:\nNOP", {"Ra": 1, "Rb": 2, "target": 1}),
            ("JAL", "JAL R31, target\nNOP\ntarget:\nNOP", {"Rd": 31, "target": 1}),
            ("BRA", "BRA target\nNOP\ntarget:\nNOP", {"target": 1}),
            ("SSY", "SSY target\nNOP\ntarget:\nNOP", {"target": 1}),
        ]

        for name, source, operands in cases:
            with self.subTest(name=name):
                self.assertEqual(isa.encode(name, **operands), asm_first(source))

    def test_getid_family_matches_assembler(self):
        for type_id, name in enumerate(("GETTID", "GETLANE", "GETWARP", "GETLWARP", "GETARG")):
            with self.subTest(name=name):
                word = isa.encode(name, Rd=7)
                self.assertEqual(word, asm_first(f"{name} R7"))
                self.assertEqual(isa.decode(word).name, name)
                self.assertEqual((word >> 16) & 0x1F, type_id)
                self.assertEqual(word & 0xFFFF, 0)


class RoundTripTest(unittest.TestCase):
    def test_encode_decode_decode_operands(self):
        pc = 0x100
        cases = [
            ("NOP", {}),
            ("ADD", {"Rd": 1, "Ra": 2, "Rb": 3}),
            ("ADDI", {"Rd": 1, "Ra": 2, "imm16": -123}),
            ("ORI", {"Rd": 1, "Ra": 2, "imm16": 0xABCD}),
            ("LOADB", {"Rd": 1, "Ra": 2, "imm16": -8}),
            ("SHLI", {"Rd": 1, "Ra": 2, "imm5": 31}),
            ("GETARG", {"Rd": 4}),
            ("JALR", {"Rd": 31, "Ra": 5, "imm16": -2}),
            ("JR", {"Ra": 31}),
            ("BAR", {}),
            ("EXIT", {}),
        ]
        branch_cases = [
            ("BEQ", {"Ra": 1, "Rb": 2, "target": -2}),
            ("JAL", {"Rd": 31, "target": 3}),
            ("BRA", {"target": -3}),
            ("SSY", {"target": 2}),
        ]

        for name, operands in cases:
            with self.subTest(name=name):
                word = isa.encode(name, **operands)
                inst = isa.decode(word)
                self.assertIsNotNone(inst)
                self.assertEqual(inst.name, name)
                self.assertEqual(inst.decode_operands(word, pc), list(operands.values()))

        for name, operands in branch_cases:
            with self.subTest(name=name):
                word = isa.encode(name, **operands)
                inst = isa.decode(word)
                self.assertIsNotNone(inst)
                self.assertEqual(inst.name, name)
                decoded = inst.decode_operands(word, pc)
                expected = list(operands.values())
                expected[-1] = pc + 4 + operands["target"] * 4
                self.assertEqual(decoded, expected)


class OperandLimitsTest(unittest.TestCase):
    def test_accepts_minimum_and_maximum_values(self):
        self.assertEqual(isa.encode("ADDI", Rd=31, Ra=0, imm16=-32768) & 0xFFFF, 0x8000)
        self.assertEqual(isa.encode("ADDI", Rd=31, Ra=0, imm16=32767) & 0xFFFF, 0x7FFF)
        self.assertEqual(isa.encode("ORI", Rd=31, Ra=0, imm16=0xFFFF) & 0xFFFF, 0xFFFF)
        self.assertEqual((isa.encode("SHLI", Rd=1, Ra=2, imm5=31) >> 11) & 0x1F, 31)
        self.assertEqual(isa.encode("BRA", target=-(1 << 25)) & 0x03FFFFFF, 1 << 25)
        self.assertEqual(isa.encode("BRA", target=(1 << 25) - 1) & 0x03FFFFFF, (1 << 25) - 1)

    def test_rejects_out_of_range_values(self):
        bad_cases = [
            ("ADDI", {"Rd": 1, "Ra": 2, "imm16": -32769}),
            ("ADDI", {"Rd": 1, "Ra": 2, "imm16": 32768}),
            ("ORI", {"Rd": 1, "Ra": 2, "imm16": -1}),
            ("ORI", {"Rd": 1, "Ra": 2, "imm16": 0x10000}),
            ("ADD", {"Rd": 32, "Ra": 2, "Rb": 3}),
            ("SHLI", {"Rd": 1, "Ra": 2, "imm5": 32}),
            ("BRA", {"target": 1 << 25}),
        ]
        for name, operands in bad_cases:
            with self.subTest(name=name, operands=operands):
                with self.assertRaises(ISAEncodingError):
                    isa.encode(name, **operands)

    def test_rejects_missing_and_unknown_operands(self):
        with self.assertRaises(ISAEncodingError):
            isa.encode("ADD", Rd=1, Ra=2)
        with self.assertRaises(ISAEncodingError):
            isa.encode("ADD", Rd=1, Ra=2, Rb=3, imm16=0)


class ToolCompatibilityTest(unittest.TestCase):
    def test_decode_unknown_returns_none(self):
        self.assertIsNone(isa.decode(0x34 << 26))

    def test_disassemble_word(self):
        word = isa.encode("GETLANE", Rd=2)
        self.assertEqual(isa.disassemble_word(word), "GETLANE R2")

    def test_validate_and_mini_isa_cli(self):
        isa.validate_isa()
        script = Path(__file__).with_name("mini-isa.py")
        result = subprocess.run(
            [sys.executable, str(script), "--list"],
            cwd=script.parent,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("GETARG", result.stdout)


if __name__ == "__main__":
    unittest.main()
