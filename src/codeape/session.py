from __future__ import annotations

import time
from dataclasses import dataclass

from codeape.apply import apply_hunks, delete_file, replay_commit, write_file
from codeape.comments import split_code_and_comment
from codeape.diff_engine import Hunk, commit_hunks
from codeape.history import commit_meta, file_at
from codeape.paths import RepoPaths
from codeape.progress import Current, Progress
from codeape.tokens import tab_target


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
        self.progress.save(self.paths.progress_file)

    def _save(self) -> None:
        self.persist()

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
        for hunk in self._hunks:
            if hunk.path not in self._parent_files:
                self._parent_files[hunk.path] = file_at(
                    self.paths.mirror, self._parent_sha, hunk.path
                )
        if restore:
            self._restore_workspace()
        self._line_i = 0
        if self._hunks and self.progress.current.hunk < len(self._hunks):
            self.progress.current.file = self._hunks[self.progress.current.hunk].path
        self._skip_non_targets()

    def _restore_workspace(self) -> None:
        """Reset current-commit files from the parent tree, then replay completed hunks."""
        completed = self.progress.current.hunk
        by_path: dict[str, list[Hunk]] = {}
        for hunk in self._hunks[:completed]:
            by_path.setdefault(hunk.path, []).append(hunk)
        for path, original in self._parent_files.items():
            applied = by_path.get(path, [])
            self._write_path(path, original, applied)

    def _write_path(
        self, path: str, original: list[str] | None, applied: list[Hunk]
    ) -> None:
        all_for_path = [h for h in self._hunks if h.path == path]
        done_all = applied and len(applied) == len(all_for_path)
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

    def _apply_completed_prefix(self) -> None:
        completed = self.progress.current.hunk
        if completed <= 0:
            return
        path = self._hunks[completed - 1].path
        applied = [h for h in self._hunks[:completed] if h.path == path]
        self._write_path(path, self._parent_files.get(path), applied)

    def _skip_non_targets(self) -> None:
        if self.done or self.progress.current.hunk >= len(self._prepared):
            return
        lines = self._prepared[self.progress.current.hunk].lines
        while self._line_i < len(lines) and lines[self._line_i].skip:
            self._line_i += 1

    def _hunk_done(self) -> bool:
        if self.progress.current.hunk >= len(self._prepared):
            return True
        return self._line_i >= len(self._prepared[self.progress.current.hunk].lines)

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
            if self.progress.current.hunk >= len(self._hunks):
                self._finish_commit(empty=False)
                continue
            prepared = self._prepared[self.progress.current.hunk]
            self._skip_non_targets()
            if prepared.is_skippable or self._hunk_done():
                self._complete_hunk()
                continue
            self.progress.current.file = prepared.hunk.path
            self._save()
            return

    def _complete_hunk(self) -> None:
        self.progress.current.hunk += 1
        self._apply_completed_prefix()
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
        while (
            not self.done
            and self.progress.current.sha is not None
            and self.progress.current.hunk < len(self._hunks)
        ):
            self._complete_hunk()
        if not self.done:
            self._advance_to_typable()

    def view(self) -> ViewState:
        shas = self.progress.first_parent_shas
        sha = self.progress.current.sha or (shas[-1] if shas else "")
        commit_index = len(self.progress.completed_shas) + (0 if self.done else 1)
        files = list(dict.fromkeys(h.path for h in self._hunks))
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
