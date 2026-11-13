# ruff: noqa
# mypy: ignore-errors
# (protected scanning rules, copied by script from the old modules; see the header. The cut code is the old untyped
# code verbatim, so it is exempt from lint and type checks, like a vendored module.)
"""The Deal Flow V2 official-source parsers (review 034a), cut MECHANICALLY from the old ``domain/sources_v2.py``
at revision 6c739b9 (``scripts/gen_scan_catalog.py``): the whole module but its registry data, which lives in
``dealflow/sources/catalog.py`` (review 021). The only change: the lazy ``connectors`` import names
``dealflow/scan/parsers``.
"""

# fmt: off
import html as _html
import re
from urllib.parse import urljoin

_TAG = re.compile(r"<[^>]+>")

_HEAD = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.I | re.S)

_A = re.compile(r"<a[^>]+href=[\"']([^\"'#][^\"']*)[\"'][^>]*>(.*?)</a>", re.I | re.S)

_SCRIPT = re.compile(r"<(script|style|noscript|nav|footer|header)[^>]*>.*?</\1>", re.I | re.S)

_TABLE = re.compile(r"<table[^>]*>(.*?)</table>", re.I | re.S)

_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I | re.S)

_TD = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.I | re.S)

_LI = re.compile(r"<li[^>]*>(.*?)</li>", re.I | re.S)

CATEGORY_WORDS = re.compile(
    r"^(biotech|cleantech|engineering|ict|medtech|fintech|deeptech|life sciences?|digital|"
    r"energy|mobility|robotics|health|software|hardware|other|others|all|projects?|all projects|"
    r"portraits?|how we support a project|review|spin-off-program|field study fellowship|"
    r"call for applications?|partners?|programme?s?|programs?|news|contact|cookies?|privacy)$",
    re.I,
)

_INSTITUTION = re.compile(
    r"\b(epfl|eth zurich|ethz|helmholtz|max[- ]planck|mpg|sprind|ellis|insurtech hub|"
    r"universit(y|ät|é)|fraunhofer|institute? (of|for|für)|gesellschaft|association)\b",
    re.I,
)

_COOKIE = re.compile(r"\b(cookie|consent|privacy policy|datenschutz|gdpr)\b", re.I)

_INSURERS = re.compile(
    r"\b(allianz|munich re|münchener rück|generali|ergo|swiss re|axa|zurich|hdi|talanx|hannover re|"
    r"signal iduna|nürnberger|versicherungskammer|wüstenrot|w&w|bayerische|debeka|huk|r\+v|"
    r"gothaer|lvm|provinzial|helvetia|baloise|uniqa|vienna insurance|sparkasse|die bayerische)\b",
    re.I,
)

def _txt(s):
    return re.sub(r"\s+", " ", _html.unescape(_TAG.sub(" ", s or ""))).strip()

def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")

def _blocks(html):
    """(heading_text, heading_html, body_html, level) between consecutive headings."""
    html = _SCRIPT.sub(" ", html or "")
    heads = list(_HEAD.finditer(html))
    out = []
    for i, m in enumerate(heads):
        start = m.end()
        end = heads[i + 1].start() if i + 1 < len(heads) else min(len(html), start + 8000)
        out.append((_txt(m.group(2)), m.group(2), html[start:end], int(m.group(1))))
    return out

def _name_ok(name):
    if not name or not (2 <= len(name) <= 90):
        return False
    if CATEGORY_WORDS.match(name.strip()) or _COOKIE.search(name):
        return False
    if _INSTITUTION.search(name) and (
        len(name.split()) <= 3
        or re.search(
            r"\b(startups?|start-?ups?|spin-?(offs?|outs?)|projects?|news|enterprise|"
            r"innovation|creation|entrepreneurs?|program(me)?s?|batch)\b",
            name,
            re.I,
        )
    ):
        return False
    if re.fullmatch(r"[\d\W]+", name):
        return False
    return True

def _emit(src, name, desc, url, location=None, country=None, why=None, bootstrap=False, baseline=False):
    from projectzero.dealflow.scan import parsers as connectors

    c = connectors._mk_from(src, name[:90], desc[:600], url, location, country)
    c["why"] = (c.get("why") or []) + (why or [])
    if bootstrap:
        c["bootstrap_source"] = True  # existed before Project Zero; surfaced on first scan
        c["decision"] = "new"
    elif baseline:
        c["decision"] = "baseline"
    return c

