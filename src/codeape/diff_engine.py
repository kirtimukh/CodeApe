from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from unidiff import PatchSet

from codeape.history import git
from codeape.paths import is_lockfile


@dataclass(frozen=True)
class DiffLine:
    kind: str  # ADD, DEL, CTX
    content: str


@dataclass(frozen=True)
class Hunk:
    path: str
    is_added_file: bool
    is_removed_file: bool
    source_start: int
    source_length: int
    lines: tuple[DiffLine, ...]


def _diff_text(repo: Path, parent: str | None, sha: str) -> str:
    if parent is None:
        result = git(
            [
                "diff-tree",
                "--no-commit-id",
                "-p",
                "--root",
                "--no-renames",
                "-U3",
                sha,
            ],
            cwd=repo,
        )
    else:
        result = git(
            ["diff", "-U3", "--no-renames", parent, sha],
            cwd=repo,
        )
    return result.stdout


def _numstat_binaries(repo: Path, parent: str | None, sha: str) -> set[str]:
    if parent is None:
        result = git(
            ["diff-tree", "--no-commit-id", "--numstat", "--root", "-r", sha],
            cwd=repo,
        )
    else:
        result = git(["diff", "--numstat", "--no-renames", parent, sha], cwd=repo)
    binaries: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, deleted, path = parts[0], parts[1], parts[2]
        if added == "-" and deleted == "-":
            binaries.add(path)
    return binaries


def commit_hunks(repo: Path, parent: str | None, sha: str) -> list[Hunk]:
    binaries = _numstat_binaries(repo, parent, sha)
    text = _diff_text(repo, parent, sha)
    if not text.strip():
        return []
    patch = PatchSet(text)
    hunks: list[Hunk] = []
    for patched in patch:
        path = patched.path
        if is_lockfile(path) or path in binaries or patched.is_binary_file:
            continue
        for raw in patched:
            lines = tuple(
                DiffLine(kind=_kind(line), content=_content(line))
                for line in raw
                if _kind(line) is not None
            )
            hunks.append(
                Hunk(
                    path=path,
                    is_added_file=bool(patched.is_added_file),
                    is_removed_file=bool(patched.is_removed_file),
                    source_start=int(raw.source_start),
                    source_length=int(raw.source_length),
                    lines=lines,
                )
            )
    return hunks


def _kind(line: object) -> str | None:
    if getattr(line, "is_added", False):
        return "ADD"
    if getattr(line, "is_removed", False):
        return "DEL"
    if getattr(line, "is_context", False):
        return "CTX"
    return None


def _content(line: object) -> str:
    value = getattr(line, "value", "")
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return value.rstrip("\n")
