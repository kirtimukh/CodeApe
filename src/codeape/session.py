from __future__ import annotations

import time
from dataclasses import dataclass

from codeape.apply import apply_hunks, delete_file, replay_commit, write_file
from codeape.comments import split_code_and_comment
from codeape.diff_engine import Hunk, commit_hunks
from codeape.history import commit_meta, file_at
from codeape.paths import RepoPaths
from codeape.progress import Current, HunkCursor, Progress
from codeape.tokens import leading_indent, tab_target


@dataclass
class SessionLine:
    kind: str
    display: str
    typing: str
    comment_suffix: str
    skip: bool
    col: int = 0
    miss: bool = False
    remaining: int = 0


@dataclass
class PreparedHunk:
    hunk: Hunk
    lines: list[SessionLine]

    @property
    def is_skippable(self) -> bool:
        return all(line.skip for line in self.lines)


@dataclass
class ViewLine:
    kind: str
    gutter: str
    display: str
    typing: str
    comment_suffix: str
    col: int
    remaining: int
    skip: bool
    is_current: bool
    miss: bool


@dataclass
class ViewState:
    done: bool
    sha: str
    subject: str
    commit_index: int
    commit_total: int
    file: str
    files: list[str]
    file_index: int
    file_total: int
    hunk_index: int
    hunk_total: int
    lines: list[ViewLine]
    current_kind: str
    wpm: float
    accuracy: float
    chars_typed: int
    misses: int
    chars_assisted: int


def _prepare_line(kind: str, content: str, filename: str) -> SessionLine:
    code, suffix, comment_only = split_code_and_comment(content, filename)
    if kind == "CTX" or comment_only:
        return SessionLine(
            kind=kind,
            display=content,
            typing="",
            comment_suffix=suffix if kind == "ADD" else "",
            skip=True,
        )
    if kind == "ADD":
        return SessionLine(
            kind=kind,
            display=content,
            typing=code,
            comment_suffix=suffix,
            skip=False,
        )
    return SessionLine(
        kind="DEL",
        display=content,
        typing=content,
        comment_suffix="",
        skip=content == "",
        remaining=len(content),
    )


def _prepare_hunk(hunk: Hunk) -> PreparedHunk:
    lines = [_prepare_line(line.kind, line.content, hunk.path) for line in hunk.lines]
    return PreparedHunk(hunk=hunk, lines=lines)


