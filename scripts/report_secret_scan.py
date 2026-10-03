"""Retain actionable finding inventory without source snippets or secret values."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from security_scan_results import read_json, require, secret_findings, validate_exit


def inventory(payload, root):
    secret_findings(payload)
    rows = []
    for finding in payload:
        rule = finding["RuleID"]
        require(re.fullmatch(r"[a-z0-9-]{1,100}", rule))
        file = Path(finding["File"]).resolve().relative_to(root.resolve()).as_posix()
        require(re.fullmatch(r"[A-Za-z0-9_./ -]{1,500}", file) and ".." not in file.split("/"))
        line = finding["StartLine"]
        require(type(line) is int and line > 0)
        identity = hashlib.sha256(f"{rule}:{file}:{line}".encode()).hexdigest()
        rows.append({"rule": rule, "file": file, "line": line, "fingerprint": identity})
    return rows


def main(argv):
    try:
        if len(argv) == 2 and argv[0] == "--enforce":
            rows = read_json(argv[1])
            require(isinstance(rows, list))
            for row in rows:
                require(isinstance(row, dict) and set(row) == {"rule", "file", "line", "fingerprint"})
            return 1 if rows else 0
        require(len(argv) == 4 and argv[2] in {"strict", "advisory"})
        payload = read_json(argv[0])
        count = secret_findings(payload)
        validate_exit(int(argv[1]), count)
        rows = inventory(payload, Path(argv[3]))
        target = os.environ.get("GITLEAKS_REPORT_PATH")
        if target:
            output = Path(target)
            output.parent.mkdir(parents=True, exist_ok=True)
            require(not output.exists())
            output.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        message = f"Secret scan: valid redacted result, {count} findings. No secret values are included.\n"
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
                stream.write("### Secret finding inventory\n\n" + message)
                stream.write("See the Secret finding inventory artifact for all locations.\n")
        print(message.strip())
        return 1 if count and argv[2] == "strict" else 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        print("::error::Secret scan or redacted report validation failed.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
