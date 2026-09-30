"""Validate declarative shell env files and emit names only, never their values."""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ASSIGNMENT = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_REFERENCE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*\})")


def declared_names(text: str) -> list[str]:
    if any(char in text for char in ("\x00", "\r", "\ufeff")):
        raise ValueError("Shell environment files require plain UTF-8 LF text")
    names = []
    for raw in text.split("\n"):
        line = raw.strip(" \t")
        if not line or line.startswith("#"):
            continue
        match = _ASSIGNMENT.fullmatch(line)
        if match is None:
            raise ValueError(
                "Environment file requires literal assignment declarations"
            )
        name, value = match.groups()
        if name.startswith("_crow_") or name in {
            "IFS",
            "BASH_ENV",
            "ENV",
            "SHELLOPTS",
            "BASHOPTS",
            "PS4",
            "BASH_XTRACEFD",
            "CDPATH",
        }:
            raise ValueError(
                "Shell control variables are unsupported in environment files"
            )
        quote = ""
        position = 0
        while position < len(value):
            char = value[position]
            if char == "\\" and quote != "'":
                position += 2
                if position > len(value):
                    raise ValueError("Environment file continuations are unsupported")
                continue
            if char in "\"'" and (not quote or quote == char):
                quote = "" if quote else char
            elif quote != "'" and char == "$":
                reference = _REFERENCE.match(value, position)
                if reference is None:
                    raise ValueError(
                        "Environment file supports simple variable references only"
                    )
                position = reference.end()
                continue
            elif quote != "'" and char == "`":
                raise ValueError("Environment file command substitution is unsupported")
            elif not quote and char.isspace():
                if (
                    value[position:].strip().startswith("#")
                    or not value[position:].strip()
                ):
                    break
                raise ValueError("Environment file whitespace values require quotes")
            elif not quote and char in ";|&<>(){}":
                raise ValueError("Environment file compound commands are unsupported")
            position += 1
        if quote:
            raise ValueError("Environment file multiline quotes are unsupported")
        if name.startswith(("CROW_", "FAPAI_")):
            names.append(name)
    return names


def main() -> int:
    try:
        text = Path(sys.argv[1]).read_bytes().decode("utf-8")
        names = declared_names(text)
        if sys.argv[2:] not in ([], ["--legacy-container-env"]):
            raise ValueError("Unknown shell environment validation mode")
        if sys.argv[2:] == ["--legacy-container-env"]:
            canonical = [name for name in names if name.startswith("CROW_")]
            if canonical:
                replacements = [name + " -> FAPAI_" + name[5:] for name in canonical]
                print(
                    "Container env_file retains legacy wire keys: "
                    + ", ".join(replacements),
                    file=sys.stderr,
                )
                return 2
    except (IndexError, OSError, UnicodeError, ValueError):
        print(
            "Unsupported declarative environment file; no settings were sourced",
            file=sys.stderr,
        )
        return 2
    print("\n".join(names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
