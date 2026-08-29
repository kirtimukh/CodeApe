from __future__ import annotations

from pygments.lexers import get_lexer_for_filename, guess_lexer
from pygments.token import Comment, String
from pygments.util import ClassNotFound


def _lexer(filename: str, text: str):
    try:
        return get_lexer_for_filename(filename, stripnl=False)
    except ClassNotFound:
        try:
            return guess_lexer(text)
        except ClassNotFound:
            return None


def _is_skipped_token(ttype: object) -> bool:
    return ttype in Comment or ttype in String.Doc


def split_code_and_comment(line: str, filename: str) -> tuple[str, str, bool]:
    """Split a source line into (code, comment_suffix, is_comment_only).

    `code + comment_suffix` always equals `line`. Trailing whitespace before a
    comment is kept on the suffix so it is not typed.
    """
    if line == "":
        return "", "", False
    lexer = _lexer(filename, line)
    if lexer is None:
        return line, "", False
    try:
        source = line if line.endswith("\n") else line + "\n"
        tokens = list(lexer.get_tokens(source))
    except Exception:
        return line, "", False

    pieces: list[str] = []
    for ttype, value in tokens:
        value = value.replace("\n", "")
        if not value:
            continue
        if _is_skipped_token(ttype):
            code = "".join(pieces)
            if not line.startswith(code):
                return line, "", False
            suffix = line[len(code) :]
            if suffix:
                stripped = code.rstrip(" \t")
                suffix = code[len(stripped) :] + suffix
                code = stripped
            return code, suffix, code.strip() == ""
        pieces.append(value)

    code = "".join(pieces)
    if line.startswith(code) and code != line:
        return code, line[len(code) :], code.strip() == ""
    return line, "", False
