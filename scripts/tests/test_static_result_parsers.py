"""Check findings/tool-failure separation without running the product suites."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from static_result_parsers import classify, effective_findings
from report_secret_scan import inventory

ROOT = Path.cwd()


class StaticParserTests(unittest.TestCase):
    def test_json_lint_findings_are_locations_only(self):
        data = [{"filename": "src/example.py", "location": {"row": 1}, "code": "F401",
                 "message": "PRIVATE_CANARY", "fix": {"content": "PRIVATE_CANARY"}}]
        rows = classify("ruff", 1, json.dumps(data), "", ROOT)
        self.assertEqual(rows, [{"file": "src/example.py", "line": 1, "code": "F401"}])
        self.assertNotIn("PRIVATE_CANARY", json.dumps(rows))

    def test_mypy_and_typescript_semantic_findings(self):
        self.assertEqual(classify("mypy", 0, "\n", "", ROOT), [])
        data = {"file": "src/example.py", "line": 2, "code": "assignment", "severity": "error"}
        self.assertEqual(len(classify("mypy", 1, json.dumps(data), "", ROOT)), 1)
        self.assertEqual(len(classify("tsc", 1, "src/example.ts(2,3): error TS2322: type mismatch\n", "", ROOT)), 1)

    def test_syntax_infrastructure_and_corrupt_outputs_fail(self):
        cases = [("ruff", 1, "{", ""), ("ruff", 2, "[]", ""),
                 ("ruff", 1, "[]", ""), ("ruff", 0, "[]", "tool warning"),
                 ("mypy", 1, '{"file":"x.py","line":1,"severity":"error","code":"syntax"}', ""),
                 ("tsc", 1, "x.ts(1,1): error TS1005: syntax\n", ""),
                 ("tsc", 2, "x.ts(1,1): error TS2322: type mismatch\n", ""),
                 ("tsc", 2, "error TS5058: missing config\n", ""),
                 ("rustfmt", 1, "", "cannot parse"), ("oxlint", 1, "{}", "")]
        for kind, status, out, err in cases:
            with self.subTest(kind=kind, output=out), self.assertRaises((ValueError, KeyError)):
                classify(kind, status, out, err, ROOT)

    def test_formatter_diff_requires_successful_tool(self):
        out = "Diff in src/main.rs:1:\n-fn main( ){}\n+fn main() {}\n"
        self.assertEqual(len(classify("rustfmt", 1, out, "", ROOT)), 1)
        with self.assertRaises(ValueError):
            classify("rustfmt", 2, out, "", ROOT)

    def test_oxlint_requires_diagnostics(self):
        diagnostic = {"severity": "warning", "code": "eslint(no-unused-vars)",
                      "filename": "src/example.ts", "labels": [{"span": {"line": 1}}]}
        self.assertEqual(len(classify("oxlint", 1, json.dumps({"diagnostics": [diagnostic]}), "", ROOT)), 1)

    def test_size_findings_not_generation_errors(self):
        payload = {"schemaVersion": 1, "checkerVersion": 2, "mode": "ratchet",
                   "summary": {"scanned": 1}, "violations": ["src/a.py: oversized baseline file changed before reaching 700 lines"]}
        self.assertEqual(len(effective_findings(payload, 1, ROOT)), 1)
        payload["violations"] = ["generated source is inconsistent"]
        with self.assertRaises(ValueError):
            effective_findings(payload, 1, ROOT)

    def test_secret_inventory_drops_match_and_secret(self):
        rows = inventory([{"RuleID": "generic-api-key", "Secret": "REDACTED", "Match": "PRIVATE_CANARY",
                           "File": str(ROOT / "a.py"), "StartLine": 3}], ROOT)
        self.assertEqual(len(rows), 1)
        self.assertNotIn("PRIVATE_CANARY", json.dumps(rows))
        self.assertNotIn("REDACTED", json.dumps(rows))


if __name__ == "__main__":
    unittest.main()
