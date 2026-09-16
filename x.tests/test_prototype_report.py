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
    collect as _collect,
    simulator_capabilities as _simulator_capabilities,
    _uart_baud_from_rtl,
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

    def test_simulator_capabilities_parses_backends_without_import(self):
        # `x.tests` no es importable (el punto del nombre lo impide) y el
        # runner arrastra dependencias que un informe no necesita, así que se
        # lee con ast igual que ARCHITECTURAL_REGIONS.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backends = root / "x.tests" / "backends"
            backends.mkdir(parents=True)
            (backends / "simulator.py").write_text(textwrap.dedent("""
                from pathlib import Path
                VERSIONS = {
                    "current": {
                        "simulator_path": Path("2.cpu-sim-func/minicpu_sim.py"),
                        "memory_size": 32 * 1024 * 1024,
                        "capabilities": ("frame_capture", "mul_div"),
                        "description": "simulador funcional MiniCPU actual",
                    },
                }
            """), encoding="utf-8")
            (backends / "gpu_simulator.py").write_text(textwrap.dedent("""
                from pathlib import Path
                VERSIONS = {
                    "current": {
                        "simulator_path": Path("11.gpu-sim-func/minigpu_sim.py"),
                        "capabilities": ("atomic_warp_faults",),
                    },
                }
            """), encoding="utf-8")
            entries = {e["name"]: e for e in _simulator_capabilities(root)}
            self.assertEqual(set(entries), {"2.cpu-sim-func", "11.gpu-sim-func"})
            cpu = entries["2.cpu-sim-func"]
            self.assertEqual(cpu["architecture"], "cpu")
            self.assertEqual(cpu["capabilities"], ("frame_capture", "mul_div"))
            # `memory_size` es un BinOp y no se puede leer como literal; que no
            # rompa el resto de la entrada es justo lo que se comprueba aquí.
            self.assertNotIn("memory_size", cpu)
            self.assertEqual(entries["11.gpu-sim-func"]["architecture"], "gpu")

    def test_build_snapshot_used_when_no_report_is_archived(self):
        # Los prototipos de CPU no tienen `reports/`: sus números de síntesis
        # solo existen en `_build/`, que es de donde salían a mano.
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            build = root / "6.fpga-cpu" / "_build" / "default"
            build.mkdir(parents=True)
            (build / "hardware.pnr").write_text(json.dumps({
                "fmax": {"$glbnet$clk": {"achieved": 127.3, "constraint": 120}},
                "utilization": {"TRELLIS_COMB": {"used": 5664},
                                "TRELLIS_FF": {"used": 2466}},
                "critical_paths": [],
            }), encoding="utf-8")
            report = _collect(root / "6.fpga-cpu", root)
            self.assertEqual(report["synthesis"]["_source"], "_build")
            self.assertEqual(report["synthesis"]["clocks"]["$glbnet$clk"]["achieved"], 127.3)
            self.assertEqual(report["synthesis"]["utilization"]["TRELLIS_COMB"]["used"], 5664)

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

    def test_uart_baud_divides_the_system_clock(self):
        # El divisor es una constante elegida -- multiplo de 4 y con baudio que
        # el FTDI genere exacto --, no una division: se lee, no se calcula.
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            (root / "6.fpga-cpu" / "top.v").write_text(textwrap.dedent("""
                module top(input clk_25mhz);
                  localparam integer UART_CLOCKS_PER_BIT = 40;
                  localparam integer UART_DIVISOR = UART_CLOCKS_PER_BIT;
                endmodule
            """), encoding="utf-8")
            # Gana el PLL sobre el oscilador: 120 MHz / 40 = 3 Mbaud.
            self.assertEqual(_uart_baud_from_rtl(root / "6.fpga-cpu"), 3_000_000)

    def test_uart_baud_is_none_without_divisor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp))
            (root / "6.fpga-cpu" / "top.v").write_text(
                "module top(input clk_25mhz);\nendmodule\n", encoding="utf-8")
            self.assertIsNone(_uart_baud_from_rtl(root / "6.fpga-cpu"))

    def test_clock_hz_from_rtl_falls_back_to_board_oscillator(self):
        # Como las GPU: sin PLL, el reloj del núcleo es el de la placa y se lee
        # del puerto de entrada del top. Devolver None diría "no se sabe"
        # cuando el valor está bien definido.
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp), with_rtl=False)
            proto = root / "99.gpu-sin-pll"
            proto.mkdir()
            (proto / "top.v").write_text(
                "module top(input clk_25mhz, output [7:0] led);\nendmodule\n",
                encoding="utf-8",
            )
            self.assertEqual(_clock_hz_from_rtl(proto), 25_000_000)

    def test_clock_hz_from_rtl_prefers_pll_over_board_oscillator(self):
        # La 22 tiene las dos cosas: `clk_25mhz` de entrada y un PLL, pero ese
        # PLL es solo para los relojes de pixel. Si algún día un prototipo trae
        # un PLL de sistema, ese es el que manda.
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_repo(Path(tmp), with_rtl=False)
            proto = root / "99.con-pll"
            proto.mkdir()
            (proto / "top.v").write_text(
                "module top(input clk_25mhz);\nendmodule\n", encoding="utf-8"
            )
            (proto / "pll_cpu.v").write_text(
                'FREQUENCY_PIN_CLKOP = "80.000000"\n', encoding="utf-8"
            )
            self.assertEqual(_clock_hz_from_rtl(proto), 80_000_000)

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
