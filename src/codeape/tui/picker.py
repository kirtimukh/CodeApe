from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, OptionList, Static
from textual.widgets.option_list import Option

from codeape.history import commit_meta, first_parent_shas
from codeape.paths import RepoEntry, load_repo_paths
from codeape.progress import Progress
from codeape.session import LessonRow
from codeape.tui import palette as pal


def _repo_label(entry: RepoEntry) -> str:
    paths = load_repo_paths(entry.id)
    progress = Progress.load(paths.progress_file)
    shas = first_parent_shas(paths.mirror)
    if progress.current_target is None:
        detail = f"done  {len(shas)} commits"
    else:
        meta = commit_meta(paths.mirror, progress.current_target)
        attempt = progress.attempts.get(progress.current_target)
        status = attempt.status if attempt else "in_progress"
        detail = f"{status}  {progress.current_target[:7]}  {meta.subject}"
    return f"{entry.id}  {entry.name}    {detail}"


class RepoPickerApp(App[int | None]):
    CSS = f"""
    Screen {{
        background: {pal.BACKGROUND};
        color: {pal.ADD_TYPED};
    }}
    #title {{
        padding: 1 2 0 2;
    }}
    #repos {{
        padding: 1 2;
    }}
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "quit", "Quit"),
    ]

    def __init__(self, repos: list[RepoEntry]) -> None:
        super().__init__()
        self.repos = repos

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Select a repository", id="title")
            options = [
                Option(_repo_label(entry), id=str(entry.id)) for entry in self.repos
            ]
            yield OptionList(*options, id="repos")
        yield Footer()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.exit(int(str(event.option_id)))

    def action_quit(self) -> None:
        self.exit(None)


class LessonSwitcher(ModalScreen[str | None]):
    CSS = f"""
    LessonSwitcher {{
        align: center middle;
    }}
    #lesson-box {{
        width: 80%;
        height: auto;
        max-height: 80%;
        background: {pal.BACKGROUND};
        color: {pal.ADD_TYPED};
        padding: 1 2;
        border: solid {pal.STATUS};
    }}
    """
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
    ]

    def __init__(self, rows: list[LessonRow]) -> None:
        super().__init__()
        self.rows = rows

    def compose(self) -> ComposeResult:
        with Vertical(id="lesson-box"):
            yield Static("Switch lesson")
            options = []
            for row in self.rows:
                mark = "*" if row.current else " "
                options.append(
                    Option(
                        f"{mark} {row.index:3}  {row.sha[:7]}  {row.status:12}  {row.subject}",
                        id=row.sha,
                    )
                )
            yield OptionList(*options, id="lessons")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option_id))

    def action_cancel(self) -> None:
        self.dismiss(None)
