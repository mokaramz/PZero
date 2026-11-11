"""Person identity rules shared by the importer and the coming Network port (review 012).

* ``fold`` — the old person-identity key (``services/identity.fold`` at the old revision, ported verbatim and
  golden-tested against it): ß -> ss, ASCII fold, lower case, leading academic titles (Dr, Prof, Dipl, Ing, Mag, MBA,
  PhD, "Dr.-Ing.") stripped, everything but letters and spaces dropped. ``people.normalized_name`` is this key.
* ``classify_profile_url`` — one ``profile_urls`` entry as a person identifier. Only a URL that names ONE person is a
  strong ``profile_url``: a LinkedIn ``/in/<slug>`` (the old ``extraction._LI_PROFILE`` / ``canonical_linkedin``), a
  GitHub or X account the person's own record establishes as theirs (``own_accounts``: the GitHub collector's source
  account, the person's ``x`` field), an ORCID iD, an OpenAlex author (the old collector's ``author.id``), a Google
  Scholar ``citations?user=`` page on a known Scholar host. Anything else -- the GitHub
  profile's ``blog`` field (a personal or company site), a YouTube channel, a project page -- is a weak ``url``: a
  company site can be listed by several people, so it must never be unique to one of them.
* ``canonical_orcid`` / ``canonical_openalex`` — the one spelling of those ids, bare or as a URL.

URL variants are folded before identifiers are compared: scheme and host case, ``www.``, ``http`` vs ``https``, a
trailing ``/``, the fragment; the profile hosts also fold the case of the handle (LinkedIn, GitHub and X handles are
case-insensitive; the old ``canonical_linkedin`` lower-cases the whole URL).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Literal
from urllib.parse import parse_qs, urlsplit, urlunsplit

PersonUrlKind = Literal["profile_url", "url"]

_ORCID = re.compile(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dXx])")
_OPENALEX = re.compile(r"[Aa](\d+)")
_GITHUB_LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")
_X_HANDLE = re.compile(r"[A-Za-z0-9_]{1,15}")
# first path segments that are GitHub / X site pages, not a user
_GITHUB_RESERVED = frozenset(
    {
        "about", "apps", "collections", "customer-stories", "enterprise", "events", "explore", "features", "issues",
        "join", "login", "marketplace", "new", "notifications", "orgs", "pricing", "pulls", "readme", "search",
        "security", "settings", "site", "sponsors", "topics", "trending",
    }
)  # fmt: skip
_X_RESERVED = frozenset(
    {"explore", "hashtag", "home", "i", "intent", "login", "messages", "notifications", "privacy", "search",
     "settings", "share", "signup", "tos"}
)  # fmt: skip


def fold(s: Any) -> str:
    """The old ``services/identity.fold``, verbatim."""
    s = str(s or "").replace("ß", "ss").replace("ẞ", "SS")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"^((dr|prof|dipl|ing|mag|mba|phd)\.?(-ing\.?)?\s+)+", "", s.strip())
    return " ".join(re.sub(r"[^a-z ]+", " ", s).split())


def _split(value: str) -> tuple[str, str, list[str], str] | None:
    """(scheme, host without www., path segments, query) of a URL, or None if it has no host."""
    text = value if "://" in value else "https://" + value
    try:
        parts = urlsplit(text)
        host = (parts.hostname or "").removeprefix("www.")
        port = parts.port
    except ValueError:
        return None
    if not host or " " in host:
        return None
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    return parts.scheme.lower(), netloc, [s for s in parts.path.split("/") if s], parts.query


def canonical_orcid(value: str) -> str:
    """``https://orcid.org/<iD>`` for an ORCID iD given bare or as a URL; any other value stripped."""
    v = value.strip()
    m = _ORCID.fullmatch(v)
    if m is None:
        split = _split(v)
        if split and split[1] == "orcid.org" and len(split[2]) == 1:
            m = _ORCID.fullmatch(split[2][0])
    return f"https://orcid.org/{m.group(1).upper()}" if m else v


def canonical_openalex(value: str) -> str:
    """``https://openalex.org/A<n>`` for an OpenAlex author given bare or as a URL; any other value stripped."""
    v = value.strip()
    m = _OPENALEX.fullmatch(v)
    if m is None:
        split = _split(v)
        if split and split[1] in ("openalex.org", "api.openalex.org"):
            segs = split[2][1:] if split[2][:1] == ["authors"] else split[2]
            m = _OPENALEX.fullmatch(segs[0]) if len(segs) == 1 else None
    return f"https://openalex.org/A{m.group(1)}" if m else v


# Google Scholar hosts matched EXACTLY (review 012, Codex H-078): an unknown "scholar.google.<x>" host stays weak.
SCHOLAR_HOSTS = frozenset(
    {
        "scholar.google.com", "scholar.google.de", "scholar.google.co.uk", "scholar.google.fr", "scholar.google.ch",
        "scholar.google.at", "scholar.google.nl", "scholar.google.be", "scholar.google.it", "scholar.google.es",
        "scholar.google.pt", "scholar.google.ie", "scholar.google.se", "scholar.google.dk", "scholar.google.no",
        "scholar.google.fi", "scholar.google.pl", "scholar.google.cz", "scholar.google.ca", "scholar.google.com.au",
    }
)  # fmt: skip

OwnAccounts = frozenset[tuple[str, str]]  # {("github", login), ("x", handle)} established by the person's own record


