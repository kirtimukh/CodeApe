from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(RuntimeError):
    pass


def git(
    args: list[str],
    cwd: Path,
    *,
    check: bool = True,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        input=input_text,
        env=env,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise GitError(f"git {' '.join(args)} failed: {detail}")
    return result


@dataclass(frozen=True)
class CommitMeta:
    sha: str
    author_name: str
    author_email: str
    author_date: str
    subject: str
    message: str


def first_parent_shas(repo: Path) -> list[str]:
    result = git(["log", "--reverse", "--first-parent", "--format=%H"], cwd=repo)
    return [line for line in result.stdout.splitlines() if line]


def commit_meta(repo: Path, sha: str) -> CommitMeta:
    header = git(
        ["show", "-s", "--format=%an%n%ae%n%aI%n%s", sha],
        cwd=repo,
    )
    lines = header.stdout.splitlines()
    if len(lines) < 4:
        raise GitError(f"Could not read metadata for {sha}")
    author_name, author_email, author_date, subject = lines[:4]
    body = git(["show", "-s", "--format=%B", sha], cwd=repo).stdout
    if body.endswith("\n"):
        body = body[:-1]
    return CommitMeta(
        sha=sha,
        author_name=author_name,
        author_email=author_email,
        author_date=author_date,
        subject=subject,
        message=body,
    )


def file_at(repo: Path, sha: str | None, path: str) -> list[str] | None:
    if sha is None:
        return None
    result = git(["cat-file", "-p", f"{sha}:{path}"], cwd=repo, check=False)
    if result.returncode != 0:
        return None
    text = result.stdout
    if text.endswith("\n"):
        text = text[:-1]
    if text == "":
        return []
    return text.split("\n")


def clone_local(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    git(["clone", "--local", str(src), str(dest)], cwd=src.parent)


def clone_url(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    git(["clone", url, str(dest)], cwd=dest.parent)


def clone_workspace(mirror: Path, workspace: Path) -> None:
    git(["clone", "--local", str(mirror), str(workspace)], cwd=mirror.parent)
    git(["config", "user.name", "CodeApe"], cwd=workspace)
    git(["config", "user.email", "codeape@local"], cwd=workspace)


EMPTY_BRANCH = "codeape-empty"


def checkout_parent(workspace: Path, parent: str | None) -> None:
    """Reset the workspace to origin parent N, or an empty tree for the root commit."""
    if parent is None:
        _checkout_empty(workspace)
        return
    git(["checkout", "-f", parent], cwd=workspace)
    git(["reset", "--hard", parent], cwd=workspace)
    git(["clean", "-fd"], cwd=workspace)


def _checkout_empty(workspace: Path) -> None:
    exists = git(["rev-parse", "--verify", EMPTY_BRANCH], cwd=workspace, check=False)
    if exists.returncode != 0:
        git(["checkout", "--orphan", EMPTY_BRANCH], cwd=workspace)
        git(["read-tree", "--empty"], cwd=workspace)
        git(["clean", "-fd"], cwd=workspace)
        git(["commit", "--allow-empty", "-m", "empty"], cwd=workspace)
        return
    git(["checkout", "-f", EMPTY_BRANCH], cwd=workspace)
    git(["reset", "--hard", EMPTY_BRANCH], cwd=workspace)
    git(["clean", "-fd"], cwd=workspace)
