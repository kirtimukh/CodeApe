from pathlib import Path

from codeape.cli import cmd_init
from codeape.history import first_parent_shas, git
from codeape.paths import RepoPaths, load_repo_paths
from codeape.progress import STATUS_COMPLETED, STATUS_SKIPPED, Attempt, Progress
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


def test_session_types_root_then_advances(sample_repo, codeape_home):
    session, paths = _open_session(sample_repo)
    shas = first_parent_shas(sample_repo)

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
    head = git(["rev-parse", "HEAD"], cwd=paths.workspace).stdout.strip()
    assert head == shas[0]
    saved = Progress.load(paths.progress_file)
    assert saved.attempts[shas[0]].status == STATUS_COMPLETED
    assert saved.current_target == shas[1]

    current = _current_line(session)
    assert current.kind == "DEL"
    session.on_accept_del()
    current = _current_line(session)
    assert current.col == 4
    assert current.typing[current.col :].startswith("return")
    _type_line(session, "return 2")
    current = _current_line(session)
    assert current.kind == "ADD"
    assert "# note" in current.typing
    session.on_line_tab()
    assert session.done
    assert (paths.workspace / "hello.py").read_text() == (
        "def hello():\n    # note\n    return 2\n"
    )
    head = git(["rev-parse", "HEAD"], cwd=paths.workspace).stdout.strip()
    assert head == shas[2]


def test_session_types_comments_and_skips_lockfile(sample_repo, codeape_home):
    cmd_init(str(sample_repo))
    paths = load_repo_paths()
    progress = Progress.load(paths.progress_file)
    shas = first_parent_shas(sample_repo)
    progress.current_target = shas[2]
    progress.attempts = {
        shas[0]: Attempt(parent=None, target=shas[0], status=STATUS_COMPLETED),
        shas[1]: Attempt(parent=shas[0], target=shas[1], status=STATUS_COMPLETED),
    }
    progress.save(paths.progress_file)

    session = Session(paths, progress)
    assert session.done is False
    current = _current_line(session)
    assert current.kind == "ADD"
    assert "# note" in current.typing
    session.on_line_tab()
    assert session.done
    assert session.progress.attempts[shas[2]].status == STATUS_COMPLETED
    assert session.progress.attempts[shas[3]].status == STATUS_COMPLETED


def test_tab_completes_identifier(sample_repo, codeape_home):
    session, _ = _open_session(sample_repo)
    session.on_tab()
    current = _current_line(session)
    assert current.col > 0
    assert session.progress.stats.chars_assisted > 0
    assert session.progress.stats.chars_typed == 0


def test_tab_covers_connected_punct_spaces_and_newline(sample_repo, codeape_home):
    session, _ = _open_session(sample_repo)
    session.on_tab()
    current = _current_line(session)
    assert current.typing[: current.col] == "def "
    session.on_tab()
    current = _current_line(session)
    assert current.typing[: current.col] == "def hello()"
    session.on_tab()
    current = _current_line(session)
    assert current.typing[current.col :].startswith("return")


def test_line_tab_completes_rest_of_line(sample_repo, codeape_home):
    session, _ = _open_session(sample_repo)
    session.on_line_tab()
    current = _current_line(session)
    assert current.typing[current.col :].startswith("return")
    assert session.progress.stats.chars_assisted == len("def hello():")


def test_added_files_are_absent_until_typed(import_added_repo, codeape_home):
    session, paths = _open_session(import_added_repo)
    session.skip_commit()

    assert not (paths.workspace / "util.py").exists()
    hello = (paths.workspace / "hello.py").read_text()
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


def test_navigate_all_lesson_files(mixed_nav_repo, codeape_home):
    session, _ = _open_session(mixed_nav_repo)
    session.skip_commit()
    session.skip_commit()

    view = session.view()
    assert set(view.files) == {"hello.py", "notes.py", "util.py"}
    assert view.file_total == 3

    seen = {view.file}
    session.next_file()
    seen.add(session.view().file)
    session.next_file()
    seen.add(session.view().file)
    session.next_file()
    seen.add(session.view().file)
    assert seen == {"hello.py", "notes.py", "util.py"}


def _finish_current_file(session: Session) -> str:
    path = session.view().file
    for _ in range(80):
        if session.view().file != path or session.done:
            return path
        current = _current_line(session)
        if current.kind == "ADD":
            session.on_line_tab()
        elif current.kind == "DEL":
            session.on_accept_del()
        else:
            session.on_down()
    raise AssertionError(f"could not finish {path}")