class Session:
    def __init__(self, paths: RepoPaths, progress: Progress, *, apply: bool = True):
        self.paths = paths
        self.progress = progress
        self.done = progress.current.sha is None
        self._hunks: list[Hunk] = []
        self._prepared: list[PreparedHunk] = []
        self._parent_files: dict[str, list[str] | None] = {}
        self._added_files: dict[str, list[str]] = {}
        self._done_set: set[int] = set()
        self._cursors: dict[int, int] = {}
        self._file_cursor: dict[str, int] = {}
        self._parent_sha: str | None = None
        self._line_i = 0
        self._subject = ""
        self._session_start = time.monotonic()
        self._time_base = progress.stats.time_ms
        if not self.done:
            self._load_commit(restore=apply)
            if apply:
                self._advance_to_typable()

    def time_ms(self) -> int:
        elapsed = int((time.monotonic() - self._session_start) * 1000)
        return self._time_base + elapsed

    def persist(self) -> None:
        self.progress.stats.time_ms = self.time_ms()
        self._snapshot_typing()
        self.progress.save(self.paths.progress_file)

    def _save(self) -> None:
        self.persist()

    def _line_offset(self, hunk_i: int, line_i: int) -> tuple[int, int | None]:
        if not (0 <= hunk_i < len(self._prepared)):
            return 0, None
        lines = self._prepared[hunk_i].lines
        if not (0 <= line_i < len(lines)):
            return 0, None
        line = lines[line_i]
        if line.kind == "DEL":
            return line.col, line.remaining
        return line.col, None

    def _snapshot_typing(self) -> None:
        current = self.progress.current
        if self.done or current.sha is None:
            current.line = 0
            current.col = 0
            current.remaining = None
            current.cursors = []
            return
        self._save_cursor()
        cursors: list[HunkCursor] = []
        for hunk_i, line_i in sorted(self._cursors.items()):
            if hunk_i in self._done_set or not (0 <= hunk_i < len(self._prepared)):
                continue
            col, remaining = self._line_offset(hunk_i, line_i)
            cursors.append(
                HunkCursor(hunk=hunk_i, line=line_i, col=col, remaining=remaining)
            )
        current.cursors = cursors
        current.line = self._line_i
        current.col, current.remaining = self._line_offset(current.hunk, self._line_i)

    def _restore_saved_cursors(self) -> None:
        current = self.progress.current
        positions = {cursor.hunk: cursor for cursor in current.cursors}
        if (
            current.hunk not in positions
            and (current.line or current.col or current.remaining is not None)
        ):
            positions[current.hunk] = HunkCursor(
                hunk=current.hunk,
                line=current.line,
                col=current.col,
                remaining=current.remaining,
            )
        for hunk_i, cursor in positions.items():
            if hunk_i in self._done_set or not (0 <= hunk_i < len(self._prepared)):
                continue
            self._cursors[hunk_i] = cursor.line
            self._file_cursor[self._hunks[hunk_i].path] = hunk_i
            lines = self._prepared[hunk_i].lines
            if not (0 <= cursor.line < len(lines)):
                continue
            line = lines[cursor.line]
            if line.kind == "ADD":
                line.col = min(max(cursor.col, 0), len(line.typing))
            elif line.kind == "DEL" and cursor.remaining is not None:
                line.remaining = min(max(cursor.remaining, 0), len(line.display))
        if current.hunk in self._cursors:
            self._line_i = self._cursors[current.hunk]

    def _parent_of(self, sha: str) -> str | None:
        shas = self.progress.first_parent_shas
        idx = shas.index(sha)
        return shas[idx - 1] if idx > 0 else None

    def _load_commit(self, restore: bool = True) -> None:
        sha = self.progress.current.sha
        if sha is None:
            self.done = True
            return
        self._parent_sha = self._parent_of(sha)
        self._subject = commit_meta(self.paths.mirror, sha).subject
        self._hunks = commit_hunks(self.paths.mirror, self._parent_sha, sha)
        self._prepared = [_prepare_hunk(h) for h in self._hunks]
        self._parent_files = {}
        self._added_files = {}
        self._cursors = {}
        self._file_cursor = {}
        self._done_set = {
            i
            for i in self.progress.current.done_hunks
            if 0 <= i < len(self._hunks)
        }
        self._sync_done()
        for hunk in self._hunks:
            if hunk.path not in self._parent_files:
                self._parent_files[hunk.path] = file_at(
                    self.paths.mirror, self._parent_sha, hunk.path
                )
            if (
                self._parent_files[hunk.path] is None
                and hunk.path not in self._added_files
            ):
                added = file_at(self.paths.mirror, sha, hunk.path)
                if added is not None:
                    self._added_files[hunk.path] = added
        if restore:
            self._restore_workspace()
        self._line_i = 0
        if self._hunks and 0 <= self.progress.current.hunk < len(self._hunks):
            self.progress.current.file = self._hunks[self.progress.current.hunk].path
        self._restore_saved_cursors()
        self._skip_non_targets()

    def _restore_workspace(self) -> None:
        """Reset current-commit files from the parent tree, then replay completed hunks.

        Newly added files are written from the commit tree immediately so imports
        in files the user is typing already exist in the workspace.
        """
        by_path: dict[str, list[Hunk]] = {}
        for i, hunk in enumerate(self._hunks):
            if i in self._done_set:
                by_path.setdefault(hunk.path, []).append(hunk)
        for path, original in self._parent_files.items():
            self._write_path(path, original, by_path.get(path, []))

    def _write_path(
        self, path: str, original: list[str] | None, applied: list[Hunk]
    ) -> None:
        all_for_path = [h for h in self._hunks if h.path == path]
        done_all = applied and len(applied) == len(all_for_path)
        added = self._added_files.get(path)
        if added is not None and not done_all:
            write_file(self.paths.workspace, path, added)
            return
        if not applied:
            if original is None:
                delete_file(self.paths.workspace, path)
            else:
                write_file(self.paths.workspace, path, original)
            return
        lines = apply_hunks(original, applied)
        if done_all and all_for_path[-1].is_removed_file:
            delete_file(self.paths.workspace, path)
            return
        write_file(self.paths.workspace, path, lines)

    def _sync_done(self) -> None:
        self.progress.current.done_hunks = sorted(self._done_set)

    def _apply_file(self, path: str) -> None:
        applied = [
            hunk
            for i, hunk in enumerate(self._hunks)
            if i in self._done_set and hunk.path == path
        ]
        self._write_path(path, self._parent_files.get(path), applied)

    def _mark_done(self, indices: list[int] | None = None) -> None:
        if indices is None:
            indices = [i for i in range(len(self._hunks)) if i not in self._done_set]
        dirty: set[str] = set()
        for i in indices:
            if i in self._done_set or not (0 <= i < len(self._hunks)):
                continue
            self._done_set.add(i)
            self._cursors.pop(i, None)
            dirty.add(self._hunks[i].path)
        for path in dirty:
            self._apply_file(path)
        self._sync_done()

    def _file_paths(self) -> list[str]:
        return list(dict.fromkeys(hunk.path for hunk in self._hunks))

    def _nav_files(self) -> list[str]:
        """Files the user can switch to: still-typable changes, plus new files."""
        return [
            path
            for path in self._file_paths()
            if path in self._added_files or self._first_typable_hunk(path) is not None
        ]

    def _first_typable_hunk(self, path: str) -> int | None:
        for i, hunk in enumerate(self._hunks):
            if (
                hunk.path == path
                and i not in self._done_set
                and not self._prepared[i].is_skippable
            ):
                return i
        return None

    def _next_typable_hunk(self, *, prefer_file: str | None) -> int | None:
        files = self._file_paths()
        if prefer_file in files:
            start = files.index(prefer_file)
            files = files[start:] + files[:start]
        for path in files:
            found = self._first_typable_hunk(path)
            if found is not None:
                return found
        return None

    def _save_cursor(self) -> None:
        hunk_i = self.progress.current.hunk
        if 0 <= hunk_i < len(self._hunks):
            self._cursors[hunk_i] = self._line_i
            self._file_cursor[self._hunks[hunk_i].path] = hunk_i

    def _focus_hunk(self, hunk_i: int) -> None:
        self.progress.current.hunk = hunk_i
        self.progress.current.file = self._hunks[hunk_i].path
        self._file_cursor[self._hunks[hunk_i].path] = hunk_i
        if hunk_i in self._done_set:
            self._line_i = len(self._prepared[hunk_i].lines)
            return
        self._line_i = self._cursors.get(hunk_i, 0)
        self._skip_non_targets()

    def _complete_skippable(self) -> None:
        self._mark_done(
            [
                i
                for i, prepared in enumerate(self._prepared)
                if i not in self._done_set and prepared.is_skippable
            ]
        )

    def _skip_non_targets(self) -> None:
        if self.done or self.progress.current.hunk >= len(self._prepared):
            return
        lines = self._prepared[self.progress.current.hunk].lines
        while self._line_i < len(lines) and lines[self._line_i].skip:
            self._line_i += 1
        self._place_at_code_start()

    def _place_at_code_start(self) -> None:
        line = self._current_line()
        if line is None or line.kind != "ADD" or line.col != 0:
            return
        indent = leading_indent(line.typing)
        if indent:
            line.col = indent

    def _hunk_done(self) -> bool:
        hunk_i = self.progress.current.hunk
        if hunk_i >= len(self._prepared) or hunk_i in self._done_set:
            return True
        return self._line_i >= len(self._prepared[hunk_i].lines)

    def _advance_to_typable(self) -> None:
        while not self.done:
            sha = self.progress.current.sha
            if sha is None:
                self.done = True
                self._save()
                return
            if not self._hunks:
                self._finish_commit(empty=True)
                continue
            self._complete_skippable()
            hunk_i = self.progress.current.hunk
            if (
                0 <= hunk_i < len(self._prepared)
                and hunk_i not in self._done_set
                and not self._prepared[hunk_i].is_skippable
            ):
                nxt = hunk_i
            else:
                nxt = self._next_typable_hunk(prefer_file=self.progress.current.file)
            if nxt is None:
                self._finish_commit(empty=False)
                continue
            self._focus_hunk(nxt)
            if self._hunk_done():
                self._complete_hunk()
                continue
            self._save()
            return

    def _complete_hunk(self) -> None:
        self._mark_done([self.progress.current.hunk])
        self._line_i = 0
        self._save()

    def _finish_commit(self, empty: bool) -> None:
        sha = self.progress.current.sha
        assert sha is not None
        meta = commit_meta(self.paths.mirror, sha)
        replayed = False if empty else replay_commit(self.paths.workspace, meta)
        self.progress.completed_shas.append(sha)
        if empty or not replayed:
            if sha not in self.progress.skipped.shas:
                self.progress.skipped.shas.append(sha)
        shas = self.progress.first_parent_shas
        idx = shas.index(sha)
        if idx + 1 < len(shas):
            nxt = shas[idx + 1]
            self.progress.current = Current(sha=nxt, file="", hunk=0)
            self.done = False
            self._load_commit()
        else:
            self.progress.current = Current(sha=None, file="", hunk=0)
            self.done = True
        self._save()

    def _current_line(self) -> SessionLine | None:
        if self.done or self.progress.current.hunk >= len(self._prepared):
            return None
        lines = self._prepared[self.progress.current.hunk].lines
        if self._line_i >= len(lines):
            return None
        return lines[self._line_i]

    def _after_line(self) -> None:
        self._line_i += 1
        self._skip_non_targets()
        if self._hunk_done():
            self._complete_hunk()
            self._advance_to_typable()

    def on_char(self, ch: str) -> None:
        line = self._current_line()
        if line is None or line.kind != "ADD":
            return
        if line.col >= len(line.typing):
            return
        expected = line.typing[line.col]
        if ch == expected:
            line.col += 1
            line.miss = False
            self.progress.stats.chars_typed += 1
        else:
            line.miss = True
            self.progress.stats.misses += 1

    def on_enter(self) -> None:
        line = self._current_line()
        if line is None or line.kind != "ADD":
            return
        if line.col >= len(line.typing):
            self._after_line()

    def on_backspace(self) -> None:
        line = self._current_line()
        if line is None:
            return
        if line.kind == "ADD":
            if line.col > 0:
                line.col -= 1
                line.miss = False
            return
        if line.kind == "DEL" and line.remaining > 0:
            line.remaining -= 1
            if line.remaining == 0:
                self._after_line()

    def on_tab(self) -> None:
        line = self._current_line()
        if line is None or line.kind != "ADD":
            return
        target = tab_target(line.typing, line.col)
        if target is None or target <= line.col:
            return
        self.progress.stats.chars_assisted += target - line.col
        line.col = target
        line.miss = False

    def on_accept_del(self) -> None:
        line = self._current_line()
        if line is None or line.kind != "DEL":
            return
        line.remaining = 0
        self._after_line()

    def skip_hunk(self) -> None:
        if self.done:
            return
        self._complete_hunk()
        self._advance_to_typable()

    def skip_commit(self) -> None:
        if self.done or self.progress.current.sha is None:
            return
        self._mark_done()
        self._save()
        if not self.done:
            self._advance_to_typable()

    def next_file(self) -> None:
        self._step_file(1)

    def prev_file(self) -> None:
        self._step_file(-1)

    def _step_file(self, delta: int) -> None:
        if self.done:
            return
        files = self._nav_files()
        if len(files) < 2:
            return
        self._save_cursor()
        current = self.progress.current.file
        if current not in files:
            target = files[0] if delta > 0 else files[-1]
            self._focus_file(target)
            self._save()
            return
        idx = files.index(current)
        self._focus_file(files[(idx + delta) % len(files)])
        self._save()

    def _focus_file(self, path: str) -> None:
        last = self._file_cursor.get(path)
        if (
            last is not None
            and last not in self._done_set
            and 0 <= last < len(self._hunks)
            and self._hunks[last].path == path
        ):
            hunk_i = last
        else:
            hunk_i = self._first_typable_hunk(path)
            if hunk_i is None:
                matches = [i for i, hunk in enumerate(self._hunks) if hunk.path == path]
                if not matches:
                    return
                hunk_i = matches[-1]
        self._focus_hunk(hunk_i)

    def view(self) -> ViewState:
        shas = self.progress.first_parent_shas
        sha = self.progress.current.sha or (shas[-1] if shas else "")
        commit_index = len(self.progress.completed_shas) + (0 if self.done else 1)
        files = self._nav_files()
        current_file = self.progress.current.file
        if current_file in files:
            file_index = files.index(current_file) + 1
        else:
            file_index = 1 if files else 0
        hunks_in_file = [
            i for i, h in enumerate(self._hunks) if h.path == current_file
        ]
        if self.progress.current.hunk in hunks_in_file:
            hunk_index = hunks_in_file.index(self.progress.current.hunk) + 1
        else:
            hunk_index = 1 if hunks_in_file else 0
        lines: list[ViewLine] = []
        current_kind = ""
        if not self.done and self.progress.current.hunk < len(self._prepared):
            prepared = self._prepared[self.progress.current.hunk]
            for i, line in enumerate(prepared.lines):
                gutter = {"ADD": "+", "DEL": "-", "CTX": " "}.get(line.kind, " ")
                is_current = i == self._line_i
                if is_current:
                    current_kind = line.kind
                lines.append(
                    ViewLine(
                        kind=line.kind,
                        gutter=gutter,
                        display=line.display,
                        typing=line.typing,
                        comment_suffix=line.comment_suffix,
                        col=line.col,
                        remaining=line.remaining,
                        skip=line.skip,
                        is_current=is_current,
                        miss=line.miss,
                    )
                )
        typed = self.progress.stats.chars_typed
        misses = self.progress.stats.misses
        minutes = self.time_ms() / 60000
        wpm = (typed / 5) / minutes if minutes > 0 else 0.0
        denom = typed + misses
        accuracy = typed / denom if denom else 1.0
        return ViewState(
            done=self.done,
            sha=sha,
            subject=self._subject,
            commit_index=commit_index,
            commit_total=len(shas),
            file=current_file,
            files=files,
            file_index=file_index,
            file_total=len(files),
            hunk_index=hunk_index,
            hunk_total=len(hunks_in_file),
            lines=lines,
            current_kind=current_kind,
            wpm=wpm,
            accuracy=accuracy,
            chars_typed=typed,
            misses=misses,
            chars_assisted=self.progress.stats.chars_assisted,
        )
