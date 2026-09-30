"""Typing canvas colors. Terminals fake translucency with dim truecolor."""

from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass

_THEMES = ("dark", "light")
_OSC11_RGB = re.compile(
    r"\x1b\]11;rgb:([0-9a-fA-F]+)/([0-9a-fA-F]+)/([0-9a-fA-F]+)"
)


@dataclass(frozen=True)
class Palette:
    DEL: str
    DEL_EATEN: str
    ADD_UNTYPED: str
    ADD_TYPED: str
    CURSOR: str
    MISS: str
    CTX: str
    COMMENT: str
    GUTTER_ADD: str
    GUTTER_DEL: str
    GUTTER_CTX: str
    STATUS: str
    STATUS_DIM: str
    BACKGROUND: str
    HIGHLIGHT: str


DARK = Palette(
    DEL="dim #c45c5c",
    DEL_EATEN="dim #5a3030",
    ADD_UNTYPED="dim #9399b2",
    ADD_TYPED="#cdd6f4",
    CURSOR="bold #1e1e2e on #cdd6f4",
    MISS="bold #cdd6f4 on #7f1d1d",
    CTX="dim #6c7086",
    COMMENT="dim #6c7086",
    GUTTER_ADD="dim #6c7086",
    GUTTER_DEL="dim #c45c5c",
    GUTTER_CTX="dim #6c7086",
    STATUS="#cdd6f4",
    STATUS_DIM="dim #9399b2",
    BACKGROUND="#1e1e2e",
    HIGHLIGHT="on #45475a",
)

LIGHT = Palette(
    DEL="dim #d20f39",
    DEL_EATEN="dim #c9a0a6",
    ADD_UNTYPED="dim #7c7f93",
    ADD_TYPED="#4c4f69",
    CURSOR="bold #eff1f5 on #4c4f69",
    MISS="bold #eff1f5 on #d20f39",
    CTX="dim #9ca0b0",
    COMMENT="dim #9ca0b0",
    GUTTER_ADD="dim #9ca0b0",
    GUTTER_DEL="dim #d20f39",
    GUTTER_CTX="dim #9ca0b0",
    STATUS="#4c4f69",
    STATUS_DIM="dim #7c7f93",
    BACKGROUND="#eff1f5",
    HIGHLIGHT="on #bcc0cc",
)

_PALETTES = {"dark": DARK, "light": LIGHT}
_active_name = "dark"


def active() -> Palette:
    return _PALETTES[_active_name]


def active_name() -> str:
    return _active_name


def use(name: str) -> str:
    global _active_name
    if name not in _PALETTES:
        raise ValueError(f"unknown theme {name!r}")
    _active_name = name
    return name


def resolve(preference: str | None = None) -> str:
    """Resolve ``dark``, ``light``, or ``auto`` to a concrete theme.

    ``None`` reads ``CODEAPE_THEME`` (default ``auto``). Unknown values
    fall back to auto. Auto uses ``COLORFGBG`` or OSC 11, else dark.
    """
    if preference is None:
        preference = os.environ.get("CODEAPE_THEME", "auto")
    pref = preference.strip().lower()
    if pref not in (*_THEMES, "auto"):
        pref = "auto"
    if pref in _THEMES:
        return pref
    return detect() or "dark"


def detect() -> str | None:
    found = _from_colorfgbg(os.environ.get("COLORFGBG", ""))
    if found:
        return found
    return _from_osc11()


def apply_colors(widget, *, border: bool = False) -> None:
    pal = active()
    widget.styles.background = pal.BACKGROUND
    widget.styles.color = pal.ADD_TYPED
    if border:
        widget.styles.border = ("solid", pal.STATUS)


def apply_app(app) -> None:
    light = _active_name == "light"
    try:
        app.theme = "textual-light" if light else "textual-dark"
    except (AttributeError, KeyError, ValueError):
        if hasattr(app, "dark"):
            app.dark = not light
    apply_colors(app.screen)


def _from_colorfgbg(value: str) -> str | None:
    parts = [part.strip() for part in value.split(";") if part.strip()]
    bg = next((int(part) for part in reversed(parts) if part.isdigit()), None)
    if bg is None:
        return None
    return "light" if bg in {7, 15} else "dark"


def _from_osc11(timeout: float = 0.05) -> str | None:
    raw = _query_osc11(timeout)
    return _parse_osc11(raw) if raw else None


def _parse_osc11(raw: str) -> str | None:
    match = _OSC11_RGB.search(raw)
    if not match:
        return None
    red, green, blue = (_osc_channel(part) for part in match.groups())
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return "light" if luminance >= 0.5 else "dark"


def _osc_channel(part: str) -> float:
    return int(part, 16) / ((16 ** len(part)) - 1)


def _query_osc11(timeout: float) -> str | None:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return None
    try:
        import select
        import termios
        import tty
    except ImportError:
        return None
    fd = sys.stdin.fileno()
    try:
        saved = termios.tcgetattr(fd)
    except termios.error:
        return None
    buf = ""
    try:
        tty.setcbreak(fd)
        sys.stdout.write("\033]11;?\033\\")
        sys.stdout.flush()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ready, _, _ = select.select([fd], [], [], deadline - time.monotonic())
            if not ready:
                break
            chunk = os.read(fd, 64)
            if not chunk:
                break
            buf += chunk.decode("latin-1")
            if "\033\\" in buf or buf.endswith("\x07"):
                break
        while select.select([fd], [], [], 0)[0]:
            os.read(fd, 4096)
    except (OSError, termios.error):
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    return buf or None


def __getattr__(name: str):
    try:
        return getattr(active(), name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