def _seen_gate(src, key, first):
    """False = skip (already seen). Marks the key."""
    from projectzero.dealflow.scan import parsers as connectors

    if not first and connectors._peek(src, key):
        return False
    connectors._mark(src, key)
    return True

def _first(src):
    return not (src.get("hwm") or {}).get("seen")

_CAT_VOCAB = re.compile(
    r"^(biotech|cleantech|engineering|ict|medtech|fintech|deeptech|digital|health|life sciences?|"
    r"energy|software|hardware|robotics|mobility|foodtech|edtech|agritech|spacetech|other|others)$",
    re.I,
)

_CAT_EL = re.compile(r"<(button|a|span|div|li|h[1-6])[^>]*>([^<]{2,30})</\1>", re.I)

def p_epfl_creation(src):
    """Table rows (Project | Description | Project Leader(s) | Executive Summary). The category is the
    nearest preceding category BUTTON / label / heading (Biotech, Cleantech, Engineering, ICT, Medtech...)."""
    from projectzero.dealflow.scan import parsers as connectors

    html = _SCRIPT.sub(" ", connectors._get(src["url"]))
    first = _first(src)
    out = []
    category = ""
    events = sorted(
        [(m.start(), "c", _txt(m.group(2))) for m in _CAT_EL.finditer(html)]
        + [(m.start(), "t", m) for m in _TABLE.finditer(html)],
        key=lambda x: x[0],
    )
    for _, kind, m in events:
        if kind == "c":
            if _CAT_VOCAB.match(m.strip()):
                category = m.strip()  # nearest preceding category element
            continue
        for row in _TR.finditer(m.group(1)):
            if re.search(r"<th", row.group(0), re.I):
                continue
            cells = _TD.findall(row.group(1))
            if len(cells) < 2:
                continue
            name = _txt(cells[0])
            desc = _txt(cells[1])
            leaders = _txt(cells[2]) if len(cells) > 2 else ""
            summ = cells[3] if len(cells) > 3 else ""
            if not _name_ok(name) or len(desc) < 15 or name.lower() in ("project", "projects"):
                continue
            link = _A.search(summ) or _A.search(cells[0])
            url = urljoin(src["url"], link.group(1)) if link else src["url"] + "#" + _slug(name)
            d = ("Category: " + category + ". " if category else "") + desc
            if leaders:
                d += " Project leader(s): " + leaders + "."
            if not _seen_gate(src, url, first):
                continue
            c = _emit(
                src,
                name,
                d,
                url,
                "Lausanne, Switzerland",
                "Switzerland",
                why=["EPFL startup in creation (official pre-company list)"],
                bootstrap=first,
            )
            c["category"] = category or "UNKNOWN"
            out.append(c)
    src["last_first_scan"] = first
    return out

_BATCH = re.compile(r"\bbatch\s+(?:[IVX]+\s+)?(20\d\d)\b", re.I)

_HE_HEAD_BAN = re.compile(
    r"\b(review|spin-?off-?program(me)?|field study fellowship|call for application|partners?|"
    r"program(me)?|jury|contact|news|apply|funding line|eligibility)\b",
    re.I,
)

def p_helmholtz_enterprise(src):
    """Live hierarchy: H2 'Batch I 2026' -> H3 project headings (e.g. 'Chaser Robotics (Field Study)')
    until the NEXT Batch heading. '(Field Study)' is stripped from the name and kept as metadata."""
    from projectzero.dealflow.scan import parsers as connectors

    html = connectors._get(src["url"])
    first = _first(src)
    blocks = _blocks(html)
    years = [int(_BATCH.search(h).group(1)) for h, _, _, _ in blocks if _BATCH.search(h)]
    newest = max(years) if years else None
    out = []
    batch, batch_level, year = None, None, None
    for heading, hh, body, level in blocks:
        if _BATCH.search(heading):
            batch, batch_level, year = heading, level, int(_BATCH.search(heading).group(1))
            for raw in [_txt(x) for x in _LI.findall(body)]:  # flat <li> lists directly under the batch
                _he_emit(src, out, raw, batch, year == newest, first, body)
            continue
        if batch is None or level <= batch_level:
            batch = None  # left the batch section (a new non-batch H2)
            continue
        _he_emit(
            src,
            out,
            heading + (" - " + _txt(body)[:200] if _txt(body) else ""),
            batch,
            year == newest,
            first,
            hh + body,
        )
    src["last_first_scan"] = first
    return out

