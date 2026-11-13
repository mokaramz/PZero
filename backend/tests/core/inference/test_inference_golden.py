"""The gateway against the OLD gateway as oracle (``oracle_inference.json``, ``python -m
projectzero.ops.parity_inference goldens``): every Result, estimate, wait, provider call, ledger row and decision
equal once the declared differences are applied, and each declared difference really occurs."""

from __future__ import annotations

from projectzero.ops import parity_inference as parity


def test_golden_provenance_and_cases() -> None:
    golden = parity.load_golden()
    assert golden["provenance"]["old_revision"].startswith("6c739b9") and golden["provenance"]["old_dirty"] is False
    assert golden["cases"] == parity.js(parity.CASES)
    assert parity.GOLDEN.read_bytes().endswith(b"\n") and b"\r\n" not in parity.GOLDEN.read_bytes()


def test_new_gateway_matches_the_old_one_with_the_declared_differences() -> None:
    assert parity.compare(parity.load_golden()) == []


def test_the_declared_differences_occur() -> None:
    old = {c["name"]: c for c in parity.load_golden()["expected"]}
    # (c): unset ran the old call; (d): the old cache served while paid was off
    assert old["c_unset"]["steps"][0]["result"]["ok"] is True
    assert old["d_cache_off"]["steps"][1]["result"]["cached"] is True
    # per-attempt admission: the old retry was sent and succeeded
    assert old["retry_blocked"]["steps"][0]["result"]["attempts"] == 2
    # after-dispatch failures: the old app charged $0
    retries = old["retries"]["steps"]
    assert retries[8]["result"]["error_kind"] == "server" and retries[8]["result"]["usd"] == 0.0
    new = parity.run_new(next(c for c in parity.CASES if c["name"] == "retries"))
    assert new["steps"][8]["result"]["usd"] == round(3 * new["steps"][8]["est"], 8)
    assert [r["detail"]["attempt"] for r in new["steps"][8]["rows"]] == [1, 2, 3]
    # (h)
    assert old["refusals"]["steps"][2]["result"]["error_kind"] == "disabled"
