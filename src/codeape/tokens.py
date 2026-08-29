from __future__ import annotations

import re

TOKEN_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+(?:\.[0-9]+)?|[^\w\s]+"
)


def tab_target(line: str, col: int) -> int | None:
    """Return the column to jump to on Tab, or None if Tab is a no-op."""
    if col < 0 or col > len(line):
        return None
    leading = len(line) - len(line.lstrip(" \t"))
    if col < leading:
        return leading
    for match in TOKEN_RE.finditer(line):
        if match.start() == col:
            return match.end()
        if match.start() > col:
            break
    return None
