import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from tools.trace_cli import main
from tools.traceability import MarkdownAdapter, ModelBuilder, Resolver

REPO = Path(__file__).resolve().parents[1]


class TraceabilityTest(unittest.TestCase):
    def test_adapter_creates_document_section_and_link_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "README.md"
            path.write_text("# Diseño\n\n[Detalle](docs/detail.md#contrato)\n", encoding="utf-8")
            result = MarkdownAdapter().read(path, root)
            self.assertEqual([item.key for item in result.identities], ["README.md", "README.md#diseño"])
            self.assertEqual(result.observations[0].target, "docs/detail.md#contrato")
            self.assertEqual(result.observations[0].location.line, 3)

    def test_typed_heading_scopes_its_observations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "requirements.md"
            path.write_text("# Requisitos\n## REQ-007: vídeo\n[Diseño](design.md#dec-007-video)\n", encoding="utf-8")
            result = MarkdownAdapter().read(path, root)
            requirement = result.identities[-1]
            self.assertEqual((requirement.kind, requirement.semantic_id), ("requirement", "REQ-007"))
            self.assertEqual(result.observations[0].source, requirement)

    def test_adapter_reads_legacy_cp1252_without_losing_anchor_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "legacy.md"
            path.write_bytes("# Qué cambió\n[Sección](#qué-cambió)\n".encode("cp1252"))
            model = ModelBuilder().build(root)
            self.assertEqual(Resolver().resolve(model), [])

    def test_resolver_accepts_relative_document_and_anchor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "docs").mkdir()
            (root / "README.md").write_text("[Contrato](docs/detail.md#contrato)\n", encoding="utf-8")
            (root / "docs" / "detail.md").write_text("# Contrato\n", encoding="utf-8")
            self.assertEqual(Resolver().resolve(ModelBuilder().build(root)), [])

    def test_resolver_reports_missing_file_and_anchor(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text(
                "# Inicio\n[No existe](missing.md)\n[Ancla](#ausente)\n", encoding="utf-8"
            )
            diagnostics = Resolver().resolve(ModelBuilder().build(root))
            self.assertEqual([item.code for item in diagnostics], ["missing-target", "unresolved-identity"])

    def test_explicit_duplicate_identity_is_an_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text("# Uno {#mismo}\n## Dos {#mismo}\n", encoding="utf-8")
            diagnostics = Resolver().resolve(ModelBuilder().build(root))
            self.assertEqual([item.code for item in diagnostics], ["duplicate-identity"])

    def test_coverage_reports_requirement_without_decision_or_test(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "requirements.md").write_text("## REQ-001: identidad\n", encoding="utf-8")
            diagnostics = Resolver().resolve(ModelBuilder().build(root))
            self.assertEqual(
                {item.code for item in diagnostics},
                {"uncovered-requirement", "unverified-requirement"},
            )

    def test_duplicate_semantic_id_is_an_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "one.md").write_text("## REQ-001: uno\n", encoding="utf-8")
            (root / "two.md").write_text("## REQ-001: dos\n", encoding="utf-8")
            codes = [item.code for item in Resolver().resolve(ModelBuilder().build(root))]
            self.assertIn("duplicate-semantic-id", codes)

    def test_code_fences_and_external_links_are_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text(
                "[Web](https://example.com)\n```md\n[roto](missing.md)\n```\n", encoding="utf-8"
            )
            self.assertEqual(Resolver().resolve(ModelBuilder().build(root)), [])

    def test_root_relative_link_and_non_markdown_asset(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "docs").mkdir()
            (root / "docs" / "image.png").write_bytes(b"png")
            (root / "README.md").write_text(
                "![Imagen](/docs/image.png)\n[Inicio](/README.md)\n", encoding="utf-8"
            )
            self.assertEqual(Resolver().resolve(ModelBuilder().build(root)), [])

    def test_link_outside_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            root.mkdir()
            (root.parent / "secret.md").write_text("# Fuera\n", encoding="utf-8")
            (root / "README.md").write_text("[Fuera](../secret.md)\n", encoding="utf-8")
            diagnostics = Resolver().resolve(ModelBuilder().build(root))
            self.assertEqual([item.code for item in diagnostics], ["outside-root"])

    def test_missing_generated_build_artifact_is_allowed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text(
                "[Bitstream](_build/default/hardware.bit)\n", encoding="utf-8"
            )
            self.assertEqual(Resolver().resolve(ModelBuilder().build(root)), [])

    def test_cli_check_exit_codes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            readme = root / "README.md"
            readme.write_text("# Bien\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["check", "--root", str(root)]), 0)
            readme.write_text("[Roto](missing.md)\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["check", "--root", str(root)]), 1)

    def test_bundled_example_resolves_end_to_end(self):
        example = REPO / "tools" / "traceability" / "example"
        model = ModelBuilder().build(REPO, [example])
        self.assertEqual(Resolver().resolve(model), [])
        self.assertEqual(len(model.observations), 9)

    def test_example_builds_typed_relations(self):
        example = REPO / "tools" / "traceability" / "example"
        analysis = Resolver().analyze(ModelBuilder().build(REPO, [example]))
        triples = {
            (item.source.semantic_id, item.kind, item.target.semantic_id)
            for item in analysis.relations
        }
        self.assertIn(("DEC-001", "satisfies", "REQ-001"), triples)
        self.assertIn(("TEST-001", "verifies", "REQ-001"), triples)
        self.assertIn(("REQ-001", "specified-by", "DEC-001"), triples)

    def test_cli_show_explains_identity_connections(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["show", "req-001", "--root", str(REPO)])
        self.assertEqual(code, 0)
        self.assertIn("REQ-001 [requirement]", output.getvalue())
        self.assertIn("specified-by -> DEC-001", output.getvalue())
        self.assertIn("verified-by -> TEST-001", output.getvalue())

    def test_cli_show_reports_unknown_identity(self):
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            code = main(["show", "REQ-999", "--root", str(REPO)])
        self.assertEqual(code, 1)
        self.assertIn("no existe la identidad", error.getvalue())


if __name__ == "__main__":
    unittest.main()
