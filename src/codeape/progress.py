from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Current:
    sha: str | None
    file: str
    hunk: int


@dataclass
class Skipped:
    shas: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)


@dataclass
class Stats:
    chars_typed: int = 0
    misses: int = 0
    time_ms: int = 0
    chars_assisted: int = 0


@dataclass
class Progress:
    origin: str
    mode: str
    first_parent_shas: list[str]
    completed_shas: list[str]
    current: Current
    skipped: Skipped = field(default_factory=Skipped)
    stats: Stats = field(default_factory=Stats)

    def dump(self) -> dict:
        return {
            "origin": self.origin,
            "mode": self.mode,
            "first_parent_shas": self.first_parent_shas,
            "completed_shas": self.completed_shas,
            "current": asdict(self.current),
            "skipped": asdict(self.skipped),
            "stats": asdict(self.stats),
        }

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.dump(), indent=2) + "\n")

    @classmethod
    def load(cls, path: Path) -> Progress:
        data = json.loads(path.read_text())
        return cls(
            origin=data["origin"],
            mode=data.get("mode", "commit"),
            first_parent_shas=list(data["first_parent_shas"]),
            completed_shas=list(data.get("completed_shas", [])),
            current=Current(
                sha=data["current"].get("sha"),
                file=data["current"].get("file", ""),
                hunk=int(data["current"].get("hunk", 0)),
            ),
            skipped=Skipped(
                shas=list(data.get("skipped", {}).get("shas", [])),
                files=list(data.get("skipped", {}).get("files", [])),
            ),
            stats=Stats(**data.get("stats", {})),
        )


def new_progress(origin: str, shas: list[str]) -> Progress:
    return Progress(
        origin=origin,
        mode="commit",
        first_parent_shas=shas,
        completed_shas=[],
        current=Current(
            sha=shas[0] if shas else None,
            file="",
            hunk=0,
        ),
    )
