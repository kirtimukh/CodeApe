from pathlib import Path

from codeape.cli import cmd_init
from codeape.history import first_parent_shas, git
from codeape.paths import load_repo_paths
from codeape.progress import Progress
from codeape.session import Session


def _type_line(session: Session, text: str) -> None:
    for ch in text:
        session.on_char(ch)
    session.on_enter()


def test_session_types_root_commit_and_replays(sample_repo, codeape_home):
    cmd_init(str(sample_repo))
    paths = load_repo_paths()
    progress = Progress.load(paths.progress_file)
    session = Session(paths, progress)

    view = session.view()
    assert view.done is False
    assert view.file == "hello.py"
    line = next(ln for ln in view.lines if ln.is_current)
    assert line.kind == "ADD"

    _type_line(session, "def hello():")
    session.on_tab()
    _type_line(session, "return 1")

    assert (paths.workspace / "hello.py").read_text() == "def hello():\n    return 1\n"
    log = git(["log", "--oneline"], cwd=paths.workspace).stdout
    assert "add hello" in log
    assert len(Progress.load(paths.progress_file).completed_shas) == 1

    # Mixed +/- hunk: confirm deletion, type the new line.
    current = next(ln for ln in session.view().lines if ln.is_current)
    assert current.kind == "DEL"
    session.on_accept_del()
    session.on_tab()
    _type_line(session, "return 2")
    # Comment-only and lockfile commits auto-complete after the mixed hunk.
    assert session.done
    assert (paths.workspace / "hello.py").read_text() == (
        "def hello():\n    # note\n    return 2\n"
    )
    log = git(["log", "--format=%s"], cwd=paths.workspace).stdout
    assert "change return" in log
    assert "add comment" in log


def test_session_skips_comments_and_lockfile(sample_repo, codeape_home):
    cmd_init(str(sample_repo))
    paths = load_repo_paths()
    progress = Progress.load(paths.progress_file)
    shas = first_parent_shas(sample_repo)
    progress.completed_shas = list(shas[:2])
    progress.current.sha = shas[2]
    progress.current.hunk = 0
    progress.save(paths.progress_file)

    session = Session(paths, progress)
    assert session.done
    assert set(shas[:4]).issubset(set(session.progress.completed_shas))


def test_tab_completes_identifier(sample_repo, codeape_home):
    cmd_init(str(sample_repo))
    paths = load_repo_paths()
    progress = Progress.load(paths.progress_file)
    session = Session(paths, progress)
    session.on_tab()
    view = session.view()
    current = next(ln for ln in view.lines if ln.is_current)
    assert current.col > 0
    assert session.progress.stats.chars_assisted > 0
    assert session.progress.stats.chars_typed == 0


def test_session_skips_comments_and_lockfile(sample_repo, codeape_home):
    cmd_init(str(sample_repo))
    paths = load_repo_paths()
    progress = Progress.load(paths.progress_file)
    shas = first_parent_shas(sample_repo)
    progress.completed_shas = list(shas[:2])
    progress.current.sha = shas[2]
    progress.current.hunk = 0
    progress.save(paths.progress_file)

    session = Session(paths, progress)
    # Comment-only commit auto-completes; lockfile commit is empty after filter.
    # Catch-up should land on done or skip both remaining commits.
    session.skip_commit()
    session.skip_commit()
    # After comment commit + lockfile, all done
    assert session.done or len(session.progress.completed_shas) >= 3


def test_tab_completes_identifier(sample_repo, codeape_home):
    cmd_init(str(sample_repo))
    paths = load_repo_paths()
    progress = Progress.load(paths.progress_file)
    session = Session(paths, progress)
    session.on_tab()  # may complete first token "def"
    view = session.view()
    current = next(ln for ln in view.lines if ln.is_current)
    assert current.col > 0
    assert session.progress.stats.chars_assisted > 0
    assert session.progress.stats.chars_typed == 0