def test_completed_file_stays_navigable(mixed_nav_repo, codeape_home):
    session, _ = _open_session(mixed_nav_repo)
    session.skip_commit()
    session.skip_commit()

    lesson_files = {"hello.py", "notes.py", "util.py"}
    assert set(session.view().files) == lesson_files
    finished = _finish_current_file(session)
    assert finished in lesson_files
    assert session.done is False
    assert set(session.view().files) == lesson_files
    assert session.view().file_total == 3
    assert session.view().file != finished

    seen = {session.view().file}
    session.next_file()
    seen.add(session.view().file)
    session.next_file()
    seen.add(session.view().file)
    session.next_file()
    seen.add(session.view().file)
    assert seen == lesson_files

    while session.view().file != finished:
        session.next_file()
    assert session.view().file == finished
    assert session.view().lines
    assert all(
        line.complete or line.skip or line.kind == "CTX"
        for line in session.view().lines
    )


def test_untouched_indent_is_not_persisted(sample_repo, codeape_home):
    session, paths = _open_session(sample_repo)
    shas = first_parent_shas(sample_repo)
    _type_line(session, "def hello():")
    current = _current_line(session)
    assert current.col == 4
    assert current.typing[current.col :].startswith("return")
    session.persist()

    saved = Progress.load(paths.progress_file).attempts[shas[0]]
    assert [line.col for line in saved.lines] == [len("def hello():")]


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


def test_skip_commit_keeps_partial_attempt(sample_repo, codeape_home):
    session, paths = _open_session(sample_repo)
    shas = first_parent_shas(sample_repo)
    line = _current_line(session)
    for ch in line.typing[:3]:
        session.on_char(ch)
    session.skip_commit()

    saved = Progress.load(paths.progress_file)
    attempt = saved.attempts[shas[0]]
    assert attempt.status == STATUS_SKIPPED
    assert any(line.col == 3 for line in attempt.lines)
    assert saved.current_target == shas[1]
    assert (paths.workspace / "hello.py").read_text() == "def hello():\n    return 1\n"


def test_skip_last_lesson_stays_resumable(sample_repo, codeape_home):
    session, paths = _open_session(sample_repo)
    shas = first_parent_shas(sample_repo)
    session.skip_commit()
    session.skip_commit()

    assert session.done is False
    saved = Progress.load(paths.progress_file)
    assert saved.attempts[shas[0]].status == STATUS_SKIPPED
    assert saved.current_target is not None
    resumed = Session(paths, Progress.load(paths.progress_file))
    assert resumed.done is False
    assert resumed.progress.current_target in saved.attempts


def test_persist_writes_only_typed_added_lines(import_added_repo, codeape_home):
    session, paths = _open_session(import_added_repo)
    session.skip_commit()
    if session.view().file != "util.py":
        session.next_file()
    assert session.view().file == "util.py"
    line = _current_line(session)
    for ch in line.typing[:3]:
        session.on_char(ch)
    session.persist()
    assert (paths.workspace / "util.py").read_text() == "def\n"

    resumed = Session(paths, Progress.load(paths.progress_file))
    assert (paths.workspace / "util.py").read_text() == "def\n"
    assert _current_line(resumed).col == 3


def test_completed_lesson_ignores_typing(sample_repo, codeape_home):
    session, _ = _open_session(sample_repo)
    shas = first_parent_shas(sample_repo)
    _type_line(session, "def hello():")
    _type_line(session, "return 1")
    assert session.view().sha == shas[1]
    session.switch_lesson(shas[0])
    assert session.view().attempt_status == STATUS_COMPLETED
    typed = session.progress.stats.chars_typed
    session.on_char("x")
    session.on_enter()
    session.skip_hunk()
    assert session.progress.stats.chars_typed == typed
    assert session.view().sha == shas[0]


def _move_to_typing(session: Session, snippet: str) -> None:
    for _ in range(40):
        current = _current_line(session)
        if current.kind == "ADD" and snippet in current.typing:
            return
        session.on_down()
    raise AssertionError(f"no ADD line containing {snippet!r}")


def test_type_later_add_leaves_earlier_lines(sparse_repo, codeape_home):
    session, paths = _open_session(sparse_repo)
    session.skip_commit()
    _move_to_typing(session, "z = 3")
    session.on_line_tab()
    session.persist()

    text = (paths.workspace / "hello.py").read_text()
    assert "    z = 3\n" in text
    assert "    y = 2\n" not in text
    assert "    return x\n" in text
    assert "    return x + y + z\n" not in text

    adds = [line for line in session.view().lines if line.kind == "ADD"]
    by_typing = {line.typing: line for line in adds}
    assert by_typing["    y = 2"].complete is False
    assert by_typing["    z = 3"].complete is True
    assert by_typing[""].complete is False


def test_revisit_keeps_untyped_adds_as_candidates(sparse_repo, codeape_home):
    session, paths = _open_session(sparse_repo)
    session.skip_commit()
    _move_to_typing(session, "z = 3")
    session.on_line_tab()
    session.persist()

    resumed = Session(paths, Progress.load(paths.progress_file))
    text = (paths.workspace / "hello.py").read_text()
    assert "    z = 3\n" in text
    assert "    y = 2\n" not in text
    assert "    return x\n" in text

    adds = [line for line in resumed.view().lines if line.kind == "ADD"]
    by_typing = {line.typing: line for line in adds}
    assert by_typing["    y = 2"].complete is False
    assert by_typing["    z = 3"].complete is True
    assert by_typing[""].complete is False
    assert by_typing["    return x + y + z"].complete is False

    current = _current_line(resumed)
    assert current.complete is False
    assert current.kind in {"ADD", "DEL"}