def _he_emit(src, out, raw, batch, latest, first, link_html):
    fs = bool(re.search(r"\(\s*field study\s*\)", raw, re.I))
    raw = re.sub(r"\s*\(\s*field study\s*\)", "", raw, flags=re.I)
    name = re.split(r"\s+[–—|:(]\s*|\s+-\s+", raw, maxsplit=1)[0].strip()
    if not _name_ok(name) or _HE_HEAD_BAN.search(name) or _BATCH.search(name):
        return
    rest = raw[len(name) :].strip(" –—|:()-")
    desc = (
        "Helmholtz Enterprise " + batch + (" (Field Study Fellowship)" if fs else "") + " spin-off project. " + rest
    ).strip()
    link = next(
        (
            urljoin(src["url"], m.group(1))
            for m in _A.finditer(link_html or "")
            if _txt(m.group(2)).lower().startswith(name.lower()[:12])
        ),
        None,
    )
    key = link or (src["url"] + "#" + _slug(batch) + "-" + _slug(name))
    if not _seen_gate(src, key, first):
        return
    c = _emit(
        src,
        name,
        desc,
        link or src["url"] + "#" + _slug(name),
        "Germany",
        "Germany",
        why=["Helmholtz Enterprise " + batch],
        bootstrap=first and latest,
        baseline=first and not latest,
    )
    c["field_study"] = fs
    c["batch"] = batch
    out.append(c)

_SPRIND_BAN = re.compile(
    r"^(portraits?|all projects|projects?|how we support a project|filter|more|read more|"
    r"energy|robotics|biotech|health|mobility|software|hardware|climate|space|all)$",
    re.I,
)

_SPRIND_NAME = re.compile(r"^([A-Z0-9][\w\-\.&+]*(?: [\w\-\.&+]+){0,4})\s+[–—-]\s+(.{3,120})$")

_SPRIND_LOC = re.compile(r"^([A-ZÄÖÜ][\w\-\.äöüß ]{1,40}),\s*([A-Z]{2,}|[A-Z][a-z]+(?: [A-Z][a-z]+)?)$")

def p_sprind_projects(src):
    """Live 'All Projects' directory: rows/cards with 'Name — Innovation', 'Location, COUNTRY' and a
    description. Project-specific query URLs (?project=...) are used when present, never required."""
    from projectzero.dealflow.scan import parsers as connectors

    html = _SCRIPT.sub(" ", connectors._get(src["url"]))
    first = _first(src)
    lines = connectors._lines(html)
    hrefs = {}
    for m in _A.finditer(html):
        if "project=" in m.group(1):
            hrefs[_txt(m.group(2)).split(" – ")[0].split(" — ")[0].strip().lower()] = urljoin(src["url"], m.group(1))
    out, cur = [], None

    def flush():
        if not cur:
            return
        name, tag, loc, country, desc = (
            cur["name"],
            cur["tag"],
            cur["loc"],
            cur["country"],
            " ".join(cur["desc"]).strip(),
        )
        if _SPRIND_BAN.match(name) or CATEGORY_WORDS.match(name) or not _name_ok(name):
            return
        url = hrefs.get(name.lower()) or src["url"] + "#" + _slug(name)
        if not _seen_gate(src, url, first):
            return
        d = (tag + ". " if tag else "") + (desc or "SPRIND supported project.")
        out.append(
            _emit(
                src,
                name,
                d[:500],
                url,
                loc or "Germany",
                (country or "Germany"),
                why=["SPRIND supported project (official directory)"],
                baseline=first,
            )
        )

    for ln in lines:
        m = _SPRIND_NAME.match(ln)
        if m and not _SPRIND_BAN.match(m.group(1)) and not CATEGORY_WORDS.match(m.group(1)):
            flush()
            cur = {"name": m.group(1).strip(), "tag": m.group(2).strip(), "loc": "", "country": "", "desc": []}
            continue
        if cur is None:
            continue
        lm = _SPRIND_LOC.match(ln)
        if lm and not cur["loc"] and not cur["desc"]:
            cur["loc"], cur["country"] = (
                lm.group(1).strip(),
                lm.group(2).strip().title() if lm.group(2).isupper() and len(lm.group(2)) > 3 else lm.group(2),
            )
            continue
        if CATEGORY_WORDS.match(ln) or _SPRIND_BAN.match(ln):
            flush()
            cur = None
            continue
        cur["desc"].append(ln)
    flush()
    src["last_first_scan"] = first
    return out

