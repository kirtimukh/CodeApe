import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Static

from codeape.session import LessonRow, ViewLine, ViewState
from codeape.tui.app import CodeApeApp
from codeape.tui.picker import LessonSwitcher


def _rows() -> list[LessonRow]:
    return [
        LessonRow("aaa1111", "one", "done", False, 1),
        LessonRow("bbb2222", "two", "in_progress", True, 2),
        LessonRow("ccc3333", "three", "pending", False, 3),
    ]


class _Host(App):
    def compose(self) -> ComposeResult:
        yield Static("host")


def test_enter_selects_highlighted_lesson():
    result: dict[str, str | None] = {}

    async def _run() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(LessonSwitcher(_rows()), lambda target: result.update(target=target))
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(_run())
    assert result.get("target") == "bbb2222"


def test_enter_selects_after_moving_highlight():
    result: dict[str, str | None] = {}

    async def _run() -> None:
        app = _Host()
        async with app.run_test() as pilot:
            app.push_screen(LessonSwitcher(_rows()), lambda target: result.update(target=target))
            await pilot.pause()
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(_run())
    assert result.get("target") == "ccc3333"


class _PickerSession:
    done = False

    def __init__(self) -> None:
        self.moved = ""
        self.switched = ""

    def persist(self) -> None:
        return

    def lessons(self) -> list[LessonRow]:
        return _rows()

    def switch_lesson(self, target: str) -> None:
        self.switched = target

    def on_up(self) -> None:
        self.moved = "up"

    def on_down(self) -> None:
        self.moved = "down"

    def view(self) -> ViewState:
        return ViewState(
            done=False,
            sha="abc1234",
            subject="subject",
            commit_index=1,
            commit_total=2,
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
                ViewLine(
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
            ],
            current_kind="ADD",
            wpm=0.0,
            accuracy=1.0,
            chars_typed=0,
            misses=0,
            chars_assisted=0,
        )


def test_codeape_app_picker_down_does_not_move_hunk():
    session = _PickerSession()

    async def _run() -> None:
        app = CodeApeApp(session)
        async with app.run_test() as pilot:
            app.action_switch_lesson()
            await pilot.pause()
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(_run())
    assert session.moved == ""
    assert session.switched == "ccc3333"
