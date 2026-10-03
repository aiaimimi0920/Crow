"""Validate scan outputs before treating finding exit codes as advisory."""

import json
import hashlib
from pathlib import Path
import re

LOCKFILES = {
    "requirements.lock", "requirements-dev.lock",
    "collector-desktop/package-lock.json", "collector-desktop/src-tauri/Cargo.lock",
    "game/web-app/package-lock.json",
}


def require(condition):
    if not condition:
        raise ValueError("invalid_scan_result")


def read_json(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink())
    require(0 < path.stat().st_size <= 100 * 1024 * 1024)
    return json.loads(path.read_text(encoding="utf-8"))


def _package_label(info):
    require(isinstance(info, dict))
    commit = info.get("commit", "")
    require(isinstance(commit, str))
    name = info.get("name", "")
    require(isinstance(name, str))
    if commit:
        require(re.fullmatch(r"[0-9a-fA-F]{7,64}", commit))
        return name + "@" + commit[:8] if name else commit
    require(all(isinstance(info.get(key), str) and info[key]
                for key in ("name", "version", "ecosystem")))
    return name + "@" + info["version"]


def osv_findings(payload):
    require(isinstance(payload, dict))
    sources = payload.get("results")
    require(isinstance(sources, list) and bool(sources))
    seen, identifiers = set(), set()
    for source in sources:
        require(isinstance(source, dict) and isinstance(source.get("source"), dict))
        location = source["source"].get("path")
        require(isinstance(location, str))
        location = location.removeprefix("/github/workspace/").removeprefix("./")
        require(location in LOCKFILES and location not in seen)
        seen.add(location)
        packages = source.get("packages")
        require(isinstance(packages, list) and bool(packages))
        for package in packages:
            require(isinstance(package, dict) and isinstance(package.get("package"), dict))
            _package_label(package["package"])
            vulns = package.get("vulnerabilities", [])
            require(isinstance(vulns, list))
            for vuln in vulns:
                require(isinstance(vuln, dict))
                identifier = vuln.get("id")
                require(isinstance(identifier, str) and
                        re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,149}", identifier))
                identifiers.add(identifier)
    require(seen == LOCKFILES)
    return identifiers


def _sarif_rows(payload):
    require(isinstance(payload, dict) and payload.get("version") == "2.1.0")
    runs = payload.get("runs")
    require(isinstance(runs, list) and bool(runs))
    rows = set()
    for run in runs:
        require(isinstance(run, dict))
        require(run.get("tool", {}).get("driver", {}).get("name") == "osv-scanner")
        rules = run["tool"]["driver"].get("rules")
        require(isinstance(rules, list))
        indexed = {}
        for rule in rules:
            require(isinstance(rule, dict) and isinstance(rule.get("id"), str))
            aliases = rule.get("deprecatedIds")
            require(isinstance(aliases, list) and bool(aliases))
            require(all(isinstance(alias, str) for alias in aliases))
            require(aliases[0] == rule["id"] and rule["id"] not in indexed)
            require(len(set(aliases)) == len(aliases))
            indexed[rule["id"]] = aliases
        invocations = run.get("invocations", [])
        require(isinstance(invocations, list))
        for invocation in invocations:
            require(isinstance(invocation, dict) and invocation.get("executionSuccessful") is True)
            for key in ("toolExecutionNotifications", "toolConfigurationNotifications"):
                notifications = invocation.get(key, [])
                require(isinstance(notifications, list))
                require(all(isinstance(n, dict) and n.get("level", "warning") in
                            {"none", "note", "warning"} for n in notifications))
        results = run.get("results")
        require(isinstance(results, list))
        for result in results:
            require(isinstance(result, dict) and result.get("ruleId") in indexed)
            identifier = result["ruleId"]
            index = result.get("ruleIndex")
            require(type(index) is int and 0 <= index < len(rules))
            require(rules[index]["id"] == identifier)
            aliases = indexed[identifier]
            message = result.get("message", {}).get("text")
            require(isinstance(message, str))
            match = re.fullmatch(r"Package '(.+)' is vulnerable to '([^']+)'(?: \(also known as .+\))?\.", message)
            require(match is not None and match[2] == identifier)
            package = match[1]
            suffix = " (also known as '" + "', '".join(aliases[1:]) + "')" if len(aliases) > 1 else ""
            require(message == f"Package '{package}' is vulnerable to '{identifier}'{suffix}.")
            locations = result.get("locations")
            require(isinstance(locations, list) and len(locations) == 1)
            location = locations[0]["physicalLocation"]["artifactLocation"]["uri"]
            require(location in LOCKFILES)
            fingerprint = hashlib.sha256(f"{identifier}:{location}:{package}".encode()).hexdigest()
            require(result.get("partialFingerprints", {}).get("primaryLocationLineHash") == fingerprint)
            rows.add((frozenset(aliases), location, package, identifier))
    return rows