def p_mpg_startups(src):
    from projectzero.dealflow.scan import parsers as connectors

    html = connectors._get(src["url"])
    first = _first(src)
    out = []
    for name, hh, body, level in _blocks(html):
        if level == 1 or not _name_ok(name):
            continue
        desc = _txt(body)
        if len(desc) < 40 or not re.search(
            r"\b(spin-?off|start-?up|founded|company|gmbh|ag\b|technolog|develop)\b", desc, re.I
        ):
            continue
        link = _A.search(hh)  # THE link inside the company heading
        url = urljoin(src["url"], link.group(1)) if link else src["url"] + "#" + _slug(name)
        if not _seen_gate(src, url, first):
            continue
        out.append(
            _emit(
                src,
                name,
                desc[:500],
                url,
                "Germany",
                "Germany",
                why=["Max Planck start-up list: mixed/announcement tier deeptech signal"],
                baseline=first,
            )
        )
    src["last_first_scan"] = first
    return out

_VENTURE = re.compile(
    r"\b(spin-?outs?|spin-?offs?|start-?ups?|co-?found(ed|s)?|found(ed|s)|launch(ed|es)|venture)\b", re.I
)

_NT = r"(?:[A-Z][\w\-\.]*|AI|Labs?|GmbH|AG)"

_NAME_TOK = (
    r"(?-i:" + _NT + r"(?:\s+" + _NT + r")*)"
)  # name tokens stay case-SENSITIVE inside the case-insensitive pattern

_NAMED = re.compile(
    r"co-?founds?(?:ed)?\s+(?:the\s+)?(?:(?:ai\s+)?(?:startup|start-?up|spin-?out|spin-?off|company|venture)\s+)?("
    + _NAME_TOK
    + r")|"
    r"(?:startup|start-?up|spin-?out|spin-?off|company|venture)\s+(?:called\s+|named\s+)?(" + _NAME_TOK + r")|"
    r"("
    + _NAME_TOK
    + r"),?\s+(?:a|the)\s+(?:new\s+)?(?:\w+-based\s+)?(?:ai\s+)?(?:startup|start-?up|spin-?out|spin-?off)\b|"
    r"(?:launch(?:ed|es)|founded|announc(?:ed|es))\s+(?:the\s+)?(?:startup\s+|start-?up\s+)?(" + _NAME_TOK + r")",
    re.I,
)

_LEAD_STRIP = re.compile(r"^(?:the|a|an|new|startup|start-?up|spin-?out|spin-?off|company)\s+", re.I)

def _venture_name(text):
    for m in _NAMED.finditer(text):
        name = next(g for g in m.groups() if g)
        name = _LEAD_STRIP.sub("", name).strip(" .,;:")
        name = re.sub(
            r"\s+(is|are|was|were|will|has|have|announces?|launches?|to|that|which|and|with|for|on|in|at)$",
            "",
            name,
            flags=re.I,
        ).strip()
        if not name or len(name) < 3 or len(name.split()) > 4:
            continue
        if (
            _INSTITUTION.search(name)
            or CATEGORY_WORDS.match(name)
            or re.search(r"-based$|^(pi|researchers?|team)$", name, re.I)
        ):
            continue
        if not name[0].isupper() and not name[0].isdigit():
            continue
        return name
    return None

