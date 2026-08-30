from pathlib import Path

from codeape.cli import cmd_init
from codeape.tui.picker import paginate
from codeape.history import clone_url, first_parent_shas, git
from codeape.paths import load_registry, load_repo_paths
from codeape.progress import Progress


def test_init_assigns_stable_ids(sample_repo, tmp_path, codeape_home):
    other = tmp_path / "other-origin"
    other.mkdir()
    git(["init"], cwd=other)
    git(["config", "user.name", "Test"], cwd=other)
    git(["config", "user.email", "test@example.com"], cwd=other)
    (other / "a.py").write_text("x = 1\n")
    git(["add", "a.py"], cwd=other)
    git(["commit", "-m", "add a"], cwd=other)

    cmd_init(str(sample_repo))
    cmd_init(str(other))

    registry = load_registry()
    assert [repo.id for repo in registry.repos] == [1, 2]
    first = load_repo_paths(1)
    second = load_repo_paths(2)
    assert first.id == 1
    assert second.id == 2
    assert first.name != second.name or first.root != second.root
    assert Progress.load(first.progress_file).origin.endswith(sample_repo.name)


def test_init_file_url_clones(sample_repo, codeape_home):
    cmd_init(sample_repo.as_uri())
    paths = load_repo_paths(1)
    shas = first_parent_shas(paths.mirror)
    assert shas
    assert paths.origin == sample_repo.as_uri()


def test_clone_url_helper(sample_repo, tmp_path):
    dest = tmp_path / "cloned"
    clone_url(sample_repo.as_uri(), dest)
    assert first_parent_shas(dest) == first_parent_shas(sample_repo)


def test_load_repo_paths_single_repo(sample_repo, codeape_home):
    cmd_init(str(sample_repo))
    paths = load_repo_paths()
    assert paths.id == 1
    assert (paths.root / "progress.json").exists()


def test_progress_round_trip(tmp_path: Path):
    from codeape.progress import Attempt, HunkCursor, new_progress

    progress = new_progress("/repo", "aaa")
    progress.attempts["aaa"].cursors = [HunkCursor(hunk=0, line=1, col=2)]
    progress.attempts["bbb"] = Attempt(
        parent="aaa",
        target="bbb",
        patch="diff --git a/x b/x\n",
        status="skipped",
        hunk=1,
        done_hunks=[0],
    )
    path = tmp_path / "progress.json"
    progress.save(path)
    loaded = Progress.load(path)
    assert loaded.current_target == "aaa"
    assert loaded.attempts["aaa"].cursors[0].col == 2
    assert loaded.attempts["bbb"].status == "skipped"
    assert loaded.attempts["bbb"].patch.startswith("diff --git")


def test_paginate_clamps_and_slices():
    items = list(range(45))
    page0, page, pages = paginate(items, 0, size=20)
    assert page0 == list(range(20))
    assert page == 0
    assert pages == 3
    page2, page, pages = paginate(items, 99, size=20)
    assert page2 == list(range(40, 45))
    assert page == 2
    assert pages == 3
    empty, page, pages = paginate([], 3)
    assert empty == []
    assert page == 0
    assert pages == 1


def test_purge_codeape_home_script(tmp_path, monkeypatch):
    import importlib.util

    home = tmp_path / "old-home"
    home.mkdir()
    (home / "progress.json").write_text('{"first_parent_shas": []}\n')
    monkeypatch.setenv("CODEAPE_HOME", str(home))
    spec = importlib.util.spec_from_file_location(
        "purge_codeape_home",
        Path(__file__).resolve().parents[1] / "scripts" / "purge_codeape_home.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main()
    assert not home.exists()
