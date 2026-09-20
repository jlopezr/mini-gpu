import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from tools.trace_cli import main
from tools.traceability import MarkdownAdapter, ModelBuilder, Resolver, SystemVerilogAdapter

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "tools" / "traceability" / "example"


class TraceabilityTest(unittest.TestCase):
    def write(self, root, name, text):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_plain_markdown_is_only_a_resource(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.write(root, "README.md", "# Documento\n[Otro](other.md)\n")
            result = MarkdownAdapter().read(path, root)
            self.assertEqual(result.resource.path, path)
            self.assertEqual(result.identities, ())
            self.assertEqual(result.observations, ())

    def test_artifact_has_explicit_case_sensitive_id_and_type(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.write(root, "req.md", """<!-- trace:artifact Req-Mixed
type: requirement
-->
# Requirement
""")
            artifact = MarkdownAdapter().read(path, root).identities[0]
            self.assertEqual((artifact.key, artifact.artifact_type), ("Req-Mixed", "requirement"))

    def test_sections_are_local_to_nearest_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.write(root, "spec.md", """<!-- trace:artifact SPEC-A
type: specification
-->
# Spec
## Derived title
### Stable title {#stable}
""")
            identities = MarkdownAdapter().read(path, root).identities
            self.assertEqual([item.key for item in identities], ["SPEC-A", "SPEC-A#derived-title", "SPEC-A#stable"])
            self.assertFalse(identities[1].formal)
            self.assertTrue(identities[2].formal)

    def test_artifact_relations_are_explicit_not_markdown_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.write(root, "impl.md", """<!-- trace:artifact IMPL-A
type: implementation
implements: [SPEC-A]
-->
# Impl
[ordinary link](somewhere.md)
""")
            result = MarkdownAdapter().read(path, root)
            self.assertEqual([(item.relation, item.target) for item in result.observations], [("implements", "SPEC-A")])

    def test_section_relations_require_formal_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.write(root, "spec.md", """<!-- trace:artifact SPEC-A
type: specification
-->
# Spec
<!-- trace:relations
derived-from: [DEC-A]
-->
## Unstable
""")
            result = MarkdownAdapter().read(path, root)
            self.assertEqual([item.code for item in result.diagnostics], ["relations-require-formal-id"])

    def test_local_reference_resolves_inside_current_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "spec.md", """<!-- trace:artifact SPEC-A
type: specification
requires: ["#base"]
-->
# Spec
## Base {#base}
""")
            analysis = Resolver().analyze(ModelBuilder().build(root))
            self.assertEqual(analysis.diagnostics, ())
            self.assertEqual(analysis.relations[0].target.key, "SPEC-A#base")

    def test_unknown_metadata_and_type_are_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "bad.md", """<!-- trace:artifact A
type: requirementt
subjets: [gpu]
-->
# Bad
""")
            codes = {item.code for item in Resolver().resolve(ModelBuilder().build(root))}
            self.assertEqual(codes, {"invalid-artifact-type", "unknown-metadata"})

    def test_extended_verifies_coverage_is_preserved(self):
        model = ModelBuilder().build(REPO, [EXAMPLE])
        relation = next(item for item in Resolver().analyze(model).relations
                        if item.source.key == "VER-DEVICE-IDENTITY" and item.target.key.startswith("SPEC-DEVICE#"))
        self.assertEqual(relation.attributes, {"coverage": "complete"})

    def test_facet_creates_local_identity_and_associated_section(self):
        model = ModelBuilder().build(REPO, [EXAMPLE])
        by_key = {item.key: item for item in model.identities}
        facet = by_key["SPEC-DEVICE@identity"]
        section = by_key["SPEC-DEVICE#identity"]
        register = by_key["SPEC-DEVICE#identity-register"]
        self.assertEqual((facet.element_type, facet.owner), ("facet", "SPEC-DEVICE"))
        self.assertEqual(section.parent_facet, facet.key)
        self.assertEqual(register.parent_facet, facet.key)

    def test_nested_facet_has_structural_parent(self):
        model = ModelBuilder().build(REPO, [EXAMPLE])
        by_key = {item.key: item for item in model.identities}
        nested = by_key["SPEC-DEVICE@versioning"]
        self.assertEqual(nested.parent_facet, "SPEC-DEVICE@identity")
        self.assertEqual(by_key["SPEC-DEVICE#versioning"].parent_facet, nested.key)

    def test_facet_scope_ends_at_same_level_heading(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "spec.md", """<!-- trace:artifact SPEC
type: specification
-->
# Spec
<!-- trace:facet calls
kind: capability
-->
## Calls {#calls}
### Inside
## Outside
""")
            by_key = {item.key: item for item in ModelBuilder().build(root).identities}
            self.assertEqual(by_key["SPEC#inside"].parent_facet, "SPEC@calls")
            self.assertIsNone(by_key["SPEC#outside"].parent_facet)

    def test_facet_requires_matching_formal_section_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "spec.md", """<!-- trace:artifact SPEC
type: specification
-->
# Spec
<!-- trace:facet calls
kind: capability
-->
## Calls {#other}
""")
            codes = [item.code for item in Resolver().resolve(ModelBuilder().build(root))]
            self.assertEqual(codes, ["facet-section-id-mismatch"])

    def test_facet_can_author_relations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "spec.md", """<!-- trace:artifact BASE
type: specification
-->
# Base
<!-- trace:artifact SPEC
type: specification
-->
# Spec
<!-- trace:facet calls
kind: capability
requires: [BASE]
-->
## Calls {#calls}
""")
            analysis = Resolver().analyze(ModelBuilder().build(root))
            self.assertEqual(analysis.diagnostics, ())
            relation = analysis.relations[0]
            self.assertEqual((relation.source.key, relation.kind, relation.target.key),
                             ("SPEC@calls", "requires", "BASE"))

    def test_generated_trace_directives_are_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "generated.md", """<!-- gendoc:begin slot
generator: test
-->
<!-- trace:artifact GENERATED
type: requirement
-->
# Generated
<!-- gendoc:end slot -->
""")
            self.assertEqual(ModelBuilder().build(root).identities, ())

    def test_trace_directives_inside_code_fences_are_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "guide.md", """```markdown
<!-- trace:artifact EXAMPLE
type: requirement
-->
# Example
```
""")
            self.assertEqual(ModelBuilder().build(root).identities, ())

    def test_duplicate_artifact_and_relation_are_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "a.md", """<!-- trace:artifact A
type: decision
addresses: [B, B]
-->
# A
""")
            self.write(root, "b.md", """<!-- trace:artifact B
type: requirement
-->
# B
<!-- trace:artifact A
type: decision
-->
## Duplicate
""")
            codes = {item.code for item in Resolver().resolve(ModelBuilder().build(root))}
            self.assertIn("duplicate-identity", codes)
            self.assertIn("duplicate-relation", codes)

    def test_example_resolves_to_authored_graph(self):
        model = ModelBuilder().build(REPO, [EXAMPLE])
        analysis = Resolver().analyze(model)
        self.assertEqual(analysis.diagnostics, ())
        triples = {(item.source.key, item.kind, item.target.key) for item in analysis.relations}
        self.assertEqual(len(triples), 6)
        self.assertIn(("IMPL-DEVICE-IDENTITY", "satisfies", "REQ-DEVICE-IDENTITY"), triples)
        self.assertIn(("IMPL-DEVICE-IDENTITY", "implements", "SPEC-DEVICE@identity"), triples)
        self.assertIn(("IMPL-DEVICE-IDENTITY::identity-read", "implements", "SPEC-DEVICE#identity-register"), triples)
        self.assertIn(("VER-DEVICE-IDENTITY", "verifies", "SPEC-DEVICE#identity-register"), triples)

    def test_systemverilog_artifact_and_formal_symbol(self):
        result = SystemVerilogAdapter().read(EXAMPLE / "implementation.sv", REPO)
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(
            [(item.key, item.element_type) for item in result.identities],
            [("IMPL-DEVICE-IDENTITY", "artifact"),
             ("IMPL-DEVICE-IDENTITY::identity-read", "symbol")],
        )
        self.assertTrue(result.identities[1].formal)

    def test_systemverilog_derived_symbol_and_separate_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.write(root, "impl.sv", """// @artifact IMPL type=implementation
module top;
endmodule
// @implements SPEC
module derived_name;
endmodule
// @id stable
// @implements SPEC
module renamed;
endmodule
""")
            result = SystemVerilogAdapter().read(path, root)
            self.assertEqual(result.diagnostics, ())
            self.assertEqual(
                [item.key for item in result.identities],
                ["IMPL", "IMPL::derived_name", "IMPL::stable"],
            )
            self.assertFalse(result.identities[1].formal)
            self.assertTrue(result.identities[2].formal)

    def test_systemverilog_binding_break_is_diagnostic(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.write(root, "impl.sv", """// @artifact IMPL type=implementation
`ifdef FPGA
module top;
endmodule
""")
            result = SystemVerilogAdapter().read(path, root)
            self.assertEqual([item.code for item in result.diagnostics], ["annotation-binding"])

    def test_unannotated_systemverilog_is_only_a_resource(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.write(root, "plain.sv", "module plain; endmodule\n")
            result = SystemVerilogAdapter().read(path, root)
            self.assertEqual(result.identities, ())
            self.assertEqual(result.observations, ())

    def test_unknown_systemverilog_annotation_is_error_but_email_is_not(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self.write(root, "plain.sv", """// contact dev@example.com
// @unknown TARGET
module plain;
endmodule
""")
            result = SystemVerilogAdapter().read(path, root)
            self.assertEqual([item.code for item in result.diagnostics], ["unknown-annotation"])

    def test_cli_show_is_exact_and_calculates_inverse_view(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["show", "REQ-DEVICE-IDENTITY", "--root", str(REPO)])
        self.assertEqual(code, 0)
        self.assertIn("REQ-DEVICE-IDENTITY [requirement]", output.getvalue())
        self.assertIn("<- satisfies IMPL-DEVICE-IDENTITY", output.getvalue())
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            self.assertEqual(main(["show", "req-device-identity", "--root", str(REPO)]), 1)

    def test_trace_yaml_controls_scan_and_exclude(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "trace.yaml", """project: demo
version: 1
scan: [docs/**/*.md]
exclude: [docs/private/**]
""")
            self.write(root, "docs/public/spec.md", "# Public\n")
            self.write(root, "docs/private/secret.md", "# Secret\n")
            self.write(root, "README.md", "# Outside scan\n")
            model = ModelBuilder().build(root)
            self.assertEqual(model.config.project, "demo")
            self.assertEqual(
                [item.path.relative_to(root).as_posix() for item in model.resources],
                ["docs/public/spec.md"],
            )

    def test_trace_yaml_unknown_field_and_version_are_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "trace.yaml", """project: demo
version: 2
scna: [docs/**]
""")
            codes = {item.code for item in Resolver().resolve(ModelBuilder().build(root))}
            self.assertEqual(codes, {"unknown-config-field", "unsupported-config-version"})

    def test_explicit_path_cannot_bypass_project_discovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "trace.yaml", "scan: [docs/**/*.md]\nexclude: []\n")
            outside = self.write(root, "README.md", "# Outside\n")
            with self.assertRaisesRegex(ValueError, "fuera de scan/exclude"):
                ModelBuilder().build(root, [outside])

    def test_trace_yaml_patterns_cannot_escape_project_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write(root, "trace.yaml", "scan: [../*.md]\nexclude: []\n")
            diagnostics = Resolver().resolve(ModelBuilder().build(root))
            self.assertEqual([item.code for item in diagnostics], ["invalid-config"])


if __name__ == "__main__":
    unittest.main()
