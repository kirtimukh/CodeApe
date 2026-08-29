from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from codeape.session import Session, ViewLine
from codeape.tui import palette as pal


class TypingCanvas(Static):
    tick = reactive(0)

    def __init__(self, session: Session, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session = session

    def bump(self) -> None:
        self.tick += 1

    def render(self) -> Text:
        view = self.session.view()
        if view.done:
            out = Text()
            out.append("All commits recreated.\n", style=pal.ADD_TYPED)
            out.append(
                "The workspace is a git repo you typed by hand.",
                style=pal.STATUS_DIM,
            )
            return out

        current_i = next((i for i, line in enumerate(view.lines) if line.is_current), None)
        out = Text()
        for i, line in enumerate(view.lines):
            past = current_i is not None and i < current_i
            out.append(f"{line.gutter} ", style=self._gutter_style(line))
            out.append_text(self._body(line, past=past))
            out.append("\n")
        return out

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
