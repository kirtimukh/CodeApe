import json
from pathlib import Path

from codeape.cli import cmd_init
from codeape.history import first_parent_shas, git
from codeape.paths import RepoPaths, load_repo_paths
from codeape.progress import Progress
from codeape.session import Session


def _open_session(origin: Path) -> tuple[Session, RepoPaths]:
    cmd_init(str(origin))
    paths = load_repo_paths()
    return Session(paths, Progress.load(paths.progress_file)), paths


def _type_line(session: Session, text: str) -> None:
    for ch in text:
        session.on_char(ch)
    session.on_enter()


def _current_line(session: Session):
    return next(ln for ln in session.view().lines if ln.is_current)


def test_session_types_root_commit_and_replays(sample_repo, codeape_home):
    session, paths = _open_session(sample_repo)

    view = session.view()
    assert view.done is False
    assert view.file == "hello.py"
    line = _current_line(session)
    assert line.kind == "ADD"

    _type_line(session, "def hello():")
    current = _current_line(session)
    assert current.col == 4
    assert current.typing[current.col :].startswith("return")
    _type_line(session, "return 1")

    assert (paths.workspace / "hello.py").read_text() == "def hello():\n    return 1\n"
    log = git(["log", "--oneline"], cwd=paths.workspace).stdout
    assert "add hello" in log
    assert len(Progress.load(paths.progress_file).completed_shas) == 1

    # Mixed +/- hunk: confirm deletion, type the new line.
    current = _current_line(session)
    assert current.kind == "DEL"
    session.on_accept_del()
    current = _current_line(session)
    assert current.col == 4
    assert current.typing[current.col :].startswith("return")
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
    session, _ = _open_session(sample_repo)
    session.on_tab()
    current = _current_line(session)
    assert current.col > 0
    assert session.progress.stats.chars_assisted > 0
    assert session.progress.stats.chars_typed == 0


def test_added_files_exist_when_commit_starts(import_added_repo, codeape_home):
    session, paths = _open_session(import_added_repo)
    session.skip_commit()

    util = (paths.workspace / "util.py").read_text()
    hello = (paths.workspace / "hello.py").read_text()
    assert util == "def answer():\n    return 2\n"
    assert "from util import answer" not in hello
    assert hello == "def hello():\n    return 1\n"
    assert session.done is False
    assert session.view().file in {"hello.py", "util.py"}


def test_navigate_files_remembers_progress(import_added_repo, codeape_home):
    session, _ = _open_session(import_added_repo)
    session.skip_commit()

    view = session.view()
    assert view.file_total == 2
    first_file = view.file
    first_line = _current_line(session)
    typed = first_line.typing[:3]
    for ch in typed:
        session.on_char(ch)
    first_col = _current_line(session).col
    assert first_col == 3

    session.next_file()
    second_file = session.view().file
    assert second_file != first_file
    assert second_file in {"hello.py", "util.py"}
    second_line = _current_line(session)
    if second_line.kind == "ADD" and second_line.typing:
        session.on_char(second_line.typing[0])
    second_col = _current_line(session).col

    session.prev_file()
    assert session.view().file == first_file
    assert _current_line(session).col == first_col

    session.next_file()
    assert session.view().file == second_file
    assert _current_line(session).col == second_col


def test_navigate_files_wraps(import_added_repo, codeape_home):
    session, _ = _open_session(import_added_repo)
    session.skip_commit()

    seen = [session.view().file]
    session.next_file()
    seen.append(session.view().file)
    session.next_file()
    seen.append(session.view().file)
    assert seen[0] == seen[2]
    assert seen[0] != seen[1]
    assert set(seen) == {"hello.py", "util.py"}


def test_navigate_only_typable_and_new_files(mixed_nav_repo, codeape_home):
    session, _ = _open_session(mixed_nav_repo)
    session.skip_commit()
    session.skip_commit()

    view = session.view()
    assert set(view.files) == {"hello.py", "util.py"}
    assert "notes.py" not in view.files
    assert view.file_total == 2

    seen = {view.file}
    session.next_file()
    seen.add(session.view().file)
    session.next_file()
    seen.add(session.view().file)
    assert seen == {"hello.py", "util.py"}


def test_persist_remembers_in_progress_typing(sample_repo, codeape_home):
    session, paths = _open_session(sample_repo)
    line = _current_line(session)
    for ch in line.typing[:3]:
        session.on_char(ch)
    assert _current_line(session).col == 3
    session.persist()

    resumed = Session(paths, Progress.load(paths.progress_file))
    current = _current_line(resumed)
    assert current.col == 3
    assert current.typing[:3] == line.typing[:3]


def test_persist_remembers_typing_across_files(import_added_repo, codeape_home):
    session, paths = _open_session(import_added_repo)
    session.skip_commit()

    first_file = session.view().file
    first_line = _current_line(session)
    for ch in first_line.typing[:3]:
        session.on_char(ch)
    first_col = _current_line(session).col

    session.next_file()
    second_file = session.view().file
    assert second_file != first_file
    second_line = _current_line(session)
    if second_line.kind == "ADD" and second_line.typing:
        session.on_char(second_line.typing[0])
    second_col = _current_line(session).col
    session.persist()

    resumed = Session(paths, Progress.load(paths.progress_file))
    assert resumed.view().file == second_file
    assert _current_line(resumed).col == second_col
    resumed.prev_file()
    assert resumed.view().file == first_file
    assert _current_line(resumed).col == first_col


def test_persist_remembers_delete_remaining(sample_repo, codeape_home):
    session, paths = _open_session(sample_repo)
    _type_line(session, "def hello():")
    _type_line(session, "return 1")
    current = _current_line(session)
    assert current.kind == "DEL"
    session.on_backspace()
    remaining = _current_line(session).remaining
    assert remaining == len(current.display) - 1
    session.persist()

    resumed = Session(paths, Progress.load(paths.progress_file))
    restored = _current_line(resumed)
    assert restored.kind == "DEL"
    assert restored.remaining == remaining


def test_progress_infers_done_hunks_from_old_hunk_index(tmp_path: Path):
    path = tmp_path / "progress.json"
    path.write_text(
        json.dumps(
            {
                "origin": "/repo",
                "mode": "commit",
                "first_parent_shas": ["abc"],
                "completed_shas": [],
                "current": {"sha": "abc", "file": "hello.py", "hunk": 3},
            }
        )
    )
    progress = Progress.load(path)
    assert progress.current.done_hunks == [0, 1, 2]
    assert progress.current.line == 0
    assert progress.current.col == 0
    assert progress.current.remaining is None
    assert progress.current.cursors == []
