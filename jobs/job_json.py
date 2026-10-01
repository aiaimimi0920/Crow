"""Readable legacy job snapshots without backtracking over numeric arrays."""

import json


def format_job_json(data: object) -> str:
    """Keep nonnegative integer arrays compact in linear time after encoding."""
    lines = json.dumps(data, ensure_ascii=False, indent=2).splitlines()
    output = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.rstrip().endswith("["):
            end = index + 1
            values = []
            while end < len(lines):
                item = lines[end].strip().removesuffix(",")
                if not (item.isascii() and item.isdecimal()):
                    break
                values.append(item)
                end += 1
            closing = lines[end].strip() if end < len(lines) else ""
            if values and closing in {"]", "],"}:
                output.append(line + ", ".join(values) + closing)
                index = end + 1
                continue
        output.append(line)
        index += 1
    return "\n".join(output)
