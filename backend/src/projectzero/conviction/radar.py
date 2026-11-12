# ruff: noqa: UP031  -- protected gold-master text: printf-style templates are kept byte-for-byte
# mypy: disable-error-code="index,arg-type"
# (the old lookups EARLINESS[..][0] and CONFLICT_LABELS are kept verbatim, raising on unknown values as before)
"""The Radar, the Scout memo and the outreach email (review 019): the old protected ``domain/radar.py`` and
``taste.compose_radar``, ported mechanically at revision 6c739b9.

Only mechanical changes: the clock is a parameter (``today``) instead of ``date.today()``, ``render_radar`` returns
the document instead of writing ``weekly_memo.html`` into a data folder (decision c), and ``write_deliverables`` is
not ported (each memo and email is served per company). Templates, wording and ordering are frozen; goldens from the
OLD code compare the output. Pure logic, no I/O.
"""

from __future__ import annotations

import html as _html
import re
from datetime import date
from typing import Any

from projectzero.conviction import taste

RADAR_SLOTS = ("high", "emerging", "wildcard")  # the Top 10: the slots that credit the Radar milestone


# fmt: off
def compose_radar(entries: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """The old ``taste.compose_radar``, verbatim: Top 10 (8 high-confidence + 1 emerging + 1 wildcard) is composed
    from FULLY VERIFIED companies only, ranked by Verified score. Unverified companies with Provisional >= 65 go to a
    separate Research Queue. Conflict-gated and watchlist stay separate. Empty slots allowed. It sets ``_sc`` on the
    entries it is given (callers pass copies)."""
    live = [e for e in entries if e.get("status") != "dropped"]
    for e in live:
        e["_sc"] = taste.score(e)
    gated = [e for e in live if e.get("conflict") == "potential_conflict"]
    clean = [e for e in live if e.get("conflict") != "potential_conflict"]
    fv = [e for e in clean if e["_sc"]["fully_verified"]]
    unv = [e for e in clean if not e["_sc"]["fully_verified"]]
    high = sorted([e for e in fv if 1 <= (e.get("archetype") or 0) <= 14 and not e.get("emerging") and e["_sc"]["verified"] >= 65],
                  key=lambda e: -e["_sc"]["verified"])[:8]
    emerging = sorted([e for e in fv if e.get("emerging") and e["_sc"]["verified"] >= 55], key=lambda e: -e["_sc"]["verified"])[:1]
    wild = sorted([e for e in fv if e.get("archetype") == 15 and e["_sc"]["outlier_ok"]], key=lambda e: -e["_sc"]["verified"])[:1]
    research_queue = sorted([e for e in unv if e["_sc"]["provisional"] >= 65], key=lambda e: -e["_sc"]["provisional"])
    placed = set(id(e) for e in high + emerging + wild + research_queue)
    watch = [e for e in clean if id(e) not in placed and max(e["_sc"]["verified"] if e["_sc"]["fully_verified"] else 0, e["_sc"]["provisional"]) >= 50]
    return {"high": high, "emerging": emerging, "wildcard": wild, "research_queue": research_queue, "gated": gated, "watch": watch}


def _l(xs: list[Any], empty: str = "—") -> str:
    return "\n".join(f"- {x}" for x in xs) if xs else f"- {empty}"


def memo(e: dict[str, Any], today: date) -> str:
    sc = taste.score(e)
    a = taste.ARCHETYPE_BY_ID.get(e.get("archetype") or 0)
    b = sc["breakdown"]
    conflict = taste.CONFLICT_LABELS.get(e.get("conflict", "none"))
    founders = _l([f"{f.get('name','?')}" + (f" — {f['background']}" if f.get("background") else "") for f in e.get("founders", [])], "TBD")
    return f"""# Scout memo — {e['company']}
*Project Zero · {today.isoformat()} · Provisional Project A Fit **{sc['provisional']}** · Verified **{sc['verified']}**{' (unverified: ' + ', '.join(sc['missing']) + ')' if sc['missing'] else ' (fully verified)'} · {sc['verdict']}*

**One-liner:** {e.get('one_liner','')}
**Location:** {e.get('location','')} · **Website:** {e.get('website','TBD')}
**Archetype:** {('#%d %s' % (a[0], a[1])) if a else 'not assigned'}{' · EMERGING THESIS' if e.get('emerging') else ''}

## WHY FOUND
Discovery source: {e.get('discovery_source','')} ({taste.DISCOVERY_TIERS.get(e.get('discovery_tier','manual'),'')}) · signal date {e.get('discovery_date','')}
{e.get('why_found','')}

## WHY PROJECT A
{e.get('why_project_a','')}
Portfolio similarity: {e.get('twin') or 'no twin'} — **{conflict}**

## WHY NOW
{e.get('why_now_text','')}

## FOUNDER SIGNAL {'(verified)' if (e.get('verified') or {}).get('founders') else '(UNVERIFIED — provisional)'}
{founders}
{e.get('founder_signal','')}

## VENTURE-SCALE CASE
{e.get('venture_scale_text','')}

## EARLINESS · FUNDRAISING TIMING
Earliness: {taste.EARLINESS.get(e.get('earliness','unknown'))[0]} · Funding status: {e.get('funding_status','unknown')}
Fundraising timing: **{sc['timing_label']}** → {sc['timing_action']}

## BULL / BEAR
Strongest reason to contact: {e.get('bull','')}
Strongest reason to pass: {e.get('bear','')}

## WHAT I NEED TO VERIFY
{_l(e.get('verify_list', []), 'Founders, traction, funding status')}

## NEXT ACTION
{e.get('next_action','')}

## Score breakdown (v2.2)
founder {b['founder']}/25 · venture-scale {b['venture_scale']}/20 · why-now {b['why_now']}/15 · taste {b['taste']}/15 · earliness {b['earliness']}/10 · insight {b['insight']}/10 · resemblance {b['resemblance']}/5 · penalties {b['penalties']}

## Sources
{_l(e.get('sources', []), 'add URLs')}

*Prepared by Mohamed (Scout) · provisional blocks must be verified before forwarding.*
"""


EMAILS = {
    "raising_now": ("Quick one from Project A — {co}", "Hi {first},\n\nI'm Mohamed, scout for Project A (Berlin/London, pre-seed & seed; portfolio incl. Quantum Systems, Sennder, Trade Republic). I've been following {co} — {one}\n\nIf you're in the middle of a round, I'd like to put you in front of our investment team this week; if it's closed, congrats, and a 20-minute call to learn what you're building would still be valuable to me.\n\nBest,\nMohamed\nScout, Project A"),
    "0_6m": ("{co} — hello from Project A", "Hi {first},\n\nI'm Mohamed, scout for Project A (pre-seed & seed, Berlin/London). I came across {co} via {src} — {one}\n\nNo pitch: I'd love 20 minutes to understand what you're building and your timing. Project A tends to move early and brings a 140-person in-house ops/engineering team alongside capital, which matters most before a round rather than during it.\n\nDoes next week work?\n\nBest,\nMohamed\nScout, Project A"),
    "6_12m": ("{co} — staying close from Project A", "Hi {first},\n\nI'm Mohamed, scout for Project A (pre-seed & seed). {co} caught my attention — {one}\n\nI know you're likely heads-down and not raising; this is about relationship, not a round. If you're open to a short call now and a check-in in a couple of months, I'd like that.\n\nBest,\nMohamed\nScout, Project A"),
    "recently_funded": ("Congrats on the round — {co}", "Hi {first},\n\nCongrats on closing your round — well deserved. I'm Mohamed, scout for Project A (pre-seed & seed, Berlin/London). I'm not writing to pitch a round; I'd just like to understand {co} properly so I can be useful when the next window comes (intros in DACH industry, hiring, customers).\n\n20 minutes whenever convenient?\n\nBest,\nMohamed\nScout, Project A"),
    "unknown": ("{co} — hello from Project A", "Hi {first},\n\nI'm Mohamed, scout for Project A (pre-seed & seed, Berlin/London). I found {co} via {src} — {one}\n\nI'd love 20 minutes to learn what you're building and where you are on financing. If timing is right, I can connect you with our investment team; if not, I'm happy to just stay in touch.\n\nBest,\nMohamed\nScout, Project A"),
}


def email(e: dict[str, Any]) -> str:
    subj, body = EMAILS.get(e.get("fundraising_timing", "unknown"), EMAILS["unknown"])
    f0 = (e.get("founders") or [{}])[0]
    name = f0.get("name", "")
    first = name.split()[0] if name and not name.lower().startswith(("tbd", "founder")) else "Founder"
    if first.startswith("Dr") and len(name.split()) > 1:
        first = name.split()[1]
    one = e.get("one_liner", "") or ""
    one = (one[0].lower() + one[1:]) if one and not one[:2].isupper() else one
    ctx = dict(co=re.sub(r"\s+\b(GmbH|UG|AG|Ltd)\b.*$", "", e["company"]), first=first, one=one, src=e.get("discovery_source", "public sources"))
    to = f0.get("email", "TBD — Impressum / LinkedIn")
    warn = ""
    if e.get("conflict") == "potential_conflict":
        warn = "\n\n> ⚠ DO NOT SEND until Omar/Project A confirms the portfolio-conflict question.\n"
    return f"# Outreach — {e['company']}\n\n**To:** {to}\n**Subject:** {subj.format(**ctx)}\n**Timing:** {taste.score(e)['timing_label']}{warn}\n\n{body.format(**ctx)}\n\n---\n*Auto-drafted by Project Zero. Personalise one sentence before sending.*\n"


CSS = """body{font:14px/1.5 'Segoe UI',Arial,sans-serif;color:#1B1F26;background:#F4F4F1;margin:0;padding:36px 20px}
.w{max-width:860px;margin:0 auto}h1{font:700 24px Georgia,serif;margin:0 0 4px}.sub{color:#647084;font-size:13px;margin-bottom:22px}
h2{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:#647084;margin:26px 0 8px;border-bottom:1px solid #DDD;padding-bottom:6px}
.c{background:#fff;border:1px solid #E1E4E9;border-radius:8px;padding:14px 16px;margin-bottom:10px}
.n{font-weight:700;font-size:15px}.s{font:700 18px Georgia,serif;float:right;color:#1F4E79}.s small{font:12px 'Segoe UI';color:#647084;display:block;text-align:right}
.m{color:#647084;font-size:12px;margin-top:2px}.k{font-size:12.5px;margin-top:6px}.k b{color:#1F4E79}
.gate{border-left:4px solid #B3261E}.empty{color:#647084;font-style:italic}"""



def _card(e: dict[str, Any], gate: bool = False) -> str:
    sc = e["_sc"]
    a = taste.ARCHETYPE_BY_ID.get(e.get("archetype") or 0)
    x = _html.escape
    return f"""<div class="c{' gate' if gate else ''}"><span class="s">{sc['verified'] if sc['fully_verified'] else sc['provisional']}<small>{'verified' if sc['fully_verified'] else 'PROVISIONAL · unverified: ' + ', '.join(sc['missing'])}</small></span>
<div class="n">{x(e['company'])}</div><div class="m">{x(e.get('location',''))} · {x(('#%d %s' % (a[0], a[1])) if a else '')}</div>
<div class="k"><b>Why found:</b> {x(e.get('discovery_source',''))} · {x(taste.DISCOVERY_TIERS.get(e.get('discovery_tier','manual'),'').split(' — ')[0])}</div>
<div class="k"><b>Why Project A:</b> {x(e.get('why_project_a',''))}</div>
<div class="k"><b>Why now:</b> {x(e.get('why_now_text',''))}</div>
<div class="k"><b>Founder signal:</b> {x(e.get('founder_signal',''))}</div>
<div class="k"><b>Earliness / timing:</b> {x(taste.EARLINESS.get(e.get('earliness','unknown'))[0])} · <b>{x(sc['timing_label'])}</b> — {x(sc['timing_action'])}</div>
<div class="k"><b>Portfolio:</b> {x(e.get('twin') or 'no twin')} — {x(taste.CONFLICT_LABELS.get(e.get('conflict','none')))}</div>
<div class="k"><b>Verify:</b> {x('; '.join(e.get('verify_list', [])) or 'founders, traction, funding')}</div>
<div class="k"><b>Next action:</b> {x(e.get('next_action',''))}</div></div>"""


def render_radar(entries: list[dict[str, Any]], today: date) -> str:
    """The weekly radar HTML document (the old ``render_radar`` without the file write; decision (c))."""
    r = compose_radar(entries)

    def sec(title: str, items: list[dict[str, Any]], n: int, gate: bool = False) -> str:
        cards = "".join(_card(e, gate) for e in items)
        empties = "".join(f'<div class="c empty">Slot {i+1}: empty — no candidate met the bar this week (left empty on purpose)</div>' for i in range(len(items), n)) if n else ""
        return f"<h2>{title}</h2>{cards}{empties}"

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Project A Radar</title><style>{CSS}</style></head><body><div class="w">
<h1>PROJECT A RADAR — TOP 10</h1><div class="sub">Week of {today.isoformat()} · Composition: 8 high-confidence + 1 emerging + 1 wildcard · Prepared by Mohamed (Scout) · Taste Map v2.2</div>
{sec('High-confidence (8 slots)', r['high'], 8)}
{sec('Emerging / adjacent thesis (1 slot)', r['emerging'], 1)}
{sec('Wildcard — outlier route (1 slot)', r['wildcard'], 1)}
{sec('Research Queue — promising (Provisional ≥ 65) but NOT verified; not Project A candidates yet', r['research_queue'], 0) if r['research_queue'] else ''}
{sec('Conflict-gated — for Omar, not for forwarding', r['gated'], 0, True) if r['gated'] else ''}
{sec('Watchlist (50–64)', r['watch'], 0) if r['watch'] else ''}
<div class="sub" style="margin-top:26px">Top 10 is composed from fully verified companies only (founders, traction, funding checked), ranked by Verified score. Unverified companies never appear as high-confidence — they sit in the Research Queue with a provisional score. Fundraising timing drives urgency; recent funding lowers it. Portfolio conflicts are warnings for Project A to judge, not verdicts.</div>
</div></body></html>"""
    return doc
# fmt: on
