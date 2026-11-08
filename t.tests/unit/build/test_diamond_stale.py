"""STALE de los informes de Diamond: que cuente lo que Diamond usa y no lo demas."""
import tempfile
import unittest
from pathlib import Path

from tools.board_record import normalized_source_hashes
from tools.build_report import (DIAMOND_APIO_KEY, diamond_apio_digest, diamond_sources_current,
                                synthesizable_source_hashes)

INI = "[env:default]\nboard = ulx3s-85f\ntop-module = top\nnextpnr-extra-options = --seed {seed}\n"


class DiamondStaleTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.proto = Path(temp.name) / "1.proto"
        self.proto.mkdir()
        (self.proto / "top.v").write_bytes(b"module top;\nendmodule\n")
        (self.proto / "apio.ini").write_text(INI.format(seed=1), encoding="utf-8")
        (self.proto / "diamond-constraints.txt").write_text("BLOCK PATH ;\n", encoding="utf-8")

    def metadata(self, with_lf=True, with_ini_key=True):
        hashes = synthesizable_source_hashes(self.proto, diamond=True)
        if with_ini_key:
            hashes[DIAMOND_APIO_KEY] = diamond_apio_digest(self.proto)
        data = {"source_sha256": hashes}
        if with_lf:
            data["source_sha256_lf"] = normalized_source_hashes(self.proto)
        return data

    def test_unchanged_is_current(self):
        self.assertTrue(diamond_sources_current(self.metadata(), self.proto))

    def test_nextpnr_seed_does_not_stale_a_diamond_build(self):
        data = self.metadata()
        (self.proto / "apio.ini").write_text(INI.format(seed=9), encoding="utf-8")
        self.assertTrue(diamond_sources_current(data, self.proto))

    def test_legacy_report_still_sees_apio_ini_change(self):
        data = self.metadata(with_ini_key=False)
        (self.proto / "apio.ini").write_text(INI.format(seed=9), encoding="utf-8")
        self.assertFalse(diamond_sources_current(data, self.proto))

    def test_top_module_change_is_stale(self):
        data = self.metadata()
        (self.proto / "apio.ini").write_text(INI.format(seed=1).replace("= top\n", "= other\n"),
                                             encoding="utf-8")
        self.assertFalse(diamond_sources_current(data, self.proto))

    def test_line_endings_alone_do_not_stale_when_lf_hashes_are_stored(self):
        data = self.metadata()
        (self.proto / "top.v").write_bytes(b"module top;\r\nendmodule\r\n")
        self.assertTrue(diamond_sources_current(data, self.proto))

    def test_line_endings_without_lf_hashes_are_stale(self):
        data = self.metadata(with_lf=False)
        (self.proto / "top.v").write_bytes(b"module top;\r\nendmodule\r\n")
        self.assertFalse(diamond_sources_current(data, self.proto))

    def test_real_rtl_change_is_stale_even_with_lf_hashes(self):
        data = self.metadata()
        (self.proto / "top.v").write_bytes(b"module top;\nwire x;\nendmodule\n")
        self.assertFalse(diamond_sources_current(data, self.proto))

    def test_constraints_change_is_stale(self):
        data = self.metadata()
        (self.proto / "diamond-constraints.txt").write_text("BLOCK PATH X;\n", encoding="utf-8")
        self.assertFalse(diamond_sources_current(data, self.proto))


if __name__ == "__main__":
    unittest.main()
