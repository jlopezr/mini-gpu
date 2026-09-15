import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from tools.prototype_report import (
    _backend_from_rtl,
    _capabilities,
    _capabilities_from_rtl,
    _clock_hz_from_rtl,
    _load_capability_signals,
    _memory_regions,
    _monitor_version_from_rtl,
    _readme_title,
    _version_label,
    _latest_summary,
)

CAPABILITIES_JSON = textwrap.dedent("""
    {
        "mul_div": {"file": "cpu.v", "pattern": "OPCODE_MUL:"},
        "video": {"file": "video_registers.v"}
    }
""")


class PrototypeReportTest(unittest.TestCase):
    def _make_repo(self, tmp: Path, with_rtl: bool = True) -> Path:
        root = tmp
        (root / "tools").mkdir(exist_ok=True)
        (root / "tools" / "capabilities.json").write_text(CAPABILITIES_JSON, encoding="utf-8")
        (root / "6.fpga-cpu").mkdir()
        (root / "6.fpga-cpu" / "README.md").write_text("# MiniCPU con memorias EBR\n\ntexto\n", encoding="utf-8")
        (root / "6.fpga-cpu" / "monitor.py").write_text(textwrap.dedent("""
            ARCHITECTURAL_REGIONS = (
                (0x0000_0000, 0x0000_4000),
                (0x0010_0000, 0x0010_4000),
            )
            MONITOR_REGIONS = ()
        """), encoding="utf-8")
        (root / "6.fpga-cpu" / "version.json").write_text(json.dumps({
            "alias": "ebr",
            "description": "FPGA con 16 KiB de EBR",
        }), encoding="utf-8")
        if with_rtl:
            (root / "6.fpga-cpu" / "cpu.v").write_text(textwrap.dedent("""
                localparam [5:0] OPCODE_MUL = 6'h0a;
                always @* case (opcode)
                  OPCODE_MUL: begin result = a * b; end
                endcase
            """), encoding="utf-8")
            (root / "6.fpga-cpu" / "monitor.v").write_text(textwrap.dedent("""
                localparam [7:0] VERSION_MAJOR = 8'h01;
                localparam [7:0] VERSION_MINOR = 8'h10;
            """), encoding="utf-8")
            (root / "6.fpga-cpu" / "pll_120.v").write_text(
                '(* FREQUENCY_PIN_CLKOP="120" *)\n', encoding="utf-8",
            )
        return root

    def test_readme_title_reads_first_heading(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            self.assertEqual(_readme_title(root / "6.fpga-cpu"), "MiniCPU con memorias EBR")

    def test_memory_regions_parses_tuples_without_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            regions = _memory_regions(root / "6.fpga-cpu")
            self.assertEqual(regions["ARCHITECTURAL_REGIONS"][0], (0x0000, 0x4000))
            self.assertEqual(regions["ARCHITECTURAL_REGIONS"][1], (0x100000, 0x104000))
            self.assertEqual(regions["MONITOR_REGIONS"], ())

    # -- señales RTL individuales -----------------------------------------

    def test_backend_from_rtl_detects_cpu(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            self.assertEqual(_backend_from_rtl(root / "6.fpga-cpu"), "cpu")

    def test_backend_from_rtl_detects_gpu(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp), with_rtl=False)
            gpu_dir = root / "17.gpu"
            gpu_dir.mkdir()
            (gpu_dir / "gpu_system.v").write_text("", encoding="utf-8")
            self.assertEqual(_backend_from_rtl(gpu_dir), "gpu")

    def test_backend_from_rtl_none_without_core(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp), with_rtl=False)
            bringup = root / "5.bringup"
            bringup.mkdir()
            self.assertIsNone(_backend_from_rtl(bringup))

    def test_monitor_version_from_rtl_reads_localparams(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            self.assertEqual(_monitor_version_from_rtl(root / "6.fpga-cpu"), (1, 16))

    def test_clock_hz_from_rtl_reads_pll_attribute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            self.assertEqual(_clock_hz_from_rtl(root / "6.fpga-cpu"), 120_000_000)

    def test_capabilities_from_rtl_matches_case_label_not_comment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            signals = _load_capability_signals(root)
            found = _capabilities_from_rtl(root / "6.fpga-cpu", signals)
            self.assertIn("mul_div", found)
            self.assertNotIn("video", found)  # no hay video_registers.v

    def test_capabilities_from_rtl_ignores_mention_without_case_label(self):
        # Como la 10.fpga-cpu-ram: OPCODE_MUL solo aparece en un comentario,
        # nunca como etiqueta de case -- no debe contar como implementado.
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp), with_rtl=False)
            proto = root / "10.fpga-cpu-ram"
            proto.mkdir()
            (proto / "cpu.v").write_text("// MULFX: no implementada. Ver OPCODE_MUL.\n", encoding="utf-8")
            signals = _load_capability_signals(root)
            found = _capabilities_from_rtl(proto, signals)
            self.assertNotIn("mul_div", found)

    # -- _capabilities: composición completa -------------------------------

    def test_capabilities_reads_identity_from_rtl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            cap = _capabilities(root / "6.fpga-cpu", root)
            self.assertEqual(cap["backend"], "cpu")
            self.assertEqual(cap["monitor_version"], (1, 16))
            self.assertEqual(cap["capabilities"], ("mul_div",))
            self.assertEqual(cap["clock_hz"], 120_000_000)

    def test_capabilities_fills_version_name_from_versions_dict_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            cap = _capabilities(root / "6.fpga-cpu", root)
            self.assertEqual(cap["version_name"], "ebr")
            self.assertEqual(cap["description"], "FPGA con 16 KiB de EBR")

    def test_capabilities_falls_back_to_folder_name_when_undeclared(self):
        # Como la 17.fpga-gpu-ram-v2 antes de este cambio: tiene RTL real,
        # pero no aparece en ningún VERSIONS. Ya no debe quedar vacío.
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            proto = root / "99.standalone"
            proto.mkdir()
            (proto / "cpu.v").write_text("localparam OPCODE_MUL = 0; OPCODE_MUL: begin end\n", encoding="utf-8")
            (proto / "monitor.v").write_text(
                "localparam [7:0] VERSION_MAJOR = 8'h01;\nlocalparam [7:0] VERSION_MINOR = 8'h00;\n",
                encoding="utf-8",
            )
            cap = _capabilities(proto, root)
            self.assertEqual(cap["backend"], "cpu")
            self.assertEqual(cap["version_name"], "99.standalone")
            self.assertNotIn("description", cap)

    def test_capabilities_empty_without_core_rtl(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            (root / "99.other").mkdir()
            self.assertEqual(_capabilities(root / "99.other", root), {})

    def test_version_label_reads_alias_and_description_from_version_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            label = _version_label(root / "6.fpga-cpu", root)
            self.assertEqual(label["version_name"], "ebr")
            self.assertEqual(label["description"], "FPGA con 16 KiB de EBR")

    def test_version_label_falls_back_to_readme_title_without_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            # Sin "description": solo el alias es obligatorio en version.json.
            (root / "6.fpga-cpu" / "version.json").write_text(
                json.dumps({"alias": "ebr"}), encoding="utf-8")
            label = _version_label(root / "6.fpga-cpu", root)
            self.assertEqual(label["version_name"], "ebr")
            self.assertEqual(label["description"], "MiniCPU con memorias EBR")

    def test_latest_summary_picks_newest_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            reports = root / "6.fpga-cpu" / "reports"
            older = reports / "20260101-000000-a"
            newer = reports / "20260102-000000-b"
            older.mkdir(parents=True)
            newer.mkdir(parents=True)
            (older / "summary.json").write_text(json.dumps({"label": "a"}), encoding="utf-8")
            (newer / "summary.json").write_text(json.dumps({"label": "b"}), encoding="utf-8")
            summary = _latest_summary(root / "6.fpga-cpu")
            self.assertEqual(summary["label"], "b")

    def test_latest_summary_empty_without_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            self.assertEqual(_latest_summary(root / "6.fpga-cpu"), {})


if __name__ == "__main__":
    unittest.main()
