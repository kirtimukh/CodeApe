from __future__ import annotations

import re

from rich.console import Console
from rich.text import Text

from codeape.session import ViewLine
from codeape.tui import palette as pal

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
GUTTER_CELLS = 2
_MEASURE = Console(width=120, legacy_windows=False, force_terminal=True)


def line_visual_height(plain: str, width: int) -> int:
    """Visual rows of a hunk line at ``width``, matching Textual's Text wrap."""
    if width <= 0:
        return 1
    wrapped = Text(plain).wrap(_MEASURE, width, tab_size=8)
    return max(1, len(wrapped))


def line_source(line: ViewLine) -> str:
    if line.kind == "ADD":
        return line.typing + line.comment_suffix
    return line.display


def identifier_at(text: str, col: int) -> str:
    """Identifier under ``col``, or empty if that cell is not an identifier."""
    if not text:
        return ""
    i = col if col < len(text) else len(text) - 1
    if i < 0 or not _ident_char(text[i]):
        return ""
    start = i
    while start > 0 and _ident_char(text[start - 1]):
        start -= 1
    end = i + 1
    while end < len(text) and _ident_char(text[end]):
        end += 1
    token = text[start:end]
    return token if _IDENT.fullmatch(token) else ""


def match_count(source: str, term: str) -> int:
    if not term:
        return 0
    return len(re.findall(rf"\b{re.escape(term)}\b", source))


def apply_highlight(text: Text, term: str) -> None:
    if not term:
        return
    for match in re.finditer(rf"\b{re.escape(term)}\b", text.plain):
        text.stylize(pal.HIGHLIGHT, match.start(), match.end())


def identifier_at_cell(lines: list[ViewLine], width: int, x: int, y: int) -> str:
    """Identifier at a painted cell, or empty."""
    if y < 0 or x < 0:
        return ""
    if width <= 0:
        width = 10**9
    row = 0
    for line in lines:
        plain = f"{line.gutter} {line_source(line)}"
        height = line_visual_height(plain, width)
        if y < row + height:
            offset = _cell_to_offset(plain, width, y - row, x)
            if offset is None or offset < GUTTER_CELLS:
                return ""
            return identifier_at(line_source(line), offset - GUTTER_CELLS)
        row += height
    return ""


def _ident_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _cell_to_offset(plain: str, width: int, row: int, col: int) -> int | None:
    wrapped = Text(plain).wrap(_MEASURE, width, tab_size=8)
    if row < 0 or row >= len(wrapped):
        return None
    start = sum(len(part.plain) for part in wrapped[:row])
    piece = wrapped[row].plain
    if not piece:
        return start if start <= len(plain) else None
    if col >= len(piece):
        return start + len(piece)
    return start + col
