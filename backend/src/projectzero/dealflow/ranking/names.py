"""Name helpers the protected rules depend on (old ``connectors.norm_company`` and ``radar.slug``), unchanged.

These are NOT the new identity normaliser (``dealflow.identity.normalize_name``): the ranking must keep reading
names exactly as the old app did.
"""

from __future__ import annotations

import re

_SUFFIX = {
    "gmbh", "ug", "ag", "se", "kg", "ohg", "ev", "inc", "llc", "corp", "co", "ltd", "plc", "limited", "oy", "oyj",
    "ab", "as", "aps", "bv", "nv", "sas", "sarl", "srl", "sl", "spa", "sa", "spzoo", "mbh", "gbr",
}  # fmt: skip
_JOIN_INITIALS = (
    (" b v ", " bv "),
    (" n v ", " nv "),
    (" a s ", " as "),
    (" s a ", " sa "),
    (" sp z o o ", " spzoo "),
    (" e v ", " ev "),
)


def norm_company(name: str | None) -> str:
    n = " " + re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip() + " "
    for a, b in _JOIN_INITIALS:
        n = n.replace(a, b)
    toks = n.split()
    while toks and toks[-1] in _SUFFIX:
        toks.pop()
    return " ".join(toks[:5])


def slug(s: str) -> str:
    s = re.sub(r"\((haftungsbeschränkt)\)|\b(gmbh|ug|ag|ltd|inc|se|i\.g\.)\b", "", s, flags=re.I)
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "company"