def sarif_findings(payload):
    return {row[3] for row in _sarif_rows(payload)}


def validate_osv_sarif(scan, sarif):
    """Match v2.6.0 alias groups and every distinct package/source finding.

    Upstream output/result.go groups by package.groups[].ids across sources,
    then unions vulnerability IDs/aliases. output/sarif.go emits each package
    at each source, possibly repeatedly for aliased IDs. Duplicate identical
    results are immaterial; losing a distinct package or lockfile is not.
    """
    identifiers = osv_findings(scan)
    parents, entries = {}, []

    def find(value):
        parents.setdefault(value, value)
        if parents[value] != value:
            parents[value] = find(parents[value])
        return parents[value]

    for source in scan["results"]:
        path = source["source"]["path"].removeprefix("/github/workspace/").removeprefix("./")
        for package in source["packages"]:
            vulns = package.get("vulnerabilities", [])
            groups = package.get("groups", [])
            require(isinstance(groups, list))
            covered = set()
            for group in groups:
                require(isinstance(group, dict) and isinstance(group.get("ids"), list) and group["ids"])
                group_ids = group["ids"]
                require(all(isinstance(value, str) and value in identifiers for value in group_ids))
                require(not covered.intersection(group_ids) and len(set(group_ids)) == len(group_ids))
                covered.update(group_ids)
                for value in group_ids[1:]:
                    parents[find(value)] = find(group_ids[0])
            require(covered == {v["id"] for v in vulns})
            display = _package_label(package["package"])
            for vuln in vulns:
                aliases = vuln.get("aliases", [])
                require(isinstance(aliases, list) and all(isinstance(a, str) for a in aliases))
                entries.append((vuln["id"], {vuln["id"], *aliases}, path, display))
    all_aliases = {}
    for identifier, aliases, _, _ in entries:
        all_aliases.setdefault(find(identifier), set()).update(aliases)
    expected = {(frozenset(all_aliases[find(identifier)]), path, package)
                for identifier, _, path, package in entries}
    actual = {(aliases, path, package) for aliases, path, package, _ in _sarif_rows(sarif)}
    require(actual == expected)
    return identifiers


def validate_exit(status, finding_count):
    require(type(status) is int and status in (0, 1))
    require(status == (1 if finding_count else 0))


def osv_reporter_finding_count(payload):
    """v2.6.0 reporter exit uses GroupInfo.IsCalled, even with --all-vulns.

    No analysis means called. Otherwise at least one analysis must say called.
    Unimportant findings remain in the full report and do not change this test.
    Release enforcement independently considers every retained advisory ID.
    """
    osv_findings(payload)
    count = 0
    for source in payload["results"]:
        for package in source["packages"]:
            require(not package.get("license_violations") and not package["package"].get("deprecated", False))
            vulns = {v["id"] for v in package.get("vulnerabilities", [])}
            covered = set()
            for group in package.get("groups", []):
                ids = group.get("ids")
                require(isinstance(ids, list) and all(isinstance(value, str) for value in ids))
                require(set(ids) <= vulns)
                covered.update(ids)
                analyses = group.get("experimental_analysis", {})
                require(isinstance(analyses, dict))
                for analysis in analyses.values():
                    require(isinstance(analysis, dict))
                    require(type(analysis.get("called", False)) is bool)
                    require(type(analysis.get("unimportant", False)) is bool)
                called = not analyses or any(a.get("called", False) for a in analyses.values())
                count += len(ids) if called else 0
            require(covered == vulns)
    return count


def secret_findings(payload):
    require(isinstance(payload, list))
    for item in payload:
        require(isinstance(item, dict))
        require(isinstance(item.get("RuleID"), str) and bool(item["RuleID"]))
        require(item.get("Secret") == "REDACTED")
        require(isinstance(item.get("Match"), str))
    return len(payload)
