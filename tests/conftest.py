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


def origin_with_hello(tmp_path: Path) -> Path:
    repo = tmp_path / "origin"
    init_git(repo)
    commit_file(repo, "hello.py", "def hello():\n    return 1\n", "add hello")
    return repo


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    repo = origin_with_hello(tmp_path)
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
def import_added_repo(tmp_path: Path) -> Path:
    """A repo whose second commit adds a module and imports it from an existing file."""
    repo = origin_with_hello(tmp_path)
    (repo / "util.py").write_text("def answer():\n    return 2\n")
    (repo / "hello.py").write_text(
        "from util import answer\n\ndef hello():\n    return answer()\n"
    )
    git(repo, "add", "util.py", "hello.py")
    git(repo, "commit", "-m", "add util and import it")
    return repo


@pytest.fixture
def mixed_nav_repo(tmp_path: Path) -> Path:
    """Second commit: typable edit, comment-only edit, and a new file."""
    repo = origin_with_hello(tmp_path)
    commit_file(
        repo,
        "notes.py",
        "def notes():\n    return 0\n",
        "add notes",
    )
    (repo / "hello.py").write_text("def hello():\n    return 2\n")
    (repo / "notes.py").write_text("def notes():\n    # later\n    return 0\n")
    (repo / "util.py").write_text("def answer():\n    return 2\n")
    git(repo, "add", "hello.py", "notes.py", "util.py")
    git(repo, "commit", "-m", "edit hello, comment notes, add util")
    return repo


@pytest.fixture
def md_and_py_repo(tmp_path: Path) -> Path:
    """Parent adds a .py and a .md file; the next commit edits both."""
    repo = tmp_path / "origin"
    init_git(repo)
    (repo / "hello.py").write_text("def hello():\n    return 1\n")
    (repo / "README.md").write_text("# Title\n\nHello.\n")
    git(repo, "add", "hello.py", "README.md")
    git(repo, "commit", "-m", "add py and md")
    (repo / "hello.py").write_text("def hello():\n    return 2\n")
    (repo / "README.md").write_text("# Title\n\nHello world.\n")
    git(repo, "add", "hello.py", "README.md")
    git(repo, "commit", "-m", "edit py and md")
    return repo


@pytest.fixture
def sparse_repo(tmp_path: Path) -> Path:
    """Parent → target with a blank ADD, two new lines, and a kept delete."""
    repo = tmp_path / "origin"
    init_git(repo)
    commit_file(
        repo,
        "hello.py",
        "def foo():\n    x = 1\n    return x\n",
        "add foo",
    )
    commit_file(
        repo,
        "hello.py",
        "def foo():\n    x = 1\n\n    y = 2\n    z = 3\n    return x + y + z\n",
        "expand foo",
    )
    return repo


@pytest.fixture
def dup_add_repo(tmp_path: Path) -> Path:
    """Parent → target with two identical ADD lines after a distinct one."""
    repo = tmp_path / "origin"
    init_git(repo)
    commit_file(repo, "hello.py", "def foo():\n    x = 1\n", "add foo")
    commit_file(
        repo,
        "hello.py",
        "def foo():\n    x = 1\n    pass\n    pass\n",
        "add two pass",
    )
    return repo


@pytest.fixture
def codeape_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "codeape-home"
    monkeypatch.setenv("CODEAPE_HOME", str(home))
    return home
