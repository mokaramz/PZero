"""The source-network archive check (review 025, decision (f) revision 2): ONE statement of what the old intelligence
read from ``sources/network.json``, used by the importer (a problem is a plan blocker) and by the reader (a problem
drops only that record, and the answer's ``note`` says so).

What the old code touched:

* ``_collect`` (every intelligence request): ``source_network.load()["candidates"].values()`` and ``c["state"]`` for
  every candidate. ``load()`` was ``storage.load_json(STORE, {}, tolerant=True) or {}`` then
  ``setdefault("candidates", {})``: a missing or FALSY top level (no file, ``null``, ``[]``, ``{}``) read as no
  candidates and never failed, so it is not a problem here either; a truthy top level that is not an object, and a
  ``candidates`` value that is not an object (an explicit ``null`` included: ``setdefault`` keeps it), failed.
* ``detail`` (a city with a country), for a candidate in DISCOVERED / VALIDATING / PROBATION / DEGRADED:
  ``c["url"].split("/")[2]``, ``c.get("family") in want`` (a set: the family must be hashable), and for a listed one
  ``c["name"]``, ``c["state"]``, ``c.get("family")``, ``c["url"]``.

Rules (exactly plan revision 2): the top level is an object; ``candidates``, when present, is an object; every
candidate is an object with a ``state`` key; a candidate in one of the four states has a ``url`` that is a string with
at least two ``/``, a ``name`` key, and a ``family`` that is absent, ``null`` or a string. A REJECTED (or any other
state) candidate is never read beyond its ``state``, so its other fields are not checked. Pure.
"""

from __future__ import annotations

from typing import Any

READ_STATES = ("DISCOVERED", "VALIDATING", "PROBATION", "DEGRADED")


def _kind(v: Any) -> str:
    return "null" if v is None else type(v).__name__


def check_candidates(doc: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """``(usable, problems)``: the usable candidates in archive (key) order and one line per unusable record. An
    unusable top level or ``candidates`` value drops the whole layer (no usable candidates, one problem)."""
    if not doc:  # the old ``load_json(...) or {}``: nothing stored reads as no candidates
        return [], []
    if not isinstance(doc, dict):
        return [], [f"the source-network archive is {_kind(doc)}, not an object"]
    if "candidates" not in doc:
        return [], []
    cands = doc["candidates"]
    if not isinstance(cands, dict):
        return [], [f"the source-network candidates are {_kind(cands)}, not an object"]
    usable: list[dict[str, Any]] = []
    problems: list[str] = []
    for key, c in cands.items():
        if not isinstance(c, dict) or "state" not in c:
            problems.append(f"source-network candidate {key}: not an object with a state")
            continue
        if c["state"] in READ_STATES:
            url, family = c.get("url"), c.get("family")
            if not isinstance(url, str) or url.count("/") < 2:
                problems.append(f"source-network candidate {key}: the url is not a text with a host")
                continue
            if "name" not in c:
                problems.append(f"source-network candidate {key}: no name")
                continue
            if family is not None and not isinstance(family, str):
                problems.append(f"source-network candidate {key}: the family is {_kind(family)}, not a text")
                continue
        usable.append(c)
    return usable, problems


def skip_note(problems: list[str]) -> str:
    """The sentence the intelligence / detail ``note`` gains when records were left out: the old ``compat._skip``
    wording (``"%s: %d record(s) could not be interpreted — skipped safely (%s)"``) with ``where`` = "Source network"
    and ``why`` = the problems. Empty when there is nothing to say."""
    if not problems:
        return ""
    return (
        f" Source network: {len(problems)} record(s) could not be interpreted — skipped safely ({'; '.join(problems)})."
    )
