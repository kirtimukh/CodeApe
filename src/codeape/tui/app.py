from __future__ import annotations

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Key
from textual.widgets import Footer, Static

from codeape.session import Session
from codeape.tui import palette as pal
from codeape.tui.canvas import TypingCanvas


class StatusBar(Static):
    def __init__(self, session: Session, **kwargs) -> None:
        super().__init__(**kwargs)
        self.session = session

    def render(self) -> Text:
        view = self.session.view()
        out = Text()
        if view.done:
            out.append("Done  ", style=pal.ADD_TYPED)
            out.append(
                f"{view.commit_total}/{view.commit_total} commits",
                style=pal.STATUS_DIM,
            )
            return out
        short = view.sha[:7] if view.sha else ""
        out.append("Recreating  ", style=pal.STATUS_DIM)
        out.append(f"{short}  ", style=pal.STATUS)
        out.append(view.subject or "", style=pal.ADD_UNTYPED)
        out.append("\n")
        out.append(
            f"  {view.commit_index} / {view.commit_total} commits"
            f"  ·  file {view.file_index}/{view.file_total}"
            f"  ·  hunk {view.hunk_index}/{view.hunk_total}",
            style=pal.STATUS_DIM,
        )
        out.append("\n")
        out.append(f"  {view.file}", style=pal.STATUS)
        out.append(
            f"    {view.wpm:.0f} wpm  {view.accuracy * 100:.0f}%"
            f"  tab {view.chars_assisted}",
            style=pal.STATUS_DIM,
        )
        return out


class CodeApeApp(App):
    CSS = f"""
    Screen {{
        background: {pal.BACKGROUND};
        color: {pal.ADD_TYPED};
    }}
    #status {{
        padding: 1 2 0 2;
        height: auto;
    }}
    #canvas {{
        padding: 1 2;
        height: 1fr;
    }}
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+s", "skip_hunk", "Skip hunk"),
        Binding("ctrl+k", "skip_commit", "Skip commit"),
        Binding("ctrl+d", "accept_del", "Accept del"),
        Binding("tab", "tab", "Tab", show=False, priority=True),
    ]

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session

    def compose(self) -> ComposeResult:
        with Vertical():
            yield StatusBar(self.session, id="status")
            yield TypingCanvas(self.session, id="canvas")
        yield Footer()

    def _refresh_view(self) -> None:
        self.query_one(StatusBar).refresh()
        canvas = self.query_one(TypingCanvas)
        canvas.bump()
        canvas.refresh()
        if self.session.done:
            self.session.persist()

    def on_key(self, event: Key) -> None:
        if event.key in {"tab", "ctrl+s", "ctrl+k", "ctrl+d", "ctrl+q"}:
            return
        if event.key == "enter":
            self.session.on_enter()
            event.prevent_default()
        elif event.key == "backspace":
            self.session.on_backspace()
            event.prevent_default()
        elif event.is_printable and event.character:
            self.session.on_char(event.character)
            event.prevent_default()
        else:
            return
        self._refresh_view()

    def action_tab(self) -> None:
        self.session.on_tab()
        self._refresh_view()

    def action_skip_hunk(self) -> None:
        self.session.skip_hunk()
        self._refresh_view()

    def action_skip_commit(self) -> None:
        self.session.skip_commit()
        self._refresh_view()

    def action_accept_del(self) -> None:
        self.session.on_accept_del()
        self._refresh_view()

    def action_quit(self) -> None:
        self.session.persist()
        self.exit()