def p_ellis_signal(src):
    from projectzero.dealflow.scan import parsers as connectors

    html = connectors._get(src["url"])
    first = _first(src)
    out = []
    for heading, hh, body, level in _blocks(html):
        if level == 1:
            continue
        text = heading + ". " + _txt(body)
        if not _VENTURE.search(text):
            continue
        name = _venture_name(heading) or _venture_name(_txt(body))  # explicit title first, then body
        if not name:
            continue
        link = _A.search(hh) or _A.search(body)
        url = urljoin(src["url"], link.group(1)) if link else src["url"] + "#" + _slug(name)
        if not _seen_gate(src, url + "|" + name, first):
            continue
        out.append(
            _emit(
                src,
                name,
                text[:400],
                url,
                "Tübingen, Germany",
                "Germany",
                why=["ELLIS Institute Tübingen: article explicitly names the venture"],
                bootstrap=first,
            )
        )
    src["last_first_scan"] = first
    return out

_RELEVANT = re.compile(
    r"\b(cohort|batch|venture client|startup program(me)?|accelerator|selected startups?|"
    r"meet the startups|new startups|startups? join)\b",
    re.I,
)

_NAME_LINE = re.compile(r"^([A-Z][\w\-\.&]*(?: [A-Za-z0-9][\w\-\.&]*){0,3})(?:\s*[–—:|-]\s*(.+))?$")

_SEC_HEAD = re.compile(r"the startups of the venture client program", re.I)

_LABELS = re.compile(
    r"^(data\s*&\s*ai|data and ai|esg|customer interface|customer experience|claims|underwriting|distribution|"
    r"operations|health|mobility|cyber|embedded|analytics|ai|sustainability|other|others|the startups.*)$",
    re.I,
)

_VERBS = (
    r"(?:has|have|is|are|was|were|offers?|brings?|develops?|developed|orchestrates?|revolutioni[sz]es?|uses?|"
    r"integrates?|provides?|enables?|helps?|builds?|delivers?|automates?|combines?|lets?|allows?|turns?|analy[sz]es?|"
    r"detects?|connects?|creates?|makes?|supports?|focuses|speciali[sz]es|works?|leverages?|applies|tackles?|addresses|"
    r"simplifies|reduces?|improves?|transforms?|empowers?|streamlines?|digiti[sz]es?|accelerates?|optimi[sz]es?|"
    r"monitors?|predicts?|protects?|secures?|manages?|generates?|identifies|assesses|calculates?|scores?|matches|"
    r"models?|prevents?|recogni[sz]es?|aims?|wants?|plans?|promises|claims|serves?|targets?|replaces?|extracts?|"
    r"translates?|verifies|validates?|compares?|measures?|tracks?|plugs?|sells?|runs?|operates?|powers?|positions?|equips?)"
)

_NT2 = r"(?:[A-Z0-9][\w\-\.]*|go|by|de|the)"

_NAME2 = r"((?:[a-z]{1,3}\s+)?[A-Z0-9][\w\-\.&]*(?:\s+[A-Z0-9][\w\-\.&]*){0,2})"

_CTX = r"(?:^|[.;:!?]\s+|,\s+|\b(?:and|while|whereas|meanwhile|finally|then|also|by|with|complemented by|alongside|plus)\s+)"

_PROSE_NAME2 = re.compile(
    _CTX
    + _NAME2
    + r"(?:,\s+(?:for example|for instance|meanwhile|in turn|which|whose|a|an|the)\b|\s+"
    + _VERBS
    + r"\b)"
)

_STOP = set(
    """the this these those that our we it in with for as at by on from after before together six eight five seven
 four three two one and while whereas meanwhile finally then also plus here there its their his her all each every some many
 insurers insurer insurance startups startup customers customer brokers broker agents agent companies company teams team
 founders founder program programme programs cohort hub munich germany europe partners partner venture client participants
 applications application technology technologies solution solutions platform platforms data ai esg they you he she
 new next first second third last today now""".split()
)

_PROG = re.compile(r"\b(venture client program(me)?|insurtech hub|w1 forum|innovation day|accelerator)\b", re.I)

