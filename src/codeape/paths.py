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


def sanitize_name(source: str) -> str:
    text = source.strip().rstrip("/")
    if text.endswith(".git"):
        text = text[:-4]
    if "://" in text:
        name = text.rsplit("/", 1)[-1]
    elif text.startswith("git@"):
        name = text.rsplit(":", 1)[-1].rsplit("/", 1)[-1]
    else:
        name = Path(text).expanduser().name
    name = re.sub(r"[^\w.-]+", "-", name).strip(".-")
    return name or "repo"


def is_git_url(source: str) -> bool:
    text = source.strip()
    return text.startswith(
        ("http://", "https://", "git://", "ssh://", "file://", "git@")
    )


@dataclass(frozen=True)
class RepoEntry:
    id: int
    name: str
    origin: str


@dataclass
class Registry:
    next_id: int
    repos: list[RepoEntry]

    def find(self, repo_id: int) -> RepoEntry | None:
        return next((repo for repo in self.repos if repo.id == repo_id), None)

    def dump(self) -> dict:
        return {
            "next_id": self.next_id,
            "repos": [
                {"id": repo.id, "name": repo.name, "origin": repo.origin}
                for repo in self.repos
            ],
        }


@dataclass(frozen=True)
class RepoPaths:
    id: int
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


def registry_file() -> Path:
    return home() / "repos.json"


def load_registry() -> Registry:
    path = registry_file()
    if not path.exists():
        return Registry(next_id=1, repos=[])
    data = json.loads(path.read_text())
    return Registry(
        next_id=int(data.get("next_id", 1)),
        repos=[
            RepoEntry(id=int(item["id"]), name=item["name"], origin=item["origin"])
            for item in data.get("repos", [])
        ],
    )


def save_registry(registry: Registry) -> None:
    home().mkdir(parents=True, exist_ok=True)
    registry_file().write_text(json.dumps(registry.dump(), indent=2) + "\n")


def register_repo(name: str, origin: str) -> RepoEntry:
    registry = load_registry()
    entry = RepoEntry(id=registry.next_id, name=name, origin=origin)
    registry.next_id += 1
    registry.repos.append(entry)
    save_registry(registry)
    return entry


def repo_dir(entry: RepoEntry) -> Path:
    return repos_root() / f"{entry.id}-{entry.name}"


def load_repo_paths(repo_id: int | None = None) -> RepoPaths:
    registry = load_registry()
    if not registry.repos:
        raise SystemExit("No repos. Run `codeape init <path-or-url>` first.")
    if repo_id is None:
        if len(registry.repos) != 1:
            known = ", ".join(str(repo.id) for repo in registry.repos)
            raise SystemExit(f"Specify a repo id. Known: {known}")
        entry = registry.repos[0]
    else:
        entry = registry.find(repo_id)
        if entry is None:
            known = ", ".join(str(repo.id) for repo in registry.repos)
            raise SystemExit(f"Unknown repo id {repo_id}. Known: {known}")
    root = repo_dir(entry)
    if not (root / "progress.json").exists():
        raise SystemExit(f"Repo {entry.id} ({entry.name}) is missing progress.json.")
    return RepoPaths(id=entry.id, name=entry.name, origin=entry.origin, root=root)


def is_lockfile(path: str) -> bool:
    return Path(path).name in LOCKFILES
