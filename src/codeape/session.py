from __future__ import annotations

import time
from dataclasses import dataclass

from codeape.apply import (
    apply_attempt,
    apply_hunks,
    delete_file,
    snapshot_attempt,
    write_file,
)
from codeape.diff_engine import DiffLine, Hunk, commit_hunks
from codeape.history import (
    checkout_parent,
    commit_meta,
    file_at,
    first_parent_shas,
    first_parent_subjects,
)
from codeape.paths import RepoPaths
from codeape.progress import (
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_SKIPPED,
    Attempt,
    HunkCursor,
    Progress,
)
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
class LessonRow:
    sha: str
    subject: str
    status: str
    current: bool
    index: int


@dataclass
class ViewState:
    done: bool
    sha: str
    subject: str
    commit_index: int
    commit_total: int
    attempt_status: str
    completed_count: int
    skipped_count: int
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


def _prepare_line(kind: str, content: str) -> SessionLine:
    if kind == "CTX":
        return SessionLine(
            kind=kind,
            display=content,
            typing="",
            comment_suffix="",
            skip=True,
        )
    if kind == "ADD":
        return SessionLine(
            kind=kind,
            display=content,
            typing=content,
            comment_suffix="",
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
    lines = [_prepare_line(line.kind, line.content) for line in hunk.lines]
    return PreparedHunk(hunk=hunk, lines=lines)


class Session:
    def __init__(self, paths: RepoPaths, progress: Progress, *, apply: bool = True):
        self.paths = paths
        self.progress = progress
        self._shas = first_parent_shas(self.paths.mirror)
        if progress.current_target is None:
            resume = self._first_resumable()
            if resume:
                progress.current_target = resume
        self.done = progress.current_target is None
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
            self._ensure_attempt(progress.current_target)
            self._load_commit(restore=apply)
            if apply:
                self._advance_to_typable()

    def time_ms(self) -> int:
        elapsed = int((time.monotonic() - self._session_start) * 1000)
        return self._time_base + elapsed

    def persist(self) -> None:
        self.progress.stats.time_ms = self.time_ms()
        if not self.done and self.progress.current_target:
            self._materialize_in_progress()
            self._snapshot_typing()
            self._att.patch = snapshot_attempt(self.paths.workspace)
        self.progress.save(self.paths.progress_file)

    def _save(self) -> None:
        self.persist()

    def _persist_status(self, status: str) -> None:
        self.persist()
        if self.progress.current_target:
            self._att.status = status
            self.progress.save(self.paths.progress_file)

    @property
    def _att(self) -> Attempt:
        target = self.progress.current_target
        assert target is not None
        return self.progress.attempts[target]

    def _ensure_attempt(self, target: str | None) -> Attempt | None:
        if target is None:
            return None
        if target not in self.progress.attempts:
            self.progress.attempts[target] = Attempt(
                parent=self._parent_of(target),
                target=target,
            )
        return self.progress.attempts[target]

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
        if self.done or self.progress.current_target is None:
            return
        current = self._att
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
        if self.progress.current_target is None:
            return
        current = self._att
        positions = {cursor.hunk: cursor for cursor in current.cursors}
        if current.hunk not in positions and (
            current.line or current.col or current.remaining is not None
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
        idx = self._shas.index(sha)
        return self._shas[idx - 1] if idx > 0 else None

    def _load_commit(self, restore: bool = True) -> None:
        sha = self.progress.current_target
        if sha is None:
            self.done = True
            return
        attempt = self._ensure_attempt(sha)
        assert attempt is not None
        self._parent_sha = attempt.parent if attempt.parent is not None else self._parent_of(sha)
        attempt.parent = self._parent_sha
        self._subject = commit_meta(self.paths.mirror, sha).subject
        self._hunks = commit_hunks(self.paths.mirror, self._parent_sha, sha)
        self._prepared = [_prepare_hunk(h) for h in self._hunks]
        self._parent_files = {}
        self._added_files = {}
        self._cursors = {}
        self._file_cursor = {}
        self._done_set = {
            i for i in attempt.done_hunks if 0 <= i < len(self._hunks)
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
        if self._hunks and 0 <= attempt.hunk < len(self._hunks):
            attempt.file = self._hunks[attempt.hunk].path
        self._restore_saved_cursors()
        self._skip_non_targets()

    def _restore_workspace(self) -> None:
        checkout_parent(self.paths.workspace, self._parent_sha)
        applied = apply_attempt(self.paths.workspace, self._att.patch)
        if not applied or not self._att.patch.strip():
            self._restore_done_hunks()
        self._write_added_previews()

    def _restore_done_hunks(self) -> None:
        by_path: dict[str, list[Hunk]] = {}
        for i, hunk in enumerate(self._hunks):
            if i in self._done_set:
                by_path.setdefault(hunk.path, []).append(hunk)
        for path, original in self._parent_files.items():
            if path in self._added_files:
                continue
            applied = by_path.get(path, [])
            if not applied:
                continue
            self._write_path(path, original, applied)

    def _write_added_previews(self) -> None:
        for path, added in self._added_files.items():
            dest = self.paths.workspace / path
            if not dest.exists():
                write_file(self.paths.workspace, path, added)

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
        if self.progress.current_target:
            self._att.done_hunks = sorted(self._done_set)

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
        if self.progress.current_target is None:
            return
        hunk_i = self._att.hunk
        if 0 <= hunk_i < len(self._hunks):
            self._cursors[hunk_i] = self._line_i
            self._file_cursor[self._hunks[hunk_i].path] = hunk_i

    def _focus_hunk(self, hunk_i: int) -> None:
        self._att.hunk = hunk_i
        self._att.file = self._hunks[hunk_i].path
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
        if self.done or self.progress.current_target is None:
            return
        if self._att.hunk >= len(self._prepared):
            return
        lines = self._prepared[self._att.hunk].lines
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
        if self.progress.current_target is None:
            return True
        hunk_i = self._att.hunk
        if hunk_i >= len(self._prepared) or hunk_i in self._done_set:
            return True
        return self._line_i >= len(self._prepared[hunk_i].lines)

    def _is_parked(self, sha: str) -> bool:
        attempt = self.progress.attempts.get(sha)
        return attempt is not None and attempt.status in (
            STATUS_COMPLETED,
            STATUS_SKIPPED,
        )

    def _next_unfinished(self, after: str | None) -> str | None:
        start = 0
        if after is not None and after in self._shas:
            start = self._shas.index(after) + 1
        for sha in self._shas[start:]:
            if not self._is_parked(sha):
                return sha
        return None

    def _first_resumable(self) -> str | None:
        for sha in self._shas:
            attempt = self.progress.attempts.get(sha)
            if attempt is not None and attempt.status == STATUS_SKIPPED:
                return sha
            if attempt is not None and attempt.status == STATUS_IN_PROGRESS:
                return sha
        return None

    def _park_or_resume(self, sha: str) -> None:
        nxt = self._next_unfinished(sha)
        if nxt is not None:
            self._open_lesson(nxt)
            return
        resume = self._first_resumable()
        if resume is None:
            self.progress.current_target = None
            self.done = True
            self._save()
            return
        if resume == sha:
            self.done = False
            self._save()
            return
        self._open_lesson(resume)

    def _is_readonly(self) -> bool:
        if self.done or self.progress.current_target is None:
            return True
        return self._att.status == STATUS_COMPLETED

    def _open_lesson(self, target: str, *, auto_advance: bool = True) -> None:
        self.progress.current_target = target
        self.done = False
        self._ensure_attempt(target)
        self._load_commit()
        if auto_advance:
            self._advance_to_typable()

    def _advance_to_typable(self) -> None:
        while not self.done:
            sha = self.progress.current_target
            if sha is None:
                self.done = True
                self._save()
                return
            if not self._hunks:
                self._finish_commit()
                continue
            self._complete_skippable()
            hunk_i = self._att.hunk
            if (
                0 <= hunk_i < len(self._prepared)
                and hunk_i not in self._done_set
                and not self._prepared[hunk_i].is_skippable
            ):
                nxt = hunk_i
            else:
                nxt = self._next_typable_hunk(prefer_file=self._att.file)
            if nxt is None:
                self._finish_commit()
                continue
            self._focus_hunk(nxt)
            if self._hunk_done():
                self._complete_hunk()
                continue
            self._save()
            return

    def _complete_hunk(self) -> None:
        self._mark_done([self._att.hunk])
        self._line_i = 0
        self._save()

    def _finish_commit(self) -> None:
        sha = self.progress.current_target
        assert sha is not None
        self._persist_status(STATUS_COMPLETED)
        self._park_or_resume(sha)

    def _current_line(self) -> SessionLine | None:
        if self._is_readonly():
            return None
        if self._att.hunk >= len(self._prepared):
            return None
        lines = self._prepared[self._att.hunk].lines
        if self._line_i >= len(lines):
            return None
        return lines[self._line_i]

    def _after_line(self) -> None:
        self._line_i += 1
        self._skip_non_targets()
        if self._hunk_done():
            self._complete_hunk()
            self._advance_to_typable()

    def _materialize_in_progress(self) -> None:
        if self.done or self.progress.current_target is None:
            return
        hunk_i = self._att.hunk
        if hunk_i in self._done_set or not (0 <= hunk_i < len(self._hunks)):
            return
        hunk = self._hunks[hunk_i]
        if hunk.path in self._added_files:
            return
        prepared = self._prepared[hunk_i]
        partial: list[DiffLine] = []
        for i, (raw, sl) in enumerate(zip(hunk.lines, prepared.lines)):
            if i < self._line_i:
                partial.append(raw)
                continue
            if i > self._line_i:
                if raw.kind == "ADD":
                    continue
                if raw.kind == "DEL":
                    partial.append(DiffLine("CTX", raw.content))
                else:
                    partial.append(raw)
                continue
            if sl.kind == "ADD":
                typed = sl.typing[: sl.col]
                if typed:
                    partial.append(DiffLine("ADD", typed))
            elif sl.kind == "DEL":
                if sl.remaining <= 0:
                    partial.append(raw)
                elif sl.remaining >= len(sl.display):
                    partial.append(DiffLine("CTX", sl.display))
                else:
                    partial.append(DiffLine("DEL", sl.display))
                    partial.append(DiffLine("ADD", sl.display[: sl.remaining]))
            else:
                partial.append(raw)
        done_for_path = [
            item
            for i, item in enumerate(self._hunks)
            if i in self._done_set and item.path == hunk.path
        ]
        partial_hunk = Hunk(
            path=hunk.path,
            is_added_file=hunk.is_added_file,
            is_removed_file=False,
            source_start=hunk.source_start,
            source_length=hunk.source_length,
            lines=tuple(partial),
        )
        original = self._parent_files.get(hunk.path)
        lines = apply_hunks(original, done_for_path + [partial_hunk])
        if not lines and hunk.is_added_file:
            delete_file(self.paths.workspace, hunk.path)
            return
        write_file(self.paths.workspace, hunk.path, lines)

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
        if line.col >= len(line.typing):
            self._after_line()
            return
        target = tab_target(line.typing, line.col)
        if target is None or target <= line.col:
            return
        self.progress.stats.chars_assisted += target - line.col
        line.col = target
        line.miss = False
        if line.col >= len(line.typing):
            self._after_line()

    def on_line_tab(self) -> None:
        line = self._current_line()
        if line is None or line.kind != "ADD":
            return
        remaining = len(line.typing) - line.col
        if remaining > 0:
            self.progress.stats.chars_assisted += remaining
            line.col = len(line.typing)
            line.miss = False
        self._after_line()

    def on_accept_del(self) -> None:
        line = self._current_line()
        if line is None or line.kind != "DEL":
            return
        line.remaining = 0
        self._after_line()

    def skip_hunk(self) -> None:
        if self._is_readonly():
            return
        self._complete_hunk()
        self._advance_to_typable()

    def skip_commit(self) -> None:
        if self._is_readonly() or self.progress.current_target is None:
            return
        sha = self.progress.current_target
        self._persist_status(STATUS_SKIPPED)
        self._park_or_resume(sha)

    def switch_lesson(self, target: str) -> None:
        if target not in self._shas:
            return
        if not self.done and self.progress.current_target:
            current = self.progress.attempts.get(self.progress.current_target)
            if current is None or current.status == STATUS_IN_PROGRESS:
                self._persist_status(STATUS_IN_PROGRESS)
            else:
                self.persist()
        auto = True
        existing = self.progress.attempts.get(target)
        if existing is not None and existing.status == STATUS_COMPLETED:
            auto = False
        self._open_lesson(target, auto_advance=auto)

    def next_file(self) -> None:
        self._step_file(1)

    def prev_file(self) -> None:
        self._step_file(-1)

    def _step_file(self, delta: int) -> None:
        if self.done or self.progress.current_target is None:
            return
        files = self._nav_files()
        if len(files) < 2:
            return
        self._save_cursor()
        current = self._att.file
        if current not in files:
            dest = files[0] if delta > 0 else files[-1]
            self._focus_file(dest)
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

    def lessons(self) -> list[LessonRow]:
        rows: list[LessonRow] = []
        for index, (sha, subject) in enumerate(
            first_parent_subjects(self.paths.mirror), start=1
        ):
            attempt = self.progress.attempts.get(sha)
            status = attempt.status if attempt else "pending"
            rows.append(
                LessonRow(
                    sha=sha,
                    subject=subject,
                    status=status,
                    current=sha == self.progress.current_target,
                    index=index,
                )
            )
        return rows

    def view(self) -> ViewState:
        sha = self.progress.current_target or (self._shas[-1] if self._shas else "")
        if self.progress.current_target and self.progress.current_target in self._shas:
            commit_index = self._shas.index(self.progress.current_target) + 1
        elif self.done:
            commit_index = len(self._shas)
        else:
            commit_index = 1 if self._shas else 0
        files = self._nav_files()
        current_file = self._att.file if self.progress.current_target else ""
        if current_file in files:
            file_index = files.index(current_file) + 1
        else:
            file_index = 1 if files else 0
        hunks_in_file = [
            i for i, h in enumerate(self._hunks) if h.path == current_file
        ]
        hunk_i = self._att.hunk if self.progress.current_target else -1
        if hunk_i in hunks_in_file:
            hunk_index = hunks_in_file.index(hunk_i) + 1
        else:
            hunk_index = 1 if hunks_in_file else 0
        lines: list[ViewLine] = []
        current_kind = ""
        if (
            not self.done
            and self.progress.current_target
            and hunk_i < len(self._prepared)
        ):
            prepared = self._prepared[hunk_i]
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
        completed = sum(
            1
            for attempt in self.progress.attempts.values()
            if attempt.status == STATUS_COMPLETED
        )
        skipped = sum(
            1
            for attempt in self.progress.attempts.values()
            if attempt.status == STATUS_SKIPPED
        )
        attempt_status = ""
        if self.progress.current_target:
            attempt_status = self._att.status
        return ViewState(
            done=self.done,
            sha=sha,
            subject=self._subject,
            commit_index=commit_index,
            commit_total=len(self._shas),
            attempt_status=attempt_status,
            completed_count=completed,
            skipped_count=skipped,
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
