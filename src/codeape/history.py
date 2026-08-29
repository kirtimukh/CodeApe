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


def init_workspace(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(["init"], cwd=path)
    git(["config", "user.name", "CodeApe"], cwd=path)
    git(["config", "user.email", "codeape@local"], cwd=path)