def _startup_names_from_prose(prose):
    """Real-language extraction: a name is the capitalised phrase (digits and '.ai' allowed, 'go AVA'-style
    lowercase prefix allowed) that starts a clause and is followed by a verb or an appositive/relative
    clause. Connector words (And/While/by...) never become part of the name; section labels never qualify."""
    out, seen = [], set()
    for m in _PROSE_NAME2.finditer(prose):
        name = m.group(1).strip(" .,;:")
        name = re.sub(
            r"^(?:and|while|whereas|meanwhile|finally|then|also|plus|by|with)\s+", "", name, flags=re.I
        ).strip()
        if not name or name.lower() in seen:
            continue
        toks = name.split()
        if len(toks) > 3 or (any(t.lower() in _STOP for t in toks if not re.search(r"\d|\.", t)) and len(toks) == 1):
            continue
        if toks[0].lower() in _STOP and len(toks) == 1:
            continue
        if _LABELS.match(name) or _INSURERS.search(name) or _PROG.search(name) or _RELEVANT.search(name):
            continue
        if all(t.lower() in _STOP for t in toks):
            continue
        if not (re.search(r"[A-Z0-9]", name[0]) or re.match(r"^[a-z]{1,3}\s+[A-Z]", name)):
            continue
        seen.add(name.lower())
        out.append(name)
    return out

def _startup_section(art):
    """Text of the 'The startups of the Venture Client Program ...' section up to the next major H2.
    Sub-headings inside it (Data & AI, ESG, Customer interface...) are labels, never companies."""
    blocks = _blocks(art)
    started, parts = False, []
    start_level = 2
    for heading, hh, body, level in blocks:
        if not started:
            if _SEC_HEAD.search(heading):
                started, start_level = True, level
                parts.append(_txt(body))
            continue
        if level <= start_level:
            break  # next major section
        parts.append(_txt(body))  # sub-block prose; its heading is a label, skipped
    return " ".join(parts).strip()

def _hub_pages(src):
    base = src["url"].rstrip("/") + "/"
    return [base] + [base + "page/%d/" % n for n in (2, 3)]

def p_insurtech_hub(src):
    """English News Hub (/en/news/, pages 1-3) -> relevant Venture Client / cohort / startup-programme
    articles -> startup names from the 'The startups of the Venture Client Program ...' section only."""
    from projectzero.dealflow.scan import parsers as connectors

    first = _first(src)
    out, articles, seen_urls = [], [], set()
    for pu in _hub_pages(src):
        try:
            html = _SCRIPT.sub(" ", connectors._get(pu))
        except Exception:
            continue
        for heading, hh, body, level in _blocks(html):
            if level == 1:
                continue
            teaser = heading + " " + _txt(body)[:300]
            if not _RELEVANT.search(teaser):
                continue
            link = _A.search(hh) or _A.search(body)
            if link:
                aurl = urljoin(src["url"], link.group(1))
                if aurl not in seen_urls:
                    seen_urls.add(aurl)
                    articles.append((heading, aurl))
    for idx, (title, aurl) in enumerate(articles[:8]):
        try:
            art = _SCRIPT.sub(" ", connectors._get(aurl))
        except Exception:
            continue
        prose = _startup_section(art)
        if not prose:
            continue  # no explicit startup section -> nothing to emit
        for name in _startup_names_from_prose(prose):
            if not _seen_gate(src, aurl + "|" + name, first):
                continue
            desc = (
                "Named in InsurTech Hub Munich article '" + title[:80] + "' (Venture Client Program startups section)."
            )
            out.append(
                _emit(
                    src,
                    name,
                    desc,
                    aurl,
                    "Munich, Germany",
                    "Germany",
                    why=["InsurTech Hub Munich Venture Client / cohort article (Regulated Industries signal)"],
                    bootstrap=first and idx == 0,
                    baseline=first and idx > 0,
                )
            )
    src["last_first_scan"] = first
    return out

PARSERS_V2 = {
    "epfl_creation": p_epfl_creation,
    "helmholtz_enterprise": p_helmholtz_enterprise,
    "sprind_projects": p_sprind_projects,
    "mpg_startups": p_mpg_startups,
    "ellis_signal": p_ellis_signal,
    "insurtech_hub": p_insurtech_hub,
}
# fmt: on