def _profile(netloc: str, segs: list[str], query: str, own: OwnAccounts) -> str | None:
    """The canonical person-profile URL, or None when the URL does not name one person.

    A GitHub or X account can belong to an organisation as well as a person, and the URL alone cannot tell. It is a
    profile only when the person's own imported record establishes that account as theirs (``own``); otherwise the
    caller keeps it as a weak link, so two people listing one organisation never collide."""
    if netloc == "linkedin.com" or netloc.endswith(".linkedin.com"):
        if len(segs) >= 2 and segs[0].lower() == "in":
            return f"https://www.linkedin.com/in/{segs[1].lower()}"
        return None
    if netloc == "github.com":
        if len(segs) == 1 and _GITHUB_LOGIN.fullmatch(segs[0]) and segs[0].lower() not in _GITHUB_RESERVED:
            login = segs[0].lower()
            return f"https://github.com/{login}" if ("github", login) in own else None
        return None
    if netloc == "orcid.org":
        return f"https://orcid.org/{segs[0].upper()}" if len(segs) == 1 and _ORCID.fullmatch(segs[0]) else None
    if netloc in ("openalex.org", "api.openalex.org"):
        author = segs[1:] if segs[:1] == ["authors"] else segs
        m = _OPENALEX.fullmatch(author[0]) if len(author) == 1 else None
        return f"https://openalex.org/A{m.group(1)}" if m else None
    if netloc in SCHOLAR_HOSTS:
        users = parse_qs(query).get("user") if segs == ["citations"] else None
        return f"https://scholar.google.com/citations?user={users[0]}" if users and users[0].strip() else None
    if netloc in ("x.com", "twitter.com", "mobile.twitter.com", "mobile.x.com"):
        ok = len(segs) == 1 and _X_HANDLE.fullmatch(segs[0]) and segs[0].lower() not in _X_RESERVED
        return f"https://x.com/{segs[0].lower()}" if ok and ("x", segs[0].lower()) in own else None
    return None


def canonical_github_id(value: Any) -> str | None:
    """A GitHub account's numeric id as its one stored spelling (decimal, no leading zeros), or None.

    The ONE validator for both uses (review 012, Codex H-082): the strong ``github`` identifier and the ownership
    evidence in ``own_accounts``. Integer 42 and string "42" are the same id; "not-a-number", "", 0 and bools are none.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value) if value > 0 else None
    if isinstance(value, str) and value.strip().isdecimal() and value.strip().isascii():
        n = int(value.strip())
        return str(n) if n > 0 else None
    return None


def _aliases(value: Any) -> list[str]:
    """Aliases as whole strings: one string is ONE alias, a list keeps only its strings; anything else is none."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def _x_handle(value: str) -> str | None:
    """The X handle a person's ``x`` field names: a bare handle (``@`` optional), or an X / Twitter profile URL on a
    supported host with a single, non-reserved path segment. Any other URL names no handle."""
    v = value.strip()
    if "/" not in v and "." not in v:
        handle = v.lstrip("@")
        return handle.lower() if _X_HANDLE.fullmatch(handle) and handle.lower() not in _X_RESERVED else None
    split = _split(v if "://" in v else f"https://{v}")
    if split is None:
        return None
    _scheme, netloc, segs, _query = split
    if netloc not in ("x.com", "twitter.com", "mobile.twitter.com", "mobile.x.com") or len(segs) != 1:
        return None
    handle = segs[0].lstrip("@")
    return handle.lower() if _X_HANDLE.fullmatch(handle) and handle.lower() not in _X_RESERVED else None


def own_accounts(record: dict[str, Any]) -> OwnAccounts:
    """The GitHub / X accounts a legacy person record establishes as its own (review 012, Codex H-078 / H-080).

    * GitHub: the old collector created the record FROM an account, so it carries the account's NUMERIC id
      (``github_id``) and that login in ``aliases`` (whole strings only). A non-numeric id (``"unknown"``) proves
      nothing.
    * X: the person's ``x`` field, as a bare handle or an X / Twitter profile URL (``_x_handle``).
    Malformed values establish nothing; they never raise.
    """
    out: set[tuple[str, str]] = set()
    if canonical_github_id(record.get("github_id")) is not None:
        for alias in _aliases(record.get("aliases")):
            login = alias.strip()
            if _GITHUB_LOGIN.fullmatch(login) and login.lower() not in _GITHUB_RESERVED:
                out.add(("github", login.lower()))
    x = record.get("x")
    if isinstance(x, str) and (handle := _x_handle(x)):
        out.add(("x", handle))
    return frozenset(out)


def classify_profile_url(value: str, own: OwnAccounts = frozenset()) -> tuple[PersonUrlKind, str] | None:
    """(kind, canonical value) of one legacy ``profile_urls`` entry; None for an empty value. See the module doc."""
    v = value.strip()
    if not v:
        return None
    if _ORCID.fullmatch(v):  # a bare ORCID iD
        return "profile_url", canonical_orcid(v)
    split = _split(v)
    if split is None:
        return "url", v
    scheme, netloc, segs, query = split
    profile = _profile(netloc, segs, query, own)
    if profile is not None:
        return "profile_url", profile
    scheme = "https" if scheme in ("http", "https") else scheme
    path = "/" + "/".join(segs) if segs else ""
    return "url", urlunsplit((scheme, netloc, path, query, ""))
