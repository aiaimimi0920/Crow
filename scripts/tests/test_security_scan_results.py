"""Advisory success requires complete evidence and the precise finding exit."""
import copy
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_osv_scan as runner
from security_scan_results import LOCKFILES, osv_findings, osv_reporter_finding_count, sarif_findings, secret_findings, validate_exit, validate_osv_sarif


def result(finding=True):
    payload = {"results": [{"source": {"path": "/github/workspace/" + name, "type": "lockfile"},
        "packages": [{"package": {"name": "example", "version": "1", "ecosystem": "PyPI"},
                      "vulnerabilities": []}]} for name in sorted(LOCKFILES)]}
    if finding:
        payload["results"][0]["packages"][0]["vulnerabilities"] = [{"id": "RUSTSEC-2024-0429"}]
        payload["results"][0]["packages"][0]["groups"] = [{"ids": ["RUSTSEC-2024-0429"]}]
    return payload


def sarif(finding=True):
    identifier = "RUSTSEC-2024-0429"
    location = sorted(LOCKFILES)[0]
    fingerprint = hashlib.sha256(f"{identifier}:{location}:example@1".encode()).hexdigest()
    return {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "osv-scanner",
        "rules": [{"id": identifier, "deprecatedIds": [identifier]}] if finding else []}},
        "results": [{"ruleId": identifier, "ruleIndex": 0,
                     "message": {"text": f"Package 'example@1' is vulnerable to '{identifier}'."},
                     "partialFingerprints": {"primaryLocationLineHash": fingerprint},
                     "locations": [{"physicalLocation": {"artifactLocation": {"uri": location}}}]}]
                     if finding else [], "invocations": []}]}


