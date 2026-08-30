from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

STATUS_IN_PROGRESS = "in_progress"
STATUS_SKIPPED = "skipped"
STATUS_COMPLETED = "completed"


@dataclass
class HunkCursor:
    hunk: int
    line: int


@dataclass
class LineState:
    hunk: int
    line: int
    col: int = 0
    remaining: int | None = None
    entered: bool = False


@dataclass
class Attempt:
    parent: str | None
    target: str
    status: str = STATUS_IN_PROGRESS
    file: str = ""
    hunk: int = 0
    done_hunks: list[int] = field(default_factory=list)
    cursors: list[HunkCursor] = field(default_factory=list)
    lines: list[LineState] = field(default_factory=list)


@dataclass
class Stats:
    chars_typed: int = 0
    misses: int = 0
    time_ms: int = 0
    chars_assisted: int = 0


@dataclass
class Progress:
    origin: str
    current_target: str | None
    attempts: dict[str, Attempt] = field(default_factory=dict)
    stats: Stats = field(default_factory=Stats)

    def dump(self) -> dict:
        return {
            "origin": self.origin,
            "current_target": self.current_target,
            "attempts": {
                sha: {
                    "parent": attempt.parent,
                    "target": attempt.target,
                    "status": attempt.status,
                    "file": attempt.file,
                    "hunk": attempt.hunk,
                    "done_hunks": attempt.done_hunks,
                    "cursors": [asdict(cursor) for cursor in attempt.cursors],
                    "lines": [asdict(line) for line in attempt.lines],
                }
                for sha, attempt in self.attempts.items()
            },
            "stats": asdict(self.stats),
        }

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.dump(), indent=2) + "\n")

    @classmethod
    def load(cls, path: Path) -> Progress:
        data = json.loads(path.read_text())
        attempts = {
            sha: _load_attempt(sha, item)
            for sha, item in data.get("attempts", {}).items()
        }
        return cls(
            origin=data["origin"],
            current_target=data.get("current_target"),
            attempts=attempts,
            stats=Stats(**data.get("stats", {})),
        )


def _load_attempt(sha: str, data: dict) -> Attempt:
    cursors = _load_cursors(data)
    if not cursors and (
        data.get("line") or data.get("col") or data.get("remaining") is not None
    ):
        cursors = [
            HunkCursor(hunk=int(data.get("hunk", 0)), line=int(data.get("line", 0)))
        ]
    lines = _load_lines(data)
    if not lines:
        lines = _lines_from_legacy(data)
    return Attempt(
        parent=data.get("parent"),
        target=data.get("target", sha),
        status=data.get("status", STATUS_IN_PROGRESS),
        file=data.get("file", ""),
        hunk=int(data.get("hunk", 0)),
        done_hunks=[int(i) for i in data.get("done_hunks", [])],
        cursors=cursors,
        lines=lines,
    )


def _load_remaining(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _load_cursors(data: dict) -> list[HunkCursor]:
    cursors: list[HunkCursor] = []
    for item in data.get("cursors") or []:
        cursors.append(
            HunkCursor(
                hunk=int(item["hunk"]),
                line=int(item.get("line", 0)),
            )
        )
    return cursors


def _load_lines(data: dict) -> list[LineState]:
    lines: list[LineState] = []
    for item in data.get("lines") or []:
        lines.append(
            LineState(
                hunk=int(item["hunk"]),
                line=int(item.get("line", 0)),
                col=int(item.get("col", 0)),
                remaining=_load_remaining(item.get("remaining")),
                entered=bool(item.get("entered", False)),
            )
        )
    return lines


def _lines_from_legacy(data: dict) -> list[LineState]:
    lines: list[LineState] = []
    seen: set[tuple[int, int]] = set()
    for item in data.get("cursors") or []:
        state = _line_from_legacy_item(item)
        if state is None:
            continue
        seen.add((state.hunk, state.line))
        lines.append(state)
    if data.get("line") or data.get("col") or data.get("remaining") is not None:
        state = _line_from_legacy_item(data)
        if state is not None and (state.hunk, state.line) not in seen:
            lines.append(state)
    return lines


def _line_from_legacy_item(item: dict) -> LineState | None:
    col = int(item.get("col", 0))
    remaining = _load_remaining(item.get("remaining"))
    if col == 0 and remaining is None:
        return None
    return LineState(
        hunk=int(item.get("hunk", 0)),
        line=int(item.get("line", 0)),
        col=col,
        remaining=remaining,
    )


def new_progress(origin: str, first_target: str | None) -> Progress:
    attempts: dict[str, Attempt] = {}
    if first_target:
        attempts[first_target] = Attempt(parent=None, target=first_target)
    return Progress(
        origin=origin,
        current_target=first_target,
        attempts=attempts,
    )
