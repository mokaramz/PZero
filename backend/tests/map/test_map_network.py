"""Review 025 decision (f), revision 2: ONE check of the source-network archive (``map.network.check_candidates``),
and an already-imported malformed archive drops only the malformed records, named in the ``note``; every other layer
is unaffected and every Map answer still answers (the old code answered 500)."""

from __future__ import annotations

import dataclasses
from datetime import date
from typing import Any

import pytest

from projectzero.map import intel
from projectzero.map.network import check_candidates, skip_note
from projectzero.ops.parity_map import INJECT, inputs_of, munich_docs, net

TODAY = date(2026, 11, 12)
GOOD = net("n-good", "Invented good list", "https://good.invented.de/", "DISCOVERED")


@pytest.mark.parametrize(
    "doc",
    [None, {}, [], "", 0, {"version": 1}, {"candidates": {}}],
)
def test_nothing_stored_reads_as_no_candidates_without_a_problem(doc: Any) -> None:
    assert check_candidates(doc) == ([], [])


@pytest.mark.parametrize(
    ("doc", "problem"),
    [
        ([1], "the source-network archive is list, not an object"),
        ("text", "the source-network archive is str, not an object"),
        ({"candidates": None}, "the source-network candidates are null, not an object"),  # explicit null is not absent
        ({"candidates": [GOOD]}, "the source-network candidates are list, not an object"),
    ],
)
def test_an_unusable_archive_drops_the_whole_layer(doc: Any, problem: str) -> None:
    assert check_candidates(doc) == ([], [problem])


def test_each_candidate_rule() -> None:
    bad_url = net("n-host", "Invented no host", "example.org", "DISCOVERED")
    no_name = {k: v for k, v in net("n-noname", "x", "https://a.invented.de/", "VALIDATING").items() if k != "name"}
    list_family = net("n-fam", "Invented list family", "https://b.invented.de/", "PROBATION", family=["founder_move"])
    int_family = net("n-int", "Invented int family", "https://c.invented.de/", "DEGRADED", family=3)
    no_state = {k: v for k, v in GOOD.items() if k != "state"}
    url_not_text = net("n-url", "Invented url", "https://d.invented.de/", "DISCOVERED") | {"url": None}
    rejected_bad = net("n-rej", "Invented rejected", "example.org", "REJECTED", family=["x"])  # never read past state
    null_family = net("n-null", "Invented null family", "https://e.invented.de/", "DISCOVERED", family=None)
    minimal = {"state": "ACTIVE"}
    doc = {"candidates": {"n-good": GOOD, "n-host": bad_url, "n-noname": no_name, "n-fam": list_family,
                          "n-int": int_family, "n-nostate": no_state, "n-url": url_not_text, "n-text": "a string",
                          "n-rej": rejected_bad, "n-null": null_family, "n-min": minimal}}  # fmt: skip
    usable, problems = check_candidates(doc)
    assert [c.get("id") for c in usable] == ["n-good", "n-rej", "n-null", None]  # archive order
    assert problems == [
        "source-network candidate n-host: the url is not a text with a host",
        "source-network candidate n-noname: no name",
        "source-network candidate n-fam: the family is list, not a text",
        "source-network candidate n-int: the family is int, not a text",
        "source-network candidate n-nostate: not an object with a state",
        "source-network candidate n-url: the url is not a text with a host",
        "source-network candidate n-text: not an object with a state",
    ]
    assert check_candidates({"candidates": {"x": net("x", "y", "https://", "DISCOVERED")}}) == (
        [net("x", "y", "https://", "DISCOVERED")],
        [],
    )  # two slashes: ``split("/")[2]`` exists


def test_skip_note_uses_the_old_compat_wording() -> None:
    assert skip_note([]) == ""
    assert skip_note(["a", "b"]) == " Source network: 2 record(s) could not be interpreted — skipped safely (a; b)."


def _with_network(doc: Any) -> Any:
    docs = munich_docs()
    docs["sources/network.json"] = doc
    return inputs_of(docs, INJECT, TODAY)


def test_an_imported_malformed_archive_leaves_every_other_layer_and_answer_intact() -> None:
    valid = _with_network(munich_docs()["sources/network.json"])
    cands = dict(munich_docs()["sources/network.json"]["candidates"])
    broken = {"n-host": net("n-host", "Invented no host", "example.org", "DISCOVERED"), **cands,
              "n-fam": net("n-fam", "Invented list family", "https://b.invented.de/", "PROBATION", family=["x"])}  # fmt: skip
    malformed = _with_network({"candidates": broken})
    assert malformed.network == valid.network and len(malformed.network_problems) == 2
    d_ok, d_bad = intel.detail(valid, "Munich", TODAY), intel.detail(malformed, "Munich", TODAY)
    assert d_bad["source_candidates"] == d_ok["source_candidates"]  # the usable ones, in order
    assert d_bad["note"] == d_ok["note"] + skip_note(malformed.network_problems)
    assert "n-host" in d_bad["note"] and "n-fam" in d_bad["note"]
    for k in ("companies", "people", "events", "news", "institutions", "why_here", "coverage", "state"):
        assert d_bad[k] == d_ok[k], k
    v_ok, v_bad = intel.view(valid, TODAY), intel.view(malformed, TODAY)
    assert v_bad["note"].startswith(v_ok["note"]) and v_bad["note"] != v_ok["note"]
    assert {k: v for k, v in v_bad.items() if k != "note"} == {k: v for k, v in v_ok.items() if k != "note"}
    assert intel.search(malformed, "invented", TODAY) == intel.search(valid, "invented", TODAY)
    plan = intel.sourcing_day(malformed, "Munich", "2026-11-19", TODAY)
    assert plan == intel.sourcing_day(valid, "Munich", "2026-11-19", TODAY)  # the plan note is unchanged


def test_a_null_candidates_archive_empties_only_the_source_candidates() -> None:
    valid = _with_network(munich_docs()["sources/network.json"])
    nulled = _with_network({"candidates": None})
    assert nulled.network == [] and nulled.network_problems == ["the source-network candidates are null, not an object"]
    d = intel.detail(nulled, "Munich", TODAY)
    assert d["source_candidates"] == [] and d["companies"] == intel.detail(valid, "Munich", TODAY)["companies"]
    assert dataclasses.replace(nulled, network_problems=[]) != nulled
