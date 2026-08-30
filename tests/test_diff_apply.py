from codeape.apply import apply_hunks
from codeape.diff_engine import DiffLine, Hunk, commit_hunks
from codeape.history import first_parent_shas


def _hunk(path: str, source_start: int, lines: list[tuple[str, str]], **kwargs) -> Hunk:
    return Hunk(
        path=path,
        is_added_file=kwargs.get("is_added_file", False),
        is_removed_file=kwargs.get("is_removed_file", False),
        source_start=source_start,
        source_length=kwargs.get("source_length", sum(1 for k, _ in lines if k != "ADD")),
        lines=tuple(DiffLine(kind=k, content=c) for k, c in lines),
    )


def test_apply_mixed_hunk():
    original = ["def hello():", "    return 1"]
    hunk = _hunk(
        "hello.py",
        1,
        [
            ("CTX", "def hello():"),
            ("DEL", "    return 1"),
            ("ADD", "    return 2"),
        ],
    )
    assert apply_hunks(original, [hunk]) == ["def hello():", "    return 2"]


def test_apply_new_file():
    hunk = _hunk(
        "hello.py",
        0,
        [("ADD", "print(1)")],
        is_added_file=True,
        source_length=0,
    )
    assert apply_hunks(None, [hunk]) == ["print(1)"]


def test_commit_hunks_skips_lockfile(sample_repo):
    shas = first_parent_shas(sample_repo)
    parent, sha = shas[-2], shas[-1]
    hunks = commit_hunks(sample_repo, parent, sha)
    assert hunks == []


def test_commit_hunks_mixed_change(sample_repo):
    shas = first_parent_shas(sample_repo)
    hunks = commit_hunks(sample_repo, shas[0], shas[1])
    assert len(hunks) == 1
    kinds = [line.kind for line in hunks[0].lines]
    assert "DEL" in kinds
    assert "ADD" in kinds
    assert hunks[0].path == "hello.py"
