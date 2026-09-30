from __future__ import annotations

from typing import TypeVar

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

LESSON_PAGE_SIZE = 20

T = TypeVar("T")


def paginate(
    items: list[T], page: int, size: int = LESSON_PAGE_SIZE
) -> tuple[list[T], int, int]:
    if not items:
        return [], 0, 1
    pages = (len(items) + size - 1) // size
    page = max(0, min(page, pages - 1))
    start = page * size
    return items[start : start + size], page, pages


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
    CSS = """
    #title {
        padding: 1 2 0 2;
    }
    #repos {
        padding: 1 2;
    }
    """
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "quit", "Quit"),
    ]

    def __init__(self, repos: list[RepoEntry]) -> None:
        super().__init__()
        self.repos = repos

    def on_mount(self) -> None:
        pal.apply_app(self)

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
    CSS = """
    LessonSwitcher {
        align: center middle;
    }
    #lesson-box {
        width: 80%;
        height: auto;
        max-height: 80%;
        padding: 1 2;
    }
    """
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
        Binding("left", "page_prev", "Prev page"),
        Binding("right", "page_next", "Next page"),
        Binding("pageup", "page_prev", "Prev page", show=False),
        Binding("pagedown", "page_next", "Next page", show=False),
    ]

    def __init__(self, rows: list[LessonRow]) -> None:
        super().__init__()
        self.rows = rows
        current_i = next((i for i, row in enumerate(rows) if row.current), 0)
        self.page = current_i // LESSON_PAGE_SIZE

    def compose(self) -> ComposeResult:
        with Vertical(id="lesson-box"):
            yield Static("Switch lesson", id="lesson-title")
            yield OptionList(id="lessons")

    def on_mount(self) -> None:
        pal.apply_colors(self.query_one("#lesson-box"), border=True)
        self._render_page()

    def _render_page(self) -> None:
        visible, self.page, pages = paginate(self.rows, self.page)
        title = self.query_one("#lesson-title", Static)
        title.update(f"Switch lesson  ({self.page + 1}/{pages})")
        listing = self.query_one("#lessons", OptionList)
        listing.clear_options()
        for row in visible:
            mark = "*" if row.current else " "
            listing.add_option(
                Option(
                    f"{mark} {row.index:3}  {row.sha[:7]}  {row.status:12}  {row.subject}",
                    id=row.sha,
                )
            )
        if visible:
            current = next((i for i, row in enumerate(visible) if row.current), 0)
            listing.highlighted = current
        listing.focus()

    def action_page_next(self) -> None:
        _, _, pages = paginate(self.rows, self.page)
        if self.page + 1 < pages:
            self.page += 1
            self._render_page()

    def action_page_prev(self) -> None:
        if self.page > 0:
            self.page -= 1
            self._render_page()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option_id))

    def action_cancel(self) -> None:
        self.dismiss(None)
