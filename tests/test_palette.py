from __future__ import annotations

import asyncio

import pytest
from textual.color import Color

from codeape.tui import palette as pal
from codeape.tui.app import CodeApeApp

from test_app import _FakeSession


def test_dark_palette_keeps_mocha_hex():
    pal.use("dark")
    assert pal.BACKGROUND == "#1e1e2e"
    assert pal.ADD_TYPED == "#cdd6f4"
    assert pal.HIGHLIGHT == "on #45475a"
    assert pal.CURSOR == "bold #1e1e2e on #cdd6f4"


def test_light_palette_uses_latte_hex():
    pal.use("light")
    assert pal.active_name() == "light"
    assert pal.BACKGROUND == "#eff1f5"
    assert pal.ADD_TYPED == "#4c4f69"
    assert pal.HIGHLIGHT == "on #bcc0cc"
    assert pal.CURSOR == "bold #eff1f5 on #4c4f69"
    assert pal.MISS == "bold #eff1f5 on #d20f39"


def test_use_rejects_unknown_theme():
    with pytest.raises(ValueError, match="sepia"):
        pal.use("sepia")
    assert pal.active_name() == "dark"


def test_resolve_honors_explicit_theme():
    assert pal.resolve("light") == "light"
    assert pal.resolve("DARK") == "dark"


def test_resolve_auto_uses_colorfgbg(monkeypatch):
    monkeypatch.setenv("COLORFGBG", "0;15")
    monkeypatch.setattr(pal, "_from_osc11", lambda: None)
    assert pal.resolve("auto") == "light"
    monkeypatch.setenv("COLORFGBG", "15;0")
    assert pal.resolve("auto") == "dark"


def test_resolve_auto_defaults_dark(monkeypatch):
    monkeypatch.delenv("COLORFGBG", raising=False)
    monkeypatch.delenv("CODEAPE_THEME", raising=False)
    monkeypatch.setattr(pal, "_from_osc11", lambda: None)
    assert pal.resolve("auto") == "dark"
    assert pal.resolve(None) == "dark"
    assert pal.resolve("nope") == "dark"


def test_resolve_reads_codeape_theme(monkeypatch):
    monkeypatch.setenv("CODEAPE_THEME", "light")
    monkeypatch.setattr(pal, "_from_osc11", lambda: None)
    assert pal.resolve(None) == "light"


def test_colorfgbg_ignores_non_numeric():
    assert pal._from_colorfgbg("") is None
    assert pal._from_colorfgbg("default;default") is None
    assert pal._from_colorfgbg("15;0") == "dark"
    assert pal._from_colorfgbg("0;7") == "light"


def test_osc11_luminance():
    dark = pal._parse_osc11("\x1b]11;rgb:1e1e/1e1e/2e2e\x1b\\")
    light = pal._parse_osc11("\x1b]11;rgb:efff/f1f1/f5f5\x1b\\")
    assert dark == "dark"
    assert light == "light"
    assert pal._parse_osc11("nope") is None


def test_cmd_start_applies_theme(monkeypatch):
    from codeape.cli import cmd_start
    from codeape.paths import Registry, RepoEntry

    monkeypatch.setattr(
        "codeape.cli.load_registry",
        lambda: Registry(
            next_id=2,
            repos=[RepoEntry(id=1, name="demo", origin="/tmp/demo")],
        ),
    )
    monkeypatch.setattr("codeape.cli.load_repo_paths", lambda repo_id: object())
    monkeypatch.setattr("codeape.cli._run_session", lambda paths: None)
    cmd_start(repo_id=1, theme="light")
    assert pal.active_name() == "light"


def test_app_paints_light_screen():
    pal.use("light")
    session = _FakeSession(["a.py"])

    async def _run() -> None:
        app = CodeApeApp(session)
        async with app.run_test(size=(60, 20)):
            assert app.screen.styles.background == Color.parse("#eff1f5")
            assert app.screen.styles.color == Color.parse("#4c4f69")

    asyncio.run(_run())
