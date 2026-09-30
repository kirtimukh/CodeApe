from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from codeape.history import (
    GitError,
    clone_local,
    clone_url,
    clone_workspace,
    commit_meta,
    first_parent_shas,
    git,
)
from codeape.paths import (
    RepoEntry,
    RepoPaths,
    is_git_url,
    load_registry,
    load_repo_paths,
    register_repo,
    repo_dir,
    sanitize_name,
    save_registry,
)
from codeape.progress import Progress, new_progress
from codeape.session import Session


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="codeape",
        description="Type through a repository's commit diffs, lesson by lesson.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    init_p = sub.add_parser("init", help="Clone a local path or git URL into ~/.codeape")
    init_p.add_argument("source", help="Local git path or remote URL")
    start_p = sub.add_parser("start", help="Open the repo picker or a repo by id")
    start_p.add_argument("repo_id", nargs="?", type=int, help="Stable repo id")
    start_p.add_argument(
        "--theme",
        choices=("dark", "light", "auto"),
        default=None,
        help="TUI colors: dark, light, or auto from the terminal (env: CODEAPE_THEME)",
    )
    status_p = sub.add_parser("status", help="Show registered repos or one repo")
    status_p.add_argument("repo_id", nargs="?", type=int, help="Stable repo id")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "init":
            cmd_init(args.source)
        elif args.cmd == "start":
            cmd_start(args.repo_id, theme=args.theme)
        elif args.cmd == "status":
            cmd_status(args.repo_id)
    except GitError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc


def cmd_init(source: str) -> None:
    if is_git_url(source):
        origin = source
        name = sanitize_name(source)
        entry = register_repo(name, origin)
        root = repo_dir(entry)
        try:
            clone_url(source, root / "mirror")
        except GitError:
            _rollback_repo(entry)
            raise
    else:
        src = Path(source).expanduser().resolve()
        if not src.exists():
            raise SystemExit(f"Path not found: {src}")
        git(["rev-parse", "--is-inside-work-tree"], cwd=src)
        origin = str(src)
        name = sanitize_name(str(src))
        entry = register_repo(name, origin)
        root = repo_dir(entry)
        try:
            clone_local(src, root / "mirror")
        except GitError:
            _rollback_repo(entry)
            raise
    mirror = root / "mirror"
    workspace = root / "workspace"
    clone_workspace(mirror, workspace)
    shas = first_parent_shas(mirror)
    if not shas:
        _rollback_repo(entry)
        raise SystemExit("Repository has no commits.")
    progress = new_progress(origin, shas[0])
    progress.save(root / "progress.json")
    print(f"Initialized {entry.id} {name} ({len(shas)} first-parent commits)")
    print(f"  mirror     {mirror}")
    print(f"  workspace  {workspace}")
    print(f"Run `codeape start {entry.id}` to begin.")


def _rollback_repo(entry: RepoEntry) -> None:
    registry = load_registry()
    registry.repos = [repo for repo in registry.repos if repo.id != entry.id]
    save_registry(registry)
    root = repo_dir(entry)
    if root.exists():
        shutil.rmtree(root)


def _run_session(paths: RepoPaths) -> None:
    progress = Progress.load(paths.progress_file)
    session = Session(paths, progress)
    if session.done:
        print("All lessons done.")
        print(f"Workspace: {paths.workspace}")
        return
    from codeape.tui.app import CodeApeApp

    CodeApeApp(session).run()
    session.persist()


def cmd_start(repo_id: int | None = None, theme: str | None = None) -> None:
    registry = load_registry()
    if not registry.repos:
        raise SystemExit("No repos. Run `codeape init <path-or-url>` first.")
    from codeape.tui import palette as pal

    pal.use(pal.resolve(theme))
    if repo_id is not None:
        _run_session(load_repo_paths(repo_id))
        return
    if len(registry.repos) == 1:
        _run_session(load_repo_paths(registry.repos[0].id))
        return
    from codeape.tui.picker import RepoPickerApp

    chosen = RepoPickerApp(registry.repos).run()
    if chosen is None:
        return
    _run_session(load_repo_paths(int(chosen)))


def _brief(paths: RepoPaths, progress: Progress) -> str:
    shas = first_parent_shas(paths.mirror)
    if progress.current_target is None:
        return f"done ({len(shas)} commits)"
    meta = commit_meta(paths.mirror, progress.current_target)
    attempt = progress.attempts.get(progress.current_target)
    status = attempt.status if attempt else "in_progress"
    return f"{status}  {progress.current_target[:7]}  {meta.subject}"


def cmd_status(repo_id: int | None = None) -> None:
    registry = load_registry()
    if not registry.repos:
        print("No repos. Run `codeape init <path-or-url>` first.")
        return
    if repo_id is None and len(registry.repos) > 1:
        for entry in registry.repos:
            paths = load_repo_paths(entry.id)
            progress = Progress.load(paths.progress_file)
            print(f"{entry.id:3}  {entry.name:20}  {_brief(paths, progress)}")
        return
    paths = load_repo_paths(repo_id)
    progress = Progress.load(paths.progress_file)
    session = Session(paths, progress, apply=False)
    view = session.view()
    print(f"Repo:    {paths.id}  {paths.name}")
    print(f"Origin:  {progress.origin}")
    print(f"Workspace: {paths.workspace}")
    if view.done:
        print(f"Status:  done ({view.commit_total} commits)")
        return
    print(f"Status:  {view.attempt_status}  {view.sha[:7]}  {view.subject}")
    print(
        f"         commit {view.commit_index}/{view.commit_total}"
        f"  ·  {view.completed_count} done  ·  {view.skipped_count} skipped"
    )
    print(f"         file {view.file_index}/{view.file_total}  {view.file}")
    print(f"         hunk {view.hunk_index}/{view.hunk_total}")


if __name__ == "__main__":
    main()
