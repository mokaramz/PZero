"""Identity primitives shared by intake resolution and the legacy import.

* ``normalize_name`` — the single name normaliser (the database stores its output; it has no SQL twin).
* ``company_domain`` — a company's own registrable domain from a website URL, or None for shared hosts
  (universities, link-in-bio pages, code hosting, social networks), which must never become a strong identifier.
* ``is_placeholder_name`` — names that mean "unknown" and must not create a company.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

# Legal-form tokens, stripped only from the END of a name ("Co Robotics" keeps "co"; "Acme GmbH & Co. KG" -> "acme").
_LEGAL_SUFFIXES = frozenset(
    {
        "gmbh", "ag", "ug", "kg", "kgaa", "se", "ev", "gbr", "ohg", "mbh",
        "ltd", "limited", "plc", "llp", "inc", "incorporated", "llc", "corp", "corporation", "co", "company",
        "sa", "sas", "sarl", "srl", "spa", "sl", "bv", "nv", "ab", "oy", "oyj", "as", "asa", "aps",
    }
)  # fmt: skip
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)
_PLACEHOLDER_NAMES = frozenset({"unknown", "n a", "na", "none", "null", "tbd", "untitled", "unnamed", "stealth"})


def normalize_name(raw: str | None) -> str | None:
    """Lower-case (Unicode casefold), punctuation to spaces, trailing legal forms removed. None when nothing is left."""
    if not raw:
        return None
    tokens = _NON_WORD.sub(" ", unicodedata.normalize("NFKC", raw).casefold()).split()
    if len(tokens) > 2 and tokens[-2:] == ["a", "s"]:  # Danish/Norwegian "A/S"
        tokens[-2:] = ["as"]
    while len(tokens) > 1 and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens) or None


def is_placeholder_name(raw: str | None) -> bool:
    normalized = normalize_name(raw)
    return normalized is None or normalized in _PLACEHOLDER_NAMES


# Hosts many unrelated companies share. A match on any of these suffixes is never a company's own domain.
_SHARED_HOST_SUFFIXES = (
    "github.io", "github.com", "gitlab.com", "linktr.ee", "linkedin.com", "medium.com", "substack.com",
    "notion.site", "notion.so", "wixsite.com", "webflow.io", "vercel.app", "netlify.app", "carrd.co",
    "sites.google.com", "google.com", "x.com", "twitter.com", "facebook.com", "instagram.com", "youtube.com",
    "crunchbase.com", "dealroom.co", "angel.co", "wellfound.com", "producthunt.com", "ycombinator.com",
    "eu-startups.com", "sifted.eu", "techcrunch.com",
    "ethz.ch", "epfl.ch", "tum.de", "kit.edu", "mit.edu", "cam.ac.uk", "ox.ac.uk",
)  # fmt: skip
_ACADEMIC = re.compile(r"(\.edu|\.ac\.[a-z]{2}|\.edu\.[a-z]{2}|\.uni-[a-z-]+\.de|^uni-[a-z-]+\.de)$")
_TWO_LEVEL_SUFFIXES = frozenset({"co.uk", "org.uk", "ac.uk", "com.au", "co.jp", "co.il", "com.br", "co.nz", "co.za"})


def company_domain(website: str | None) -> str | None:
    """Registrable domain of a company's own website, e.g. 'https://www.app.aereus.de/x' -> 'aereus.de'."""
    if not website or not isinstance(website, str):
        return None
    text = website.strip()
    if "://" not in text:
        text = f"https://{text}"
    try:
        host = (urlsplit(text).hostname or "").lower().rstrip(".")
    except ValueError:
        return None
    if not host or "." not in host or not re.fullmatch(r"[a-z0-9.-]+", host):
        return None
    labels = host.split(".")
    keep = 3 if ".".join(labels[-2:]) in _TWO_LEVEL_SUFFIXES else 2
    domain = ".".join(labels[-keep:])
    if any(host == s or host.endswith(f".{s}") for s in _SHARED_HOST_SUFFIXES) or _ACADEMIC.search(host):
        return None
    return domain
