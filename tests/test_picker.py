import asyncio

from textual.app import App, ComposeResult
from textual.widgets import Static

from codeape.session import LessonRow
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
