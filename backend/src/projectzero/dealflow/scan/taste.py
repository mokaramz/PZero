# ruff: noqa
# mypy: ignore-errors
# (protected scanning rules, copied by script from the old modules; see the header. The cut code is the old untyped
# code verbatim, so it is exempt from lint and type checks, like a vendored module.)
"""Two Taste Map helpers the old scan read (review 034a), cut MECHANICALLY from the old ``domain/taste.py`` at
revision 6c739b9 (``scripts/gen_scan_catalog.py``), over the tables ``conviction/taste.py`` holds verbatim (the
script checks them node for node).
"""

# fmt: off
from projectzero.conviction.taste import ARCHETYPES, PORTFOLIO

__all__ = ["ARCHETYPES", "PORTFOLIO", "suggest_twins", "tag_archetypes"]

def suggest_twins(text: str) -> list[tuple[str, str, int]]:
    """Keyword match candidate text against portfolio → list of (name, what, hits). Discovery aid only."""
    t = " " + text.lower() + " "
    out = []
    for name, what, kws in PORTFOLIO:
        hits = [k for k in kws if k in t]
        if hits:
            out.append((name, what, len(hits)))
    return sorted(out, key=lambda x: -x[2])[:3]

def tag_archetypes(text: str) -> list[tuple[int, str, int]]:
    t = " " + text.lower() + " "
    scored = []
    for aid, name, _test, kws in ARCHETYPES:
        n = sum(1 for k in kws if k in t)
        if n:
            scored.append((n, aid, name))
    return [(aid, name, n) for n, aid, name in sorted(scored, reverse=True)[:3]]
# fmt: on
