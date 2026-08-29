from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "Test")
    env.setdefault("GIT_AUTHOR_EMAIL", "test@example.com")
    env.setdefault("GIT_COMMITTER_NAME", "Test")
    env.setdefault("GIT_COMMITTER_EMAIL", "test@example.com")
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        env=env,
    )


def init_git(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init")
    git(path, "config", "user.name", "Test")
    git(path, "config", "user.email", "test@example.com")


def commit_file(repo: Path, relative: str, content: str, message: str) -> None:
    dest = repo / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content)
    git(repo, "add", relative)
    git(repo, "commit", "-m", message)


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "origin"
    init_git(repo)
    commit_file(
        repo,
        "hello.py",
        "def hello():\n    return 1\n",
        "add hello",
    )
    commit_file(
        repo,
        "hello.py",
        "def hello():\n    return 2\n",
        "change return",
    )
    commit_file(
        repo,
        "hello.py",
        "def hello():\n    # note\n    return 2\n",
        "add comment",
    )
    commit_file(
        repo,
        "poetry.lock",
        "[[package]]\n",
        "add lockfile",
    )
    return repo


@pytest.fixture
def codeape_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "codeape-home"
    monkeypatch.setenv("CODEAPE_HOME", str(home))
    return home
