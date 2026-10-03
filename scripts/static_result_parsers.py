"""Fail closed on malformed tool output; publish locations/codes, never snippets."""
import json
from pathlib import Path
import re

from security_scan_results import require, validate_exit


def location(file, line, code, root):
    require(isinstance(file, str) and isinstance(code, str))
    require(re.fullmatch(r"[A-Za-z0-9_./()-]{1,150}", code))
    require(type(line) is int and line >= 0)
    path = Path(file.removeprefix("\\\\?\\"))
    if path.is_absolute():
        path = path.relative_to(root)
    require(".." not in path.parts)
    name = path.as_posix()
    require(re.fullmatch(r"[A-Za-z0-9_./ -]{1,500}", name))
    return {"file": name, "line": line, "code": code}


def parse_ruff(stdout, root):
    data = json.loads(stdout)
    require(isinstance(data, list))
    rows = []
    for item in data:
        require(isinstance(item, dict) and isinstance(item.get("location"), dict))
        code = item.get("code")
        # Invalid syntax has no lint code and must remain an execution failure.
        require(isinstance(code, str) and code not in {"invalid-syntax", "E999"})
        rows.append(location(item["filename"], item["location"]["row"], code, root))
    return rows


def parse_mypy(stdout, root):
    rows = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        require(isinstance(item, dict) and item.get("severity") in {"error", "note"})
        if item["severity"] == "note":
            continue
        require(item.get("code") not in {None, "syntax"})
        rows.append(location(item["file"], item["line"], item["code"], root))
    return rows


def parse_oxlint(stdout, root):
    data = json.loads(stdout)
    require(isinstance(data, dict) and isinstance(data.get("diagnostics"), list))
    rows = []
    for item in data["diagnostics"]:
        require(isinstance(item, dict) and item.get("severity") in {"error", "warning"})
        code = item.get("code")
        require(isinstance(code, str) and bool(code))
        require(not code.lower().startswith(("parse", "syntax", "oxc")))
        labels = item.get("labels")
        require(isinstance(labels, list) and bool(labels))
        rows.append(location(item["filename"], labels[0]["span"]["line"], code, root))
    return rows


def parse_rustfmt(stdout, root):
    # --check exits 1 for a diff; parsing/execution failures use stderr or an unknown exit.
    rows = []
    for block in re.split(r"(?m)^Diff in ", stdout)[1:]:
        header, _, body = block.partition("\n")
        match = re.fullmatch(r"(.+):(\d+):", header)
        require(match is not None and bool(body.strip()))
        rows.append(location(match[1], int(match[2]), "rustfmt", root))
    require(not stdout or stdout.startswith("Diff in "))
    return rows


def parse_tsc(stdout, root):
    rows = []
    for line in stdout.splitlines():
        if line.startswith("  ") and rows:
            continue
        match = re.fullmatch(r"(.+)\((\d+),(\d+)\): error TS(\d+): .+", line)
        require(match is not None)
        code = int(match[4])
        # Syntax and compiler/configuration diagnostics are not advisory findings.
        require(2000 <= code < 5000)
        rows.append(location(match[1], int(match[2]), "TS" + match[4], root))
    return rows


def classify(kind, status, stdout, stderr, root):
    require(not stderr.strip())
    parsers = {"ruff": parse_ruff, "mypy": parse_mypy, "oxlint": parse_oxlint,
               "rustfmt": parse_rustfmt, "tsc": parse_tsc}
    rows = parsers[kind](stdout, root)
    # The pinned TypeScript 7.0.2 uses 1 for diagnostics; syntax codes still fail above.
    validate_exit(status, len(rows))
    return rows


def effective_findings(payload, status, root):
    require(isinstance(payload, dict) and payload.get("schemaVersion") == 1)
    require(payload.get("checkerVersion") == 2 and payload.get("mode") == "ratchet")
    require(isinstance(payload.get("summary"), dict) and payload["summary"].get("scanned", 0) > 0)
    violations = payload.get("violations")
    require(isinstance(violations, list))
    rows = []
    for violation in violations:
        require(isinstance(violation, str))
        match = re.fullmatch(r"(.+): (?:oversized baseline file changed before reaching 700 lines|\d+ lines requires a current 501-700 exception)", violation)
        # Generation/lexing/baseline diagnostics are not ordinary size findings.
        require(match is not None)
        rows.append(location(match[1], 0, "effective-lines", root))
    validate_exit(status, len(rows))
    return rows