class ResultTests(unittest.TestCase):
    def test_clean_and_finding_exits(self):
        for finding in (False, True):
            self.assertEqual(len(osv_findings(result(finding))), int(finding))
            self.assertEqual(len(sarif_findings(sarif(finding))), int(finding))
            validate_exit(int(finding), int(finding))

    def test_unknown_and_inconsistent_exits_fail(self):
        for status, count in [(2, 1), (3, 0), (125, 1), (128, 0), (128, 1), (-9, 1), (True, 1), (1, 0), (0, 1)]:
            with self.subTest(status=status, count=count), self.assertRaises(ValueError):
                validate_exit(status, count)

    def test_missing_or_partial_results_fail(self):
        for data in ({}, {"results": []}, {"results": None}, {"results": result()["results"][:-1]}):
            with self.assertRaises(ValueError):
                osv_findings(data)

    def test_invalid_findings_and_duplicate_source_fail(self):
        data = result()
        data["results"][0]["packages"][0]["vulnerabilities"] = [{"id": "bad\nsecret"}]
        with self.assertRaises(ValueError):
            osv_findings(data)
        data = result()
        data["results"].append(copy.deepcopy(data["results"][0]))
        with self.assertRaises(ValueError):
            osv_findings(data)

    def test_failed_sarif_diagnostics_fail(self):
        for invocation in ({"executionSuccessful": False}, {"executionSuccessful": True,
            "toolConfigurationNotifications": [{"level": "error"}]}):
            data = sarif()
            data["runs"][0]["invocations"] = [invocation]
            with self.assertRaises(ValueError):
                sarif_findings(data)

    def test_secrets_require_redaction(self):
        self.assertEqual(secret_findings([]), 0)
        self.assertEqual(secret_findings([{"RuleID": "test", "Secret": "REDACTED", "Match": "x"}]), 1)
        with self.assertRaises(ValueError):
            secret_findings([{"RuleID": "test", "Secret": "do-not-print", "Match": "x"}])

    def test_runner_validates_real_files_and_release_gate(self):
        for finding in (False, True):
            with tempfile.TemporaryDirectory() as temp:
                output = Path(temp) / "osv"
                def execute(command):
                    if command[1] == "pull":
                        return 0
                    name = "results.sarif" if "/root/osv-reporter" in command else "results.json"
                    if name == "results.json":
                        self.assertIn("/root/osv-scanner", command)
                        self.assertIn("--all-vulns", command)
                        self.assertEqual(command[command.index(runner.IMAGE) + 1:][:2], ["scan", "source"])
                    else:
                        self.assertIn("--all-vulns", command[-1].splitlines())
                    data = sarif(finding) if name.endswith("sarif") else result(finding)
                    (output / name).write_text(json.dumps(data), encoding="utf-8")
                    return int(finding)
                with patch.object(runner, "execute", side_effect=execute), patch.object(runner, "probe_version"):
                    self.assertEqual(len(runner.scan(output)), int(finding))
                process = subprocess.run([sys.executable, str(Path(runner.__file__)), "enforce", str(output)],
                                         capture_output=True, text=True)
                self.assertEqual(process.returncode, int(finding))
                with self.assertRaises(FileExistsError):
                    runner.scan(output)

    def test_missing_corrupt_and_mismatched_evidence_fail(self):
        for contents in (None, "", "{", "{}", json.dumps(result())):
            with tempfile.TemporaryDirectory() as temp:
                output = Path(temp)
                if contents is not None:
                    (output / "results.json").write_text(contents)
                process = subprocess.run([sys.executable, str(Path(runner.__file__)), "enforce", str(output)],
                                         capture_output=True, text=True)
                self.assertEqual(process.returncode, 2)
                self.assertNotIn("Traceback", process.stderr)

    def test_pull_failure_and_unknown_scanner_exit_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(runner, "execute", return_value=125), self.assertRaises(ValueError):
                runner.scan(Path(temp) / "pull-failed")
            output = Path(temp) / "unknown"
            def execute(command):
                if command[1] == "pull":
                    return 0
                (output / "results.json").write_text(json.dumps(result()))
                return 128
            with patch.object(runner, "execute", side_effect=execute), patch.object(runner, "probe_version"), self.assertRaises(ValueError):
                runner.scan(output)

    def test_missing_package_or_lock_is_rejected_even_with_same_id(self):
        for another_lock in (False, True):
            data = result()
            package = copy.deepcopy(data["results"][0]["packages"][0])
            if another_lock:
                data["results"][1]["packages"].append(package)
            else:
                package["package"]["name"] = "other"
                data["results"][0]["packages"].append(package)
            with self.assertRaises(ValueError):
                validate_osv_sarif(data, sarif())

    def test_alias_group_and_duplicate_results_are_supported(self):
        data, report = result(), sarif()
        package = data["results"][0]["packages"][0]
        package["vulnerabilities"].append({"id": "GHSA-test-test-test", "aliases": ["RUSTSEC-2024-0429"]})
        package["groups"][0]["ids"].append("GHSA-test-test-test")
        rule = report["runs"][0]["tool"]["driver"]["rules"][0]
        rule["deprecatedIds"].append("GHSA-test-test-test")
        item = report["runs"][0]["results"][0]
        item["message"]["text"] = "Package 'example@1' is vulnerable to 'RUSTSEC-2024-0429' (also known as 'GHSA-test-test-test')."
        report["runs"][0]["results"].append(copy.deepcopy(item))
        self.assertEqual(len(validate_osv_sarif(data, report)), 2)
        rule["deprecatedIds"].append("CVE-2099-9999")
        with self.assertRaises(ValueError):
            validate_osv_sarif(data, report)

    def test_changed_location_package_and_rule_index_are_rejected(self):
        for field in ("location", "package", "ruleIndex"):
            report = sarif()
            item = report["runs"][0]["results"][0]
            if field == "location":
                item["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] = sorted(LOCKFILES)[1]
            elif field == "package":
                item["message"]["text"] = item["message"]["text"].replace("example@1", "other@2")
            else:
                item["ruleIndex"] = 99
            with self.assertRaises(ValueError):
                validate_osv_sarif(result(), report)

    def test_direct_binary_and_version_probe_contract(self):
        with patch.object(runner.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "osv-scanner version: 2.6.0\n", "")) as run:
            runner.probe_version(["docker", "run"])
            self.assertIn("/root/osv-scanner", run.call_args.args[0])
        for status, version in ((128, "2.6.0"), (0, "2.5.1")):
            with patch.object(runner.subprocess, "run", return_value=subprocess.CompletedProcess([], status, f"osv-scanner version: {version}\n", "")), self.assertRaises(ValueError):
                runner.probe_version(["docker", "run"])

    def test_all_findings_retained_with_official_reporter_analysis_exit(self):
        for analyses, reporter_exit in (({}, 1), ({"go": {"called": False}}, 0),
            ({"go": {"called": False, "unimportant": True}}, 0),
            ({"go": {"called": True, "unimportant": True}}, 1),
            ({"go": {"called": False}, "rust": {"called": True}}, 1)):
            data = result()
            data["results"][0]["packages"][0]["groups"][0]["experimental_analysis"] = analyses
            self.assertEqual(bool(osv_reporter_finding_count(data)), bool(reporter_exit))
            with tempfile.TemporaryDirectory() as temp:
                output = Path(temp)
                (output / "results.json").write_text(json.dumps(data))
                (output / "results.sarif").write_text(json.dumps(sarif()))
                (output / "status.json").write_text(json.dumps({"scanner": 1, "reporter": reporter_exit}))
                self.assertEqual(len(runner.validate_bundle(output)), 1)
                process = subprocess.run([sys.executable, str(Path(runner.__file__)), "enforce", str(output)],
                                         capture_output=True, text=True)
                self.assertEqual(process.returncode, 1)
                (output / "status.json").write_text(json.dumps({"scanner": 1, "reporter": 1 - reporter_exit}))
                with self.assertRaises(ValueError):
                    runner.validate_bundle(output)

    def test_malformed_analysis_cannot_claim_reporter_success(self):
        data = result()
        data["results"][0]["packages"][0]["groups"][0]["experimental_analysis"] = {"go": {"called": "false"}}
        with self.assertRaises(ValueError):
            osv_reporter_finding_count(data)


if __name__ == "__main__":
    unittest.main()