def test_arrows_move_without_completing(sparse_repo, codeape_home):
    session, _ = _open_session(sparse_repo)
    session.skip_commit()
    first = _current_line(session)
    session.on_down()
    second = _current_line(session)
    assert second.typing != first.typing or second.kind != first.kind
    assert first.complete is False
    session.on_up()
    assert _current_line(session).typing == first.typing
    assert _current_line(session).complete is False


def test_resume_keeps_later_identical_add(dup_add_repo, codeape_home):
    session, paths = _open_session(dup_add_repo)
    session.skip_commit()
    _move_to_typing(session, "pass")
    session.on_down()
    current = _current_line(session)
    assert current.typing == "    pass"
    session.on_line_tab()
    session.persist()

    resumed = Session(paths, Progress.load(paths.progress_file))
    adds = [line for line in resumed.view().lines if line.kind == "ADD"]
    assert [line.typing for line in adds] == ["    pass", "    pass"]
    assert adds[0].complete is False
    assert adds[1].complete is True
    text = (paths.workspace / "hello.py").read_text()
    assert text.count("    pass\n") == 1


def test_persist_completed_file_stays_in_ui(mixed_nav_repo, codeape_home):
    session, paths = _open_session(mixed_nav_repo)
    session.skip_commit()
    session.skip_commit()

    finished = _finish_current_file(session)
    remaining = session.view().file
    assert remaining != finished
    session.persist()

    resumed = Session(paths, Progress.load(paths.progress_file))
    assert set(resumed.view().files) == {"hello.py", "notes.py", "util.py"}
    assert resumed.view().file == remaining
    seen = {resumed.view().file}
    resumed.next_file()
    seen.add(resumed.view().file)
    resumed.next_file()
    seen.add(resumed.view().file)
    assert seen == {"hello.py", "notes.py", "util.py"}

    while resumed.view().file != finished:
        resumed.next_file()
    assert all(
        line.complete or line.skip or line.kind == "CTX"
        for line in resumed.view().lines
    )


def _type_add_prefix(session: Session, n: int) -> int:
    for _ in range(20):
        current = _current_line(session)
        if current.kind == "ADD" and current.typing:
            for ch in current.typing[:n]:
                session.on_char(ch)
            return _current_line(session).col
        if current.kind == "DEL":
            session.on_accept_del()
            continue
        session.on_down()
    raise AssertionError("no ADD line to type")


def test_md_and_py_partial_and_complete_restore(md_and_py_repo, codeape_home):
    session, paths = _open_session(md_and_py_repo)
    session.skip_commit()

    assert set(session.view().files) == {"hello.py", "README.md"}
    first = session.view().file
    first_col = _type_add_prefix(session, 3)
    session.persist()

    mid = Session(paths, Progress.load(paths.progress_file))
    assert mid.view().file == first
    assert _current_line(mid).col == first_col
    assert _current_line(mid).kind == "ADD"

    finished = _finish_current_file(mid)
    other = "README.md" if finished == "hello.py" else "hello.py"
    assert mid.view().file == other
    other_col = _type_add_prefix(mid, 2)
    mid.persist()

    resumed = Session(paths, Progress.load(paths.progress_file))
    assert set(resumed.view().files) == {"hello.py", "README.md"}
    assert resumed.view().file == other
    assert _current_line(resumed).col == other_col
    assert _current_line(resumed).kind == "ADD"

    resumed.next_file()
    assert resumed.view().file == finished
    assert resumed.view().lines
    assert all(
        line.complete or line.skip or line.kind == "CTX"
        for line in resumed.view().lines
    )
    if finished == "hello.py":
        assert (paths.workspace / "hello.py").read_text() == (
            "def hello():\n    return 2\n"
        )
    else:
        assert (paths.workspace / "README.md").read_text() == (
            "# Title\n\nHello world.\n"
        )


def test_switch_lesson_restores_attempt(sample_repo, codeape_home):
    session, paths = _open_session(sample_repo)
    shas = first_parent_shas(sample_repo)
    line = _current_line(session)
    for ch in line.typing[:3]:
        session.on_char(ch)
    first_col = _current_line(session).col

    session.switch_lesson(shas[1])
    assert session.view().sha == shas[1]
    assert (paths.workspace / "hello.py").read_text() == "def hello():\n    return 1\n"

    session.switch_lesson(shas[0])
    assert session.view().sha == shas[0]
    assert _current_line(session).col == first_col
