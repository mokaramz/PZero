"""Parent themes and the Investment Manager lens (protected; old ``domain/themes.py``).

Parent themes = Project A's investment strategy. The 15 archetypes are only MAPPED onto them; nothing here changes
scoring, sourcing or Radar.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from projectzero.dealflow.ranking.pytext import joined

THEMES = {
    "defence": "Defence Technologies",
    "industrial_autonomy": "Industrial Autonomy",
    "regulated": "Regulated Industries",
    "frontier": "Frontier Technologies",
    "physical_world": "Physical World Intelligence",
}

# archetype id -> parent theme keys. Static ONLY where the archetype is unambiguous. #1 (vertical AI), #13 (studio
# duo = stage/founder pattern) and #15 (outlier) infer the theme from the thesis text instead.
ARCHETYPE_THEMES = {
    2: ["industrial_autonomy"],
    3: ["regulated"],
    4: ["regulated"],
    5: ["defence"],
    6: ["defence", "industrial_autonomy", "physical_world"],
    7: ["industrial_autonomy"],
    8: ["physical_world"],
    9: ["regulated", "physical_world"],
    10: ["frontier", "defence"],
    11: ["frontier"],
    12: ["industrial_autonomy"],
    14: ["frontier", "physical_world"],
}
DOMAIN_INFERRED = {1, 13, 15}
ARCHETYPE_IDS = frozenset(range(1, 16))  # Taste Map v2.2 archetypes #1-#15
assert set(ARCHETYPE_THEMES) | DOMAIN_INFERRED == ARCHETYPE_IDS, "every archetype accounted for"

_VERTICAL_AI_ALLOWED = ("industrial_autonomy", "regulated", "physical_world")

# light keyword hints for candidates the strict matcher did not tag (never used for scoring)
THEME_KW = {
    "defence": r"\b(defen[cs]e|military|dual.use|nato|battlefield|munition|isr\b|sovereign security)",
    "industrial_autonomy": r"\b(freight|forwarding|logistics|procurement|supply.chain|industrial (operations|trade|ai|software)|"
    r"robot\w*|autonom\w*|automation|factory|manufactur\w*|shop.floor|cnc|warehouse|fleet operations)",
    "regulated": r"\b(insur\w*|underwrit\w*|claims|fintech|compliance|regulat\w*|bank\w*|payments?|kyc|aml|accounting|"
    r"clinical|pharma\w*|medtech|medical device|healthcare|audit)",
    "frontier": r"\b(quantum|photonic\w*|foundation model|novel (ai|architecture|algorithm)|semiconductor|chip design|fusion|"
    r"neuromorphic|space|satellite|synthetic biology|new materials?|research spin.?out)",
    "physical_world": r"\b(energy (infrastructure|procurement|grid|storage|assets?)|power grid|grid|sensor\w*|iot|"
    r"critical infrastructure|construction|agri\w*|drone\w*|digital twin|geospatial|mobility|charging|"
    r"pipelines?|utilities)",
}  # fmt: skip


def _infer(text: str, allowed: tuple[str, ...] | None = None) -> list[str]:
    return [t for t, rx in THEME_KW.items() if (allowed is None or t in allowed) and re.search(rx, text, re.I)]


def themes_for(cand: Mapping[str, Any]) -> list[str]:
    """Parent themes: static mapping for unambiguous archetypes; domain inference for #1 (restricted), #13 and #15;
    keyword inference when nothing was tagged. Never forces a theme onto the outlier or the studio-duo pattern."""
    hits = [h for h in (cand.get("archetype_hits") or []) if isinstance(h, int)]
    text = joined(cand, ("name", "description", "sectors", "notes")).lower()
    out: list[str] = []
    for aid in hits:
        for tkey in ARCHETYPE_THEMES.get(aid, []):
            if tkey not in out:
                out.append(tkey)
    if 1 in hits:
        for tkey in _infer(text, _VERTICAL_AI_ALLOWED):
            if tkey not in out:
                out.append(tkey)
    if (13 in hits or 15 in hits) or not hits:
        for tkey in _infer(text):
            if tkey not in out:
                out.append(tkey)
    return out


# ---- Investment Manager lens: a ranking lens, never a filter ----
SPINOUT = re.compile(
    r"\b(universit\w*|tu (münchen|munich|berlin|darmstadt|dresden)|eth\b|epfl|kit\b|rwth|fraunhofer|max.planck|"
    r"helmholtz|cnrs|inria|imperial|cambridge|oxford|dtu|kth|chalmers|spin.?(out|off)|research (group|institute|lab)|"
    r"phd|doctoral|postdoc|professor)\b",
    re.I,
)
_NOVEL_AI = re.compile(
    r"\b(novel|first-of-its-kind|new (class of|kind of|architecture)|foundation model|world model|"
    r"physics-(informed|based) (ai|ml)|neuromorphic|neurosymbolic|self-supervised|sim2real|"
    r"reinforcement learning|diffusion model|graph neural|causal (ai|inference)|multi-agent)\b",
    re.I,
)
_RESEARCH_SRC = re.compile(
    r"\b(exist|horizon|eic\b|erc\b|dfg|bmbf|grant|accelerator|incubator|fellowship|"
    r"research funding|innovation programme|innovation program|startup competition|prize)\b",
    re.I,
)

# ---- shared, conservative technical-founder evidence ----
_TF_ROLE = (
    r"(?<![a-z])(phd|dr|prof|professor|researchers?|scientists?|cto|engineers?|physicists?|chemists?|"
    r"biologists?|mathematicians?|postdocs?|research (lead|fellow|group leader)|ex-(cern|nasa|esa|darpa|deepmind|"
    r"google brain|openai))(?![a-z])"
)
_TF_PERSON = r"\b(founders?|co-?founders?|project leaders?\(?s?\)?|leaders?|team|led by|founded by|ceo|cto)\b"


def technical_founder_evidence(text: Any) -> bool:
    """True only when a clause EXPLICITLY ties a founder / project leader / team member to a technical or research
    role. Never inferred from 'Category: Engineering', product words, an affiliation or a bare name."""
    t = re.sub(r"\s+", " ", str(text or ""))
    t = re.sub(r"\b(dr|prof|ph\.d)\.", lambda m: m.group(1).replace(".", ""), t, flags=re.I)
    for clause in re.split(r"(?<=[.;!?])\s+|\n", t):
        cl = clause.lower()
        if re.search(r"\bcategory\s*:", cl) and not re.search(_TF_PERSON, cl):
            continue
        if re.search(_TF_PERSON, cl) and re.search(_TF_ROLE, cl):
            return True
    return False


def lens_signals(cand: Mapping[str, Any]) -> tuple[int, list[str]]:
    """Evidence-based Investment Manager lens. Returns (score, signal labels)."""
    text = joined(cand, ("name", "description", "notes", "founder_signal", "why_found", "source", "sectors")).lower()
    score, sig = 0, []
    th = themes_for(cand)
    if "frontier" in th:
        score += 3
        sig.append("Frontier Technologies")
    if 15 in (cand.get("archetype_hits") or []):
        score += 1
        sig.append("outlier route")
    if _NOVEL_AI.search(text):
        score += 2
        sig.append("novel / non-obvious AI")
    if technical_founder_evidence(text):
        score += 2
        sig.append("technical founders")
    if SPINOUT.search(text):
        score += 3
        sig.append("university / research spinout")
    tier = cand.get("discovery_tier") or ""
    if tier == "pre_company":
        score += 2
        sig.append("pre-company")
    elif tier == "grant":
        score += 2
        sig.append("grant / research signal")
    if re.search(r"\bpre.?seed\b", text):
        score += 1
        sig.append("pre-seed")
    src = str(cand.get("source", "")) + " " + str(cand.get("source_id", ""))
    if (_RESEARCH_SRC.search(src) or _RESEARCH_SRC.search(text)) and "grant / research signal" not in sig:
        score += 2
        sig.append("research/grant/accelerator signal")
    if re.search(
        r"\b(patent|peer.reviewed|published (in|at)|arxiv|benchmark|proprietary (dataset|model|sensor))\b", text
    ):
        score += 1
        sig.append("technical insight beyond the homepage")
    return score, sig
