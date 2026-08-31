from rich.text import Text

from codeape.session import ViewLine
from codeape.tui import palette as pal
from codeape.tui.highlight import (
    apply_highlight,
    identifier_at,
    identifier_at_cell,
    match_count,
)


def _add(text: str, *, gutter: str = "+") -> ViewLine:
    return ViewLine(
        kind="ADD",
        gutter=gutter,
        display=text,
        typing=text,
        comment_suffix="",
        col=0,
        remaining=0,
        skip=False,
        is_current=False,
        miss=False,
    )


def test_identifier_at_reads_word_under_column():
    assert identifier_at("foo = bar", 0) == "foo"
    assert identifier_at("foo = bar", 2) == "foo"
    assert identifier_at("foo = bar", 6) == "bar"
    assert identifier_at("foo = bar", 3) == ""
    assert identifier_at("foo = bar", 4) == ""


def test_identifier_at_rejects_leading_digits():
    assert identifier_at("123 foo", 0) == ""
    assert identifier_at("_count", 0) == "_count"


def test_match_count_uses_word_boundaries():
    source = "foo foobar foo foo_bar foo"
    assert match_count(source, "foo") == 3
    assert match_count(source, "") == 0
    assert match_count(source, "missing") == 0


def test_identifier_at_cell_skips_gutter():
    lines = [_add("count = 1")]
    assert identifier_at_cell(lines, 80, 0, 0) == ""
    assert identifier_at_cell(lines, 80, 1, 0) == ""
    assert identifier_at_cell(lines, 80, 2, 0) == "count"
    assert identifier_at_cell(lines, 80, 6, 0) == "count"
    assert identifier_at_cell(lines, 80, 10, 0) == ""


def test_identifier_at_cell_finds_second_line():
    lines = [_add("alpha"), _add("beta")]
    assert identifier_at_cell(lines, 80, 2, 1) == "beta"


def test_apply_highlight_marks_exact_words():
    text = Text("+ foo foobar foo\n")
    apply_highlight(text, "foo")
    spans = [(start, end) for start, end, style in text.spans if pal.HIGHLIGHT in str(style)]
    plains = [text.plain[start:end] for start, end in spans]
    assert plains == ["foo", "foo"]
