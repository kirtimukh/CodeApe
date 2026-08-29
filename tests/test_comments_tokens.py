from codeape.comments import split_code_and_comment
from codeape.tokens import leading_indent, tab_target


def test_trailing_comment_is_stripped():
    code, suffix, only = split_code_and_comment("    total = 1  # sum", "x.py")
    assert only is False
    assert code == "    total = 1"
    assert suffix.startswith("  #")


def test_full_line_comment_is_comment_only():
    code, suffix, only = split_code_and_comment("    # note", "x.py")
    assert only is True
    assert code.strip() == ""
    assert "#" in suffix


def test_no_comment_unchanged():
    line = "    return 2"
    code, suffix, only = split_code_and_comment(line, "x.py")
    assert only is False
    assert code == line
    assert suffix == ""


def test_leading_indent():
    assert leading_indent("    total = 1") == 4
    assert leading_indent("\treturn 1") == 1
    assert leading_indent("def hello():") == 0


def test_tab_leading_indent():
    line = "    total = math.fsum(values)"
    assert tab_target(line, 0) == 4
    assert tab_target(line, 2) == 4


def test_tab_word_and_symbol():
    line = "    total = math.fsum(values)"
    assert tab_target(line, 4) == 9  # total
    assert tab_target(line, 10) == 11  # =
    assert tab_target(line, 12) == 16  # math
    assert tab_target(line, 16) == 17  # .
    assert tab_target(line, 5) == 9  # mid-word
    assert tab_target(line, 8) == 9  # last char of word
    assert tab_target(line, 13) == 16  # mid-identifier
    assert tab_target(line, 9) is None  # between tokens


def test_tab_number():
    assert tab_target("return 2.0", 7) == 10
