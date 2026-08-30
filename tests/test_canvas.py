import asyncio

from textual.app import App, ComposeResult

from codeape.session import ViewLine, ViewState
from codeape.tui.canvas import TypingCanvas, line_visual_height, target_scroll_y


def test_follow_noop_when_line_is_in_view():
    assert target_scroll_y(5, 1, 20, 0) is None


def test_follow_noop_when_line_has_lookahead():
    assert target_scroll_y(16, 1, 20, 0) is None


def test_follow_pins_when_line_enters_bottom_band():
    assert target_scroll_y(18, 1, 20, 0) == 18 - int(20 * 2 / 3)


def test_follow_pins_when_line_is_below_the_fold():
    assert target_scroll_y(25, 1, 20, 0) == 25 - int(20 * 2 / 3)


def test_follow_scrolls_least_distance_when_line_is_above():
    assert target_scroll_y(3, 1, 20, 10) == 3


def test_follow_noop_when_already_at_top_target():
    assert target_scroll_y(10, 1, 20, 10) is None


def test_follow_skips_empty_viewport():
    assert target_scroll_y(4, 1, 0, 0) is None


def test_line_visual_height_wraps_and_keeps_a_row():
    assert line_visual_height("hello", 80) == 1
    assert line_visual_height("abcdefghij", 5) == 2
    assert line_visual_height("", 80) == 1


def _view_line(index: int, *, current: bool) -> ViewLine:
    text = f"line {index}"
    return ViewLine(
        kind="ADD",
        gutter="+",
        display=text,
        typing=text,
        comment_suffix="",
        col=0,
        remaining=0,
        skip=False,
        is_current=current,
        miss=False,
    )


class _FakeSession:
    def __init__(self, current: int, total: int = 40) -> None:
        self.current = current
        self.total = total
        self.done = False

    def view(self) -> ViewState:
        return ViewState(
            done=False,
            sha="abc",
            subject="subject",
            commit_index=1,
            commit_total=1,
            attempt_status="",
            completed_count=0,
            skipped_count=0,
            file="a.py",
            files=["a.py"],
            file_index=1,
            file_total=1,
            hunk_index=1,
            hunk_total=1,
            lines=[
                _view_line(i, current=(i == self.current)) for i in range(self.total)
            ],
            current_kind="ADD",
            wpm=0.0,
            accuracy=1.0,
            chars_typed=0,
            misses=0,
            chars_assisted=0,
        )


class _CanvasApp(App):
    def __init__(self, session: _FakeSession) -> None:
        super().__init__()
        self.session = session

    def compose(self) -> ComposeResult:
        yield TypingCanvas(self.session, id="canvas")


def test_canvas_follows_current_line_below_the_fold():
    session = _FakeSession(current=30)

    async def _run() -> None:
        app = _CanvasApp(session)
        async with app.run_test(size=(80, 12)) as pilot:
            canvas = app.query_one(TypingCanvas)
            await pilot.pause()
            assert canvas.max_scroll_y > 0
            assert canvas.scroll_offset.y > 0

    asyncio.run(_run())


def test_canvas_stays_put_when_current_line_is_visible():
    session = _FakeSession(current=2)

    async def _run() -> None:
        app = _CanvasApp(session)
        async with app.run_test(size=(80, 12)) as pilot:
            canvas = app.query_one(TypingCanvas)
            await pilot.pause()
            assert canvas.scroll_offset.y == 0

    asyncio.run(_run())


def test_canvas_follows_after_bump():
    session = _FakeSession(current=2)

    async def _run() -> None:
        app = _CanvasApp(session)
        async with app.run_test(size=(80, 12)) as pilot:
            canvas = app.query_one(TypingCanvas)
            await pilot.pause()
            assert canvas.scroll_offset.y == 0
            session.current = 30
            canvas.bump()
            await pilot.pause()
            assert canvas.scroll_offset.y > 0

    asyncio.run(_run())


def test_canvas_follows_after_resize():
    session = _FakeSession(current=15)

    async def _run() -> None:
        app = _CanvasApp(session)
        async with app.run_test(size=(80, 40)) as pilot:
            canvas = app.query_one(TypingCanvas)
            await pilot.pause()
            assert canvas.scroll_offset.y == 0
            await pilot.resize_terminal(80, 10)
            await pilot.pause()
            assert canvas.scroll_offset.y > 0

    asyncio.run(_run())
