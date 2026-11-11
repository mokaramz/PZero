"""The ported ranking rules reproduce the v1 golden outputs exactly (review 006).

Every per-candidate output is compared after a JSON round trip (tuples become lists, exactly as the old generator
stored them), key by key, including list order.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from projectzero.dealflow.ranking import attention, themes
from projectzero.dealflow.ranking.names import norm_company

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "golden_v1"
SHA256 = {
    "inbox_sample.json": "a1af71497d308111e4c204e0348cf9a8b8fae078cfb0052894ce06e768398571",
    "attention_themes.json": "fc938d48ecb16c4d356cba4648b3b4bf9096a21a7961a3d14eb894e192ea1dfe",
    "connectors_text.json": "f1220f27c10ba8df62b9bc7f9196460ddb1bb51e0dd4645772c33fa0399feaa6",
}


def load(name: str) -> Any:
    raw = (GOLDEN / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SHA256[name], f"{name} is not the pinned v1 golden"
    return json.loads(raw.decode("utf-8"))


SAMPLE = load("inbox_sample.json")
EXPECTED = load("attention_themes.json")
TEXT = load("connectors_text.json")
CANDIDATES = {c["id"]: c for c in SAMPLE["candidates"]}
LAST_RUN = SAMPLE["last_run"]


def js(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def outputs(c: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(str(c.get(k, "")) for k in ("name", "description"))
    return js(
        {
            "gate": attention.gate(c),
            "entity_type": attention.entity_type(c),
            "entity_info": attention.entity_info(c),
            "score_v2": attention.score_v2(c, LAST_RUN),
            "differentiation": attention.differentiation(c),
            "annotate": attention.annotate(c, LAST_RUN),
            "annotate_v3": attention.annotate_v3(c, LAST_RUN),
            "annotate_v31": attention.annotate_v31(c, LAST_RUN),
            "themes_for": themes.themes_for(c),
            "lens_signals": themes.lens_signals(c),
            "technical_founder_evidence": themes.technical_founder_evidence(text),
        }
    )


def test_sample_and_expected_cover_the_same_candidates() -> None:
    assert set(CANDIDATES) == set(EXPECTED["per_candidate"]) == set(TEXT)
    assert len(CANDIDATES) == 141


@pytest.mark.parametrize("candidate_id", sorted(CANDIDATES))
def test_every_rule_output_matches_v1(candidate_id: str) -> None:
    got = outputs(CANDIDATES[candidate_id])
    want = EXPECTED["per_candidate"][candidate_id]
    assert got.keys() == want.keys()
    for key in want:
        assert got[key] == want[key], f"{candidate_id} {key}"


@pytest.mark.parametrize("candidate_id", sorted(CANDIDATES))
def test_norm_company_matches_v1(candidate_id: str) -> None:
    assert norm_company(CANDIDATES[candidate_id].get("name")) == TEXT[candidate_id]["norm_company"]


def test_constants_match_v1() -> None:
    assert js(attention.ENTITY_LABELS) == EXPECTED["ENTITY_LABELS"]
    assert js(attention.ENTITY_PENALTY) == EXPECTED["ENTITY_PENALTY"]
    assert js(themes.THEMES) == EXPECTED["THEMES"]


def test_the_sample_exercises_the_rules() -> None:
    """Guard against a vacuous golden: the sample must hit gates, every entity type and both score signs."""
    finals = [EXPECTED["per_candidate"][i]["annotate_v31"] for i in CANDIDATES]
    assert sum(1 for f in finals if f["gated"]) >= 10
    assert {f["entity"]["type"] for f in finals} >= {"VENTURE", "POSSIBLE_VENTURE", "UNKNOWN_ENTITY_TYPE"}
    assert min(f["final"] for f in finals) < 0 < max(f["final"] for f in finals)
