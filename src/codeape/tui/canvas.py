from __future__ import annotations

from rich.console import Console
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.events import Resize
from textual.widgets import Static

from codeape.session import Session, ViewLine
from codeape.tui import palette as pal

LOOKAHEAD_ROWS = 3
PIN_RATIO = 2 / 3
_MEASURE = Console(width=120, legacy_windows=False, force_terminal=True)


def target_scroll_y(
    line_y: int,
    line_h: int,
    view_h: int,
    scroll_y: int,
    *,
    lookahead: int = LOOKAHEAD_ROWS,
    pin_ratio: float = PIN_RATIO,
) -> int | None:
    """Return a new scroll offset, or None if the current line can stay put.

    The line may sit anywhere except the last ``lookahead`` rows. When it would
    leave the viewport or enter that bottom band, scroll so it sits about
    ``pin_ratio`` of the way down. If it leaves the top, scroll the least
    distance that brings it back.
    """
    if view_h <= 0 or line_h <= 0:
        return None
    line_h = min(line_h, view_h)
    line_bottom = line_y + line_h
    visible_top = scroll_y
    visible_bottom = scroll_y + view_h
    margin = min(lookahead, max(0, view_h - 1))
    if line_y >= visible_top and line_bottom <= visible_bottom - margin:
        return None
    if line_y < visible_top:
        target = line_y
    else:
        pin = min(int(view_h * pin_ratio), max(0, view_h - line_h))
        target = line_y - pin
    target = max(0, target)
    return None if target == scroll_y else target


def line_visual_height(plain: str, width: int) -> int:
    """Visual rows of a hunk line at ``width``, matching Textual's Text wrap."""
    if width <= 0:
        return 1
    wrapped = Text(plain).wrap(_MEASURE, width, tab_size=8)
    return max(1, len(wrapped))


class TypingCanvas(VerticalScroll):
    """Hunk view: the body grows with the hunk; this widget scrolls and follows."""

    DEFAULT_CSS = """
    TypingCanvas {
        height: 1fr;
        overflow-x: hidden;
        overflow-y: auto;
        scrollbar-visibility: hidden;
        scrollbar-size: 0 0;
    }
    TypingCanvas > #body {
        width: 1fr;
        height: auto;
        padding: 0;
    }
    """

    def __init__(self, session: Session, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session = session

    def compose(self) -> ComposeResult:
        yield Static(id="body")

    def on_mount(self) -> None:
        self._paint()
        self.focus()

    def on_resize(self, event: Resize) -> None:
        self.call_after_refresh(self._follow_cursor)

    def bump(self) -> None:
        self._paint()

    def _paint(self) -> None:
        text, _span = self._hunk_text(self._wrap_width())
        self.query_one("#body", Static).update(text)
        self.call_after_refresh(self._follow_cursor)

    def _follow_cursor(self) -> None:
        width = self._wrap_width()
        _text, span = self._hunk_text(width)
        if span is None:
            return
        line_y, line_h = span
        view_h = self.scrollable_content_region.height
        target = target_scroll_y(line_y, line_h, view_h, self.scroll_offset.y)
        if target is None:
            return
        self.scroll_to(y=target, animate=False, immediate=True)

    def _wrap_width(self) -> int:
        body = self.query("#body")
        if not body:
            return 0
        return body[0].content_size.width or body[0].size.width

    def _hunk_text(self, width: int) -> tuple[Text, tuple[int, int] | None]:
        view = self.session.view()
        if view.done:
            out = Text()
            out.append("All lessons done.\n", style=pal.ADD_TYPED)
            out.append(
                "Each lesson was typed against its origin parent.",
                style=pal.STATUS_DIM,
            )
            return out, None

        current_i = next((i for i, line in enumerate(view.lines) if line.is_current), None)
        out = Text()
        span: tuple[int, int] | None = None
        y = 0
        for i, line in enumerate(view.lines):
            past = current_i is None or i < current_i
            row = Text()
            row.append(f"{line.gutter} ", style=self._gutter_style(line))
            row.append_text(self._body(line, past=past))
            height = line_visual_height(row.plain, width)
            if i == current_i:
                span = (y, height)
            y += height
            out.append_text(row)
            out.append("\n")
        return out, span

    def _gutter_style(self, line: ViewLine) -> str:
        if line.kind == "DEL":
            return pal.GUTTER_DEL
        if line.kind == "ADD":
            return pal.GUTTER_ADD
        return pal.GUTTER_CTX

    def _body(self, line: ViewLine, *, past: bool) -> Text:
        if line.kind == "CTX" or line.skip:
            return Text(line.display, style=pal.CTX)
        if line.kind == "DEL":
            return self._del_body(line, past=past)
        return self._add_body(line, past=past)

    def _del_body(self, line: ViewLine, *, past: bool) -> Text:
        text = Text()
        if not line.is_current:
            style = pal.DEL_EATEN if past else pal.DEL
            text.append(line.display, style=style)
            return text
        still = line.display[: line.remaining]
        eaten = line.display[line.remaining :]
        if still:
            if len(still) > 1:
                text.append(still[:-1], style=pal.DEL)
            text.append(still[-1], style=pal.CURSOR)
        else:
            text.append(" ", style=pal.CURSOR)
        if eaten:
            text.append(eaten, style=pal.DEL_EATEN)
        return text

    def _add_body(self, line: ViewLine, *, past: bool) -> Text:
        text = Text()
        if not line.is_current:
            style = pal.ADD_TYPED if past else pal.ADD_UNTYPED
            text.append(line.typing, style=style)
            if line.comment_suffix:
                text.append(line.comment_suffix, style=pal.COMMENT)
            return text

        typed, untyped = line.typing[: line.col], line.typing[line.col :]
        if typed:
            text.append(typed, style=pal.ADD_TYPED)
        if line.col >= len(line.typing):
            text.append("⏎", style=pal.CURSOR)
        elif untyped:
            text.append(untyped[0], style=pal.MISS if line.miss else pal.CURSOR)
            if untyped[1:]:
                text.append(untyped[1:], style=pal.ADD_UNTYPED)
        if line.comment_suffix:
            text.append(line.comment_suffix, style=pal.COMMENT)
        return text
