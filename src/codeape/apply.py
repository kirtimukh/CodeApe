from __future__ import annotations

import os
from pathlib import Path

from codeape.diff_engine import Hunk
from codeape.history import CommitMeta, git


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


def replay_commit(workspace: Path, meta: CommitMeta) -> bool:
    """Create a workspace commit replaying *meta*. Returns False if empty."""
    git(["add", "-A"], cwd=workspace)
    status = git(["status", "--porcelain"], cwd=workspace)
    if not status.stdout.strip():
        return False
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = meta.author_date
    env["GIT_COMMITTER_DATE"] = meta.author_date
    git(
        [
            "commit",
            f"--author={meta.author_name} <{meta.author_email}>",
            f"--date={meta.author_date}",
            "-F",
            "-",
        ],
        cwd=workspace,
        input_text=meta.message or meta.subject,
        env=env,
    )
    return True
