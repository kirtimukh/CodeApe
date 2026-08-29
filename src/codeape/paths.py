from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

LOCKFILES = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "Cargo.lock",
    }
)


def home() -> Path:
    override = os.environ.get("CODEAPE_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".codeape"


def repos_root() -> Path:
    return home() / "repos"


def sanitize_name(path: Path) -> str:
    name = path.resolve().name
    name = re.sub(r"[^\w.-]+", "-", name).strip(".-")
    return name or "repo"


@dataclass(frozen=True)
class RepoPaths:
    name: str
    origin: str
    root: Path

    @property
    def mirror(self) -> Path:
        return self.root / "mirror"

    @property
    def workspace(self) -> Path:
        return self.root / "workspace"

    @property
    def progress_file(self) -> Path:
        return self.root / "progress.json"


def repo_paths(name: str) -> Path:
    return repos_root() / name


def active_file() -> Path:
    return home() / "active.json"


def read_active() -> str | None:
    path = active_file()
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return data.get("name")


def write_active(name: str) -> None:
    home().mkdir(parents=True, exist_ok=True)
    active_file().write_text(json.dumps({"name": name}, indent=2) + "\n")


def load_repo_paths(name: str | None = None) -> RepoPaths:
    chosen = name or read_active()
    if not chosen:
        raise SystemExit("No active repo. Run `codeape init <path>` first.")
    root = repo_paths(chosen)
    progress_path = root / "progress.json"
    if not progress_path.exists():
        raise SystemExit(f"Repo {chosen!r} is missing progress.json. Re-run init.")
    data = json.loads(progress_path.read_text())
    return RepoPaths(name=chosen, origin=data["origin"], root=root)


def is_lockfile(path: str) -> bool:
    return Path(path).name in LOCKFILES
