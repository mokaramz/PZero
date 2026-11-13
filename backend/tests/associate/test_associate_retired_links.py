"""Decision (c), after the build: the old ``open`` allowlist holds ``/`` and so lets any internal link through; an
open action to a retired view (Scout Intake, the Scout Bridge, the native scout) is removed like any unsupported
action, and the reply notes it."""

from __future__ import annotations

from projectzero.associate import engine


def test_an_open_action_to_a_retired_view_is_removed_and_noted() -> None:
    actions = [
        {"kind": "open", "label": "Open the item", "link": "/scout-intake?item=si-1"},
        {"kind": "open", "label": "Bridge", "link": "/scout-bridge"},
        {"kind": "open", "label": "Open Deal Flow", "link": "/deal-flow?candidate=c-1"},
        {"kind": "save_draft", "label": "Save as draft", "title": "t"},
    ]
    keep, dropped = engine._drop_retired(actions, [])
    assert keep == [actions[2], actions[3]]
    assert dropped == ["Open the item", "Bridge"]


def test_the_old_allowlist_still_passes_every_other_internal_link() -> None:
    out, dropped = engine._clean_actions([{"kind": "open", "label": "x", "link": "/scout-intake?item=1"}], {})
    assert out and not dropped  # the verbatim old filter alone would keep it: the retired filter is what removes it
