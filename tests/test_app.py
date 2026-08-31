import asyncio

from codeape.session import ViewLine, ViewState
from codeape.tui.app import CodeApeApp, StatusBar
from codeape.tui.canvas import TypingCanvas


def _view_line() -> ViewLine:
    return ViewLine(
        kind="ADD",
        gutter="+",
        display="x = 1",
        typing="x = 1",
        comment_suffix="",
        col=0,
        remaining=0,
        skip=False,
        is_current=True,
        miss=False,
    )


class _FakeSession:
    def __init__(self, files: list[str]) -> None:
        self.files = files
        self.done = False

    def target_source(self) -> str:
        return "x = 1\nx = 2"

    def view(self) -> ViewState:
        current = self.files[0] if self.files else ""
        return ViewState(
            done=False,
            sha="abc1234",
            subject="subject",
            commit_index=1,
            commit_total=2,
            attempt_status="",
            completed_count=0,
            skipped_count=0,
            file=current,
            files=list(self.files),
            file_index=1,
            file_total=len(self.files),
            hunk_index=1,
            hunk_total=1,
            lines=[_view_line()],
            current_kind="ADD",
            wpm=0.0,
            accuracy=1.0,
            chars_typed=0,
            misses=0,
            chars_assisted=0,
        )


_LONG_FILES = [
    "src/very/long/module/name/alpha.py",
    "src/very/long/module/name/bravo.py",
    "src/very/long/module/name/charlie.py",
    "src/very/long/module/name/delta.py",
]


def test_status_grows_when_filenames_need_another_line():
    session = _FakeSession(["a.py"])

    async def _run() -> None:
        app = CodeApeApp(session)
        async with app.run_test(size=(60, 20)) as pilot:
            status = app.query_one(StatusBar)
            await pilot.pause()
            short_h = status.size.height
            session.files = list(_LONG_FILES)
            app._refresh_view()
            await pilot.pause()
            assert status.size.height > short_h

    asyncio.run(_run())


def test_status_shows_highlight_count():
    session = _FakeSession(["a.py"])

    async def _run() -> None:
        app = CodeApeApp(session)
        async with app.run_test(size=(60, 20)) as pilot:
            canvas = app.query_one(TypingCanvas)
            canvas.set_highlight("x")
            await pilot.pause()
            rendered = app.query_one(StatusBar).render()
            assert "x × 2" in rendered.plain

    asyncio.run(_run())


def test_escape_clears_highlight():
    session = _FakeSession(["a.py"])

    async def _run() -> None:
        app = CodeApeApp(session)
        async with app.run_test(size=(60, 20)) as pilot:
            canvas = app.query_one(TypingCanvas)
            canvas.set_highlight("x")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert canvas.highlight_term == ""
            assert "×" not in app.query_one(StatusBar).render().plain

    asyncio.run(_run())


def test_escape_leaves_highlight_when_command_palette_is_open():
    session = _FakeSession(["a.py"])

    async def _run() -> None:
        app = CodeApeApp(session)
        async with app.run_test(size=(60, 20)) as pilot:
            canvas = app.query_one(TypingCanvas)
            canvas.set_highlight("x")
            await pilot.pause()
            app.action_command_palette()
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert canvas.highlight_term == "x"

    asyncio.run(_run())


def test_status_shrinks_when_filenames_fit_on_one_line():
    session = _FakeSession(list(_LONG_FILES))

    async def _run() -> None:
        app = CodeApeApp(session)
        async with app.run_test(size=(60, 20)) as pilot:
            status = app.query_one(StatusBar)
            await pilot.pause()
            tall_h = status.size.height
            session.files = ["a.py"]
            app._refresh_view()
            await pilot.pause()
            assert status.size.height < tall_h

    asyncio.run(_run())
