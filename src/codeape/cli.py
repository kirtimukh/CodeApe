from __future__ import annotations

import argparse
import sys
from pathlib import Path

from codeape.history import GitError, clone_local, first_parent_shas, git, init_workspace
from codeape.paths import (
    RepoPaths,
    load_repo_paths,
    repo_paths,
    sanitize_name,
    write_active,
)
from codeape.progress import Progress, new_progress
from codeape.session import Session


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="codeape",
        description="Reconstruct a repository by typing its commit diffs.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    init_p = sub.add_parser("init", help="Clone a local repo into ~/.codeape")
    init_p.add_argument("path", help="Path to a local git repository")
    sub.add_parser("start", help="Resume typing the active repo")
    sub.add_parser("status", help="Show current vs completed commits")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "init":
            cmd_init(args.path)
        elif args.cmd == "start":
            cmd_start()
        elif args.cmd == "status":
            cmd_status()
    except GitError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc


def cmd_init(path: str) -> None:
    src = Path(path).expanduser().resolve()
    if not src.exists():
        raise SystemExit(f"Path not found: {src}")
    git(["rev-parse", "--is-inside-work-tree"], cwd=src)
    name = sanitize_name(src)
    root = repo_paths(name)
    if root.exists():
        raise SystemExit(
            f"Already initialized: {root}\n"
            "Remove that directory or choose a differently named repo."
        )
    mirror = root / "mirror"
    workspace = root / "workspace"
    clone_local(src, mirror)
    init_workspace(workspace)
    shas = first_parent_shas(mirror)
    if not shas:
        raise SystemExit("Repository has no commits.")
    progress = new_progress(str(src), shas)
    root.mkdir(parents=True, exist_ok=True)
    progress.save(root / "progress.json")
    write_active(name)
    print(f"Initialized {name} ({len(shas)} first-parent commits)")
    print(f"  mirror     {mirror}")
    print(f"  workspace  {workspace}")
    print("Run `codeape start` to begin.")


def _open_active() -> tuple[RepoPaths, Progress]:
    paths = load_repo_paths()
    progress = Progress.load(paths.progress_file)
    return paths, progress


def cmd_start() -> None:
    paths, progress = _open_active()
    session = Session(paths, progress)
    if session.done:
        print("All commits recreated.")
        print(f"Workspace: {paths.workspace}")
        return
    from codeape.tui.app import CodeApeApp

    CodeApeApp(session).run()
    session.persist()


def cmd_status() -> None:
    paths, progress = _open_active()
    session = Session(paths, progress, apply=False)
    view = session.view()
    print(f"Repo:    {paths.name}")
    print(f"Origin:  {progress.origin}")
    print(f"Workspace: {paths.workspace}")
    if view.done:
        print(f"Status:  done ({view.commit_total} commits)")
        return
    print(f"Status:  recreating {view.sha[:7]}  {view.subject}")
    print(
        f"         {len(progress.completed_shas)} completed / "
        f"{view.commit_total} total"
    )
    print(
        f"         file {view.file_index}/{view.file_total}  {view.file}"
    )
    print(f"         hunk {view.hunk_index}/{view.hunk_total}")


if __name__ == "__main__":
    main()
