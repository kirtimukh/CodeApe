from __future__ import annotations

from pathlib import Path

from codeape.diff_engine import Hunk
from codeape.history import GitError, git


def apply_hunks(original: list[str] | None, hunks: list[Hunk]) -> list[str]:
    """Apply hunks against the parent file contents (original line numbers)."""
    source = list(original or [])
    orig_i = 0
    result: list[str] = []
    for hunk in hunks:
        start = max(hunk.source_start - 1, 0)
        start = min(start, len(source))
        if orig_i < start:
            result.extend(source[orig_i:start])
            orig_i = start
        for line in hunk.lines:
            if line.kind == "CTX":
                result.append(line.content)
                orig_i += 1
            elif line.kind == "DEL":
                orig_i += 1
            elif line.kind == "ADD":
                result.append(line.content)
    result.extend(source[orig_i:])
    return result


def write_file(workspace: Path, path: str, lines: list[str]) -> None:
    dest = workspace / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines)
    if lines:
        text += "\n"
    dest.write_text(text)


def delete_file(workspace: Path, path: str) -> None:
    dest = workspace / path
    if dest.exists():
        dest.unlink()
    _prune_empty_dirs(workspace, dest.parent)


def _prune_empty_dirs(root: Path, directory: Path) -> None:
    try:
        directory.relative_to(root)
    except ValueError:
        return
    while directory != root and directory.is_dir() and not any(directory.iterdir()):
        directory.rmdir()
        directory = directory.parent


def snapshot_attempt(workspace: Path) -> str:
    git(["add", "-A"], cwd=workspace)
    return git(["diff", "--cached"], cwd=workspace).stdout


def apply_attempt(workspace: Path, patch: str) -> bool:
    if not patch.strip():
        return True
    try:
        git(["apply", "--whitespace=nowarn"], cwd=workspace, input_text=patch)
    except GitError:
        return False
    return True
