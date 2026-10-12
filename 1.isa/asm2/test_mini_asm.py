#!/usr/bin/env python3
"""Compatibility tests for the declarative mini-asm implementation."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


old_asm = load_module("old_mini_asm_for_new_tests", ROOT / "asm1" / "mini_asm.py")
new_asm = load_module("new_mini_asm_for_new_tests", HERE / "mini-asm.py")


def assert_same_binary(testcase: unittest.TestCase, source: str,
                       base_dir: Path | None = None,
                       origin: str = old_asm.ENTRADA,
                       include_dirs: tuple[Path, ...] = (),
                       defines: frozenset[str] = frozenset()) -> bytes:
    old = old_asm.assemble_bytes(source, base_dir, origin, include_dirs, defines)
    new = new_asm.assemble_bytes(source, base_dir, origin, include_dirs, defines)
    testcase.assertEqual(new, old)
    return new


class InstructionCompatibilityTest(unittest.TestCase):
    def test_all_real_instruction_families_match_old_assembler(self):
        source = "\n".join([
            "NOP",
            "ADD R1, R2, R3",
            "SUB R1, R2, R3",
            "MULFX R1, R2, R3",
            "AND R1, R2, R3",
            "OR R1, R2, R3",
            "XOR R1, R2, R3",
            "SHL R1, R2, R3",
            "SHR R1, R2, R3",
            "SAR R1, R2, R3",
            "SHLI R1, R2, 5",
            "SHRI R1, R2, 6",
            "SARI R1, R2, 7",
            "MUL R1, R2, R3",
            "MULHI R1, R2, R3",
            "DIV R1, R2, R3",
            "DIVU R1, R2, R3",
            "REM R1, R2, R3",
            "REMU R1, R2, R3",
            "MOVI R1, -1",
            "ADDI R1, R2, -7",
            "ANDI R1, R2, 0xCAFE",
            "ORI R1, R2, 0x1234",
            "XORI R1, R2, 0x4321",
            "LOAD R1, R2, -4",
            "STORE R1, R2, 8",
            "MOVHI R1, 0xABCD",
            "LOADB R1, R2, -1",
            "LOADUB R1, R2, 2",
            "STOREB R1, R2, 3",
            "LOADH R1, R2, -4",
            "LOADUH R1, R2, 5",
            "STOREH R1, R2, 6",
            "BEQ R1, R2, target",
            "BNE R1, R2, target",
            "BLT R1, R2, target",
            "BGE R1, R2, target",
            "BLTU R1, R2, target",
            "BGEU R1, R2, target",
            "SLT R1, R2, R3",
            "SLTU R1, R2, R3",
            "JAL R31, target",
            "JALR R31, R5, -2",
            "JR R31",
            "BRA target",
            "GETTID R1",
            "GETLANE R2",
            "GETWARP R3",
            "GETLWARP R4",
            "GETARG R5",
            "SSY target",
            "BAR",
            "EXIT",
            "TRAP",
            "target:",
            "HALT",
            "",
        ])
        assert_same_binary(self, source)


class SymbolsSectionsAndRelaxationTest(unittest.TestCase):
    def test_symbols_sections_and_data_directives_match_old_assembler(self):
        source = "\n".join([
            ".equ SCREEN, 0x1000",
            ".set N, SCREEN+16",
            ".text",
            "start:",
            "    LI R1, msg",
            "    LA R2, table+4",
            "    LOAD R3, R0, N",
            "    BNE R1, R2, start",
            ".rodata",
            "msg:",
            '    .string "hi"',
            "    .align 8",
            "table:",
            "    .word msg, SCREEN, N",
            ".data",
            "    .half 1, -1",
            "    .byte 2, 3",
            ".bss",
            "    .comm scratch, 12, 4",
            "",
        ])
        assert_same_binary(self, source)

    def test_relaxation_boundaries_match_old_assembler(self):
        cases = [
            "LI R1, x\n.space 65531\nx:\n.word 1\n",
            "LI R1, x\n.space 65532\nx:\n.word 1\n",
            "LI R1, a\nLI R2, b\nLI R3, 0x12345678\na:\nNOP\nb:\nHALT\n",
            "LI R1, x\n.align 32\nx:\n.word 1\n",
        ]
        for source in cases:
            with self.subTest(source=source.splitlines()[0]):
                assert_same_binary(self, source)

    def test_local_and_compiler_labels_match_old_assembler(self):
        source = "\n".join([
            "global:",
            "@loop:",
            "    ADD R1, R2, R3",
            "    BNE R1, R0, @loop",
            "    BRA L.2",
            "L.2:",
            "    RET",
            "",
        ])
        assert_same_binary(self, source)


class IncludeAndMetadataTest(unittest.TestCase):
    def test_includes_preserve_binary_and_source_locations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inc = root / "include"
            inc.mkdir()
            (inc / "a.inc").write_text(
                ".once\nhelper:\n    GETLANE R2\n    RET\n", encoding="utf-8")
            (inc / "b.inc").write_text(
                '.include "a.inc"\nvalue:\n    .word helper\n', encoding="utf-8")
            source = '.include "include/b.inc"\nJAL R31, helper\nHALT\n'

            image = assert_same_binary(self, source, root, "main.asm")
            result = new_asm.assemble_program(source, root, "main.asm")

        self.assertEqual(result.image, image)
        self.assertIn("helper", result.symbols)
        self.assertIn("value", result.symbols)
        self.assertTrue(result.fragments)
        self.assertTrue(result.address_to_source)
        self.assertTrue(any(location.file == "a.inc"
                            for location in result.address_to_source.values()))
        self.assertTrue(all(reloc.resolved for reloc in result.relocations))

    def test_pseudoinstruction_words_share_original_location(self):
        source = "LI R1, 0x12345678\n"
        result = new_asm.assemble_program(source)
        self.assertEqual(len(result.image), 8)
        self.assertEqual(result.address_to_source[0], result.address_to_source[4])

    def test_relocation_metadata_describes_symbolic_references(self):
        source = "\n".join([
            "start:",
            "    LA R1, table+4",
            "    BNE R1, R0, start",
            "table:",
            "    .word start",
            "",
        ])
        result = new_asm.assemble_program(source)
        relocs = [(reloc.kind, reloc.offset, reloc.symbol, reloc.addend,
                   reloc.bit_size, reloc.mask)
                  for reloc in result.relocations]

        self.assertIn(("HI16", 0, "table", 4, 16, 0xFFFF0000), relocs)
        self.assertIn(("LO16", 4, "table", 4, 16, 0x0000FFFF), relocs)
        self.assertIn(("PCREL_WORD", 8, "start", -4, 16, 0x0003FFFC), relocs)
        self.assertIn(("ABS32", 12, "start", 0, 32, 0xFFFFFFFF), relocs)

    def test_extern_symbols_are_imported_for_object_output(self):
        source = ".extern target\nstart:\n    LA R1, target\n    .word target+4\n"
        result = new_asm.assemble_program(source)

        self.assertFalse(result.symbols["target"].defined)
        self.assertEqual(result.symbols["target"].kind, "extern")
        self.assertEqual(len(result.image), 12)
        self.assertEqual(
            [(reloc.kind, reloc.offset, reloc.symbol, reloc.addend)
             for reloc in result.relocations],
            [
                ("HI16", 0, "target", 0),
                ("LO16", 4, "target", 0),
                ("ABS32", 8, "target", 4),
            ],
        )

    def test_extern_accepts_lcc_size_operand(self):
        # lcc escribe `.extern nombre tamano` para los datos que usa y no define.
        result = new_asm.assemble_program(".extern counter 4\n    LA R1, counter\n")
        self.assertEqual(result.symbols["counter"].kind, "extern")
        with self.assertRaises(new_asm.AsmError):
            new_asm.assemble_program(".extern counter big\n")

    def test_image_rejects_used_extern_that_nobody_defines(self):
        # Sin linker, un .extern usado y sin definir quedaria en la direccion 0.
        with self.assertRaises(new_asm.AsmError) as raised:
            new_asm.assemble_bytes(".extern ghost\n    LA R1, ghost\n    HALT\n")
        self.assertIn("ghost", str(raised.exception))
        # Para un objeto si vale: lo resuelve el linker.
        self.assertEqual(new_asm.assemble_program(
            ".extern ghost\n    LA R1, ghost\n", relocatable=True).relocations[0].symbol, "ghost")

    def test_image_ignores_declared_but_unused_extern(self):
        # lcc declara todo `extern` que ve, aunque no lo use.
        image = new_asm.assemble_bytes(".extern unused 4\n    HALT\n")
        self.assertEqual(image, new_asm.assemble_bytes("HALT\n"))

    def test_extern_defined_in_same_assembly_resolves_locally(self):
        # build-c junta todas las unidades en un ensamblado: el `.extern` de una
        # puede nombrar lo que define otra, antes o despues.
        source = "\n".join([
            ".extern counter 4, helper",
            "start:",
            "    LA R1, counter",
            "    JAL R31, helper",
            "helper:",
            "    RET",
            ".bss",
            ".comm counter, 4",
            ".extern helper",
            "",
        ])
        result = new_asm.assemble_program(source)
        self.assertTrue(result.symbols["counter"].defined)
        self.assertTrue(result.symbols["helper"].defined)
        self.assertNotEqual(result.symbols["counter"].kind, "extern")

    def test_object_li_to_label_keeps_two_words(self):
        # En un objeto, `counter` vale 4 solo hasta enlazar: el linker puede
        # llevarlo por encima de 0x7FFF, donde un MOVI extenderia el signo.
        source = "start:\n    LI R1, counter\n    HALT\n.bss\n.comm counter, 4\n"
        image = new_asm.assemble_program(source)
        self.assertEqual(image.image[:4], new_asm.assemble_bytes("MOVI R1, 8\n"))  # imagen: una palabra
        result = new_asm.assemble_program(source, relocatable=True)
        self.assertEqual(
            [(reloc.kind, reloc.offset, reloc.symbol)
             for reloc in result.relocations],
            [("HI16", 0, "counter"), ("LO16", 4, "counter")],
        )
        self.assertEqual(result.symbols["counter"].offset, 0)

    def test_object_li_to_equate_still_relaxes(self):
        # Una constante de .equ no se mueve al enlazar: un MOVI le sigue valiendo.
        source = ".equ SIZE, 100\n    LI R1, SIZE\n    LI R2, SIZE+1\n    HALT\n"
        result = new_asm.assemble_program(source, relocatable=True)
        self.assertEqual(len(result.image), 12)
        self.assertEqual(result.relocations, [])

    def test_global_marks_symbol_binding(self):
        result = new_asm.assemble_program(".global helper\nhelper:\nRET\n")
        self.assertEqual(result.symbols["helper"].binding, "global")


class ApiAndCliSurfaceTest(unittest.TestCase):
    def test_public_api_shapes(self):
        source = "label:\nNOP\n.word label\n"
        result = new_asm.assemble_program(source)
        self.assertEqual(new_asm.assemble_bytes(source), result.image)
        self.assertEqual(new_asm.assemble(source),
                         [int.from_bytes(result.image[i:i + 4], "little")
                          for i in range(0, len(result.image), 4)])
        self.assertIn(".text", result.sections)
        self.assertEqual(result.symbols["label"].offset, 0)

    def test_listing_still_contains_core_sections(self):
        listing = new_asm.format_listing("label:\nNOP\nHALT\n")
        self.assertIn("Etiquetas:", listing)
        self.assertIn("Secciones:", listing)
        self.assertIn("Simbolos:", listing)

    def test_cli_can_write_vobj(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "program.asm"
            vobj = root / "program.vobj"
            source.write_text("start:\nHALT\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(HERE / "mini-asm.py"), str(source), "--vobj", str(vobj)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = vobj.read_bytes()
        self.assertEqual(data[:5], b"VOBJ\x02")
        self.assertIn(b"start\x00", data)
        self.assertIn(b".text\x00acx\x00", data)

    def test_cli_can_write_json_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "program.asm"
            json_path = root / "program.json"
            source.write_text("start:\n.word start\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(HERE / "mini-asm.py"),
                 str(source), "--json", str(json_path)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(data["magic"], "MiniGPU-Object")
        self.assertEqual(data["relocations"][0]["symbol"], "start")
        self.assertEqual(data["relocations"][0]["kind"], "ABS32")


if __name__ == "__main__":
    unittest.main()
