"""Review 025 decision (i): the Map's Deal Flow layer is the old inbox plus what intake added since; candidates
imported only from the retired Scout views stay out (Scout 00 items are the archived Scout layer)."""

from __future__ import annotations

import pytest

from projectzero.map.inputs import _old_inbox


@pytest.mark.parametrize(
    ("origins", "kept"),
    [
        (["legacy_dealflow"], True),
        (["legacy_dealflow", "legacy_scout00"], True),  # an inbox lead merged with a Scout 00 find
        (["manual"], True),  # live intake after the import
        (["event_debrief"], True),
        ([], True),
        (None, True),
        (["legacy_scout00"], False),
        (["legacy_native"], False),
        (["legacy_native", "legacy_scout00"], False),
    ],
)
def test_only_candidates_from_the_retired_scout_views_are_left_out(origins: list[str] | None, kept: bool) -> None:
    assert _old_inbox({"origins": origins}) is kept
