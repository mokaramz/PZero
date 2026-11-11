"""Literal search escaping (review 005 #2): the LIKE escape character itself is escaped first."""

from __future__ import annotations

import re

import pytest

from projectzero.dealflow.candidates import like_literal


def like_matches(pattern: str, text: str) -> bool:
    """Reference LIKE semantics with backslash as the escape character (Postgres default)."""
    regex, i = "", 0
    while i < len(pattern):
        char = pattern[i]
        if char == "\\" and i + 1 < len(pattern):
            regex += re.escape(pattern[i + 1])
            i += 2
            continue
        regex += ".*" if char == "%" else "." if char == "_" else re.escape(char)
        i += 1
    return re.fullmatch(regex, text, re.DOTALL) is not None


@pytest.mark.parametrize(
    ("needle", "haystack", "expected"),
    [
        ("\\_", "Path\\_Finder Labs", True),  # backslash followed by underscore, literally
        ("\\_", "Path_Finder Labs", False),  # no backslash: must not match
        ("Path\\", "Path\\_Finder Labs", True),  # trailing backslash must not swallow the wildcard
        ("Path\\", "PathXFinder", False),
        ("100%_", "100%_ Club", True),
        ("100%_", "1000 Club", False),
        ("a_b", "aXb", False),
        ("plain", "Plain plain", True),
    ],
)
def test_escaped_text_matches_only_itself(needle: str, haystack: str, expected: bool) -> None:
    assert like_matches(f"%{like_literal(needle)}%", haystack) is expected


def test_escaping_order() -> None:
    assert like_literal("\\_%") == "\\\\\\_\\%"
