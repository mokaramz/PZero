"""The machine-triage cascade for ONE candidate (review 035b): the old ``services/shadow_triage.py`` ``validator_for``,
``_complete_with_schema_retry`` and the body of ``run``'s loop, over an injected model call (the runner binds it to
the inference gateway with the run's id and cap). No database work here.

* **The rules** (``cascade_rules``, cut by script): the prompt (sha-pinned), Stage 0, the reject-support check, the
  veto's formatting repair and the combination rule.
* **The validator** (``validator_for``): the old pydantic ``TriageProposal`` HAND-PORTED (the new app has no
  pydantic): the same fields, defaults, ``mode="before"`` normalisations, lax type rules and error texts
  (``"<loc>: <msg>"`` joined by ``"; "``, cut at 400), then the old grounding (founders verbatim, unknown themes
  dropped, the reject-support downgrade). The oracle checks it against the old model over valid, repairable,
  malformed and unsupported-REJECT replies.
* **One candidate** (``triage_one``): the skip rule (the same ``input_sha`` and models: no call), Stage 0 (no call),
  Stage 1 on CHEAP with ONE schema retry (``use_cache=False``), the veto on STANDARD with the Qwen model and thinking
  off only for a supported REJECT, the combination; a ``must_stop`` result stops the run (``Stop``), any other failure
  is an ``error`` entry and the run goes on.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from projectzero.core.inference.gateway import Result
from projectzero.dealflow.ranking import attention, themes
from projectzero.dealflow.triage import card
from projectzero.dealflow.triage import cascade_rules as rules

PROMPT_VERSION = card.PROMPT_VERSION
CHEAP_MODEL = card.CHEAP_MODEL
VETO_MODEL = card.VETO_MODEL
LOCKED_V3 = card.LOCKED_V3
VETO_PURPOSE = "shadow_triage_veto"
PURPOSE = "shadow_triage"
_PROPOSAL = ("KEEP", "RESEARCH", "WATCH", "REJECT")
_CONFIDENCE = ("low", "medium", "high")


# ------------------------------------------------------------------ the validator (old pydantic TriageProposal)
def _literal_msg(values: tuple[str, ...]) -> str:
    quoted = [f"'{v}'" for v in values]
    return "Input should be " + (", ".join(quoted[:-1]) + " or " + quoted[-1] if len(quoted) > 1 else quoted[0])


def _norm(v: Any) -> Any:  # old ``_norm``: proposal, entity_type, capital_stage
    return v.strip().replace(" ", "_").upper() if isinstance(v, str) else v


def _basis(v: Any) -> Any:  # old ``_basis``
    if v is None or (isinstance(v, str) and v.strip().lower() in ("", "null", "none", "n/a")):
        return None
    return v.strip().replace(" ", "_").replace("-", "_").upper() if isinstance(v, str) else v


def _conf(v: Any) -> Any:  # old ``_conf``
    return v.strip().lower() if isinstance(v, str) else v


_MISSING = object()


def model_validate(data: dict[str, Any]) -> dict[str, Any]:
    """The old ``TriageProposal.model_validate(data).model_dump()`` (pydantic 2.14, lax mode over JSON values): the
    fields in declaration order; extra keys ignored; ``ValueError`` with the old joined error text."""
    errors: list[tuple[str, str]] = []
    out: dict[str, Any] = {}

    def literal(name: str, values: tuple[str, ...], before: Callable[[Any], Any] | None, default: Any) -> None:
        raw = data.get(name, _MISSING)
        if raw is _MISSING:
            if default is _MISSING:
                errors.append((name, "Field required"))
            else:
                out[name] = default
            return
        v = before(raw) if before else raw
        if isinstance(v, str) and v in values:
            out[name] = v
        else:
            errors.append((name, _literal_msg(values)))

    def string(name: str, default: Any, before: Callable[[Any], Any] | None = None) -> None:
        raw = data.get(name, _MISSING)
        if raw is _MISSING:
            out[name] = default
            return
        v = before(raw) if before else raw
        if isinstance(v, str):
            out[name] = v
        else:
            errors.append((name, "Input should be a valid string"))

    def str_list(name: str, required: bool, min_length: int = 0) -> None:
        raw = data.get(name, _MISSING)
        if raw is _MISSING:
            if required:
                errors.append((name, "Field required"))
            else:
                out[name] = []
            return
        if not isinstance(raw, (list, tuple)):
            errors.append((name, "Input should be a valid list"))
            return
        bad = [i for i, x in enumerate(raw) if not isinstance(x, str)]
        for i in bad:
            errors.append((f"{name}.{i}", "Input should be a valid string"))
        if bad:
            return
        if len(raw) < min_length:
            errors.append((name, f"List should have at least {min_length} item after validation, not {len(raw)}"))
            return
        out[name] = list(raw)

    literal("proposal", _PROPOSAL, _norm, _MISSING)
    literal("entity_type", rules.ENTITY_TYPES, _norm, "UNKNOWN")
    literal("capital_stage", rules.CAPITAL_STAGES, _norm, "UNKNOWN")
    string("sector", "")
    str_list("themes", False)
    str_list("founders", False)
    str_list("reasons", True, 1)
    str_list("missing", False)
    literal("confidence", _CONFIDENCE, _conf, _MISSING)
    raw_basis = data.get("reject_basis", _MISSING)
    if raw_basis is _MISSING:
        out["reject_basis"] = None
    else:
        b = _basis(raw_basis)
        if b is None or (isinstance(b, str) and b in rules.REJECT_BASES):
            out["reject_basis"] = b
        else:
            errors.append(("reject_basis", _literal_msg(rules.REJECT_BASES)))
    string("reject_evidence", "", lambda v: "" if v is None else v)
    if errors:
        raise ValueError("; ".join(f"{loc}: {msg}" for loc, msg in errors)[:400])
    return out


def validator_for(card_text: str, cand: Mapping[str, Any] | None = None) -> Callable[[Any], dict[str, Any]]:
    """The old ``validator_for``: strict schema check + grounding."""
    low = card_text.lower()

    def _validate(data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("reply is not a JSON object")
        data, repaired = rules.basis_as_proposal(data)
        out = model_validate(data)
        flags: list[str] = [repaired] if repaired else []
        kept = [f.strip() for f in out["founders"] if isinstance(f, str) and f.strip() and f.strip().lower() in low]
        if len(kept) != len(out["founders"]):
            flags.append(
                f"dropped {len(out['founders']) - len(kept)} founder name(s) not present in the candidate text"
            )
        out["founders"] = kept[:6]
        bad_themes = [t for t in out["themes"] if t not in themes.THEMES]
        if bad_themes:
            flags.append("dropped unknown theme(s): " + ", ".join(map(str, bad_themes))[:120])
        out["themes"] = [t for t in out["themes"] if t in themes.THEMES]
        out["reasons"] = [str(r)[:240] for r in out["reasons"][:3]]
        out["missing"] = [str(m)[:240] for m in out["missing"][:3]]
        out["sector"] = str(out["sector"])[:80]
        out["model_proposal"] = out["proposal"]
        if out["proposal"] == "REJECT":
            problem = rules.reject_support_problem(
                out.get("reject_basis"),
                out.get("reject_evidence", ""),
                card_text,
                dict(cand) if isinstance(cand, Mapping) else None,
            )
            if problem:
                out["proposal"] = "RESEARCH"
                flags.append("REJECT downgraded to RESEARCH: " + problem)
        else:
            out["reject_basis"], out["reject_evidence"] = None, ""
        out["reject_evidence"] = str(out.get("reject_evidence") or "")[:240]
        out["flags"] = flags
        return out

    return _validate


# ------------------------------------------------------------------ one candidate
class Call(Protocol):
    """One gateway call for the candidate: ``complete(role, messages, purpose=..., entity_id=..., validate=...,
    model=..., extra_body=..., use_cache=...)``, the run's id and cap already bound (the runner)."""

    def __call__(
        self,
        role: str,
        messages: list[dict[str, str]],
        *,
        purpose: str,
        entity_id: str,
        validate: Callable[[Any], Any],
        model: str | None,
        extra_body: Mapping[str, Any] | None,
        use_cache: bool,
    ) -> Result: ...


def complete_with_schema_retry(
    call: Call,
    role: str,
    c: Mapping[str, Any],
    validate: Callable[[Any], Any],
    *,
    model: str | None,
    counts: Counter[str],
    extra_body: Mapping[str, Any] | None = None,
    purpose: str = PURPOSE,
) -> Result:
    """The old ``_complete_with_schema_retry``: a malformed / schema-invalid reply is retried exactly once (uncached).
    ``attempts`` on the returned result counts model calls (1 or 2); usd and latency cover both."""
    kw: dict[str, Any] = {
        "purpose": purpose,
        "entity_id": "inbox:" + str(c["id"]),
        "validate": validate,
        "model": model,
        "extra_body": extra_body,
    }
    msgs = rules.messages_for(dict(c))
    first = call(role, msgs, use_cache=True, **kw)
    if first.ok or first.must_stop or first.error_kind not in rules.SCHEMA_ERRORS:
        first.attempts = 1
        return first
    counts["schema_retry_" + role.lower()] += 1
    second = call(role, msgs, use_cache=False, **kw)
    second.usd = round(second.usd + first.usd, 8)
    second.latency_ms += first.latency_ms
    second.attempts = 2
    return second


@dataclass(frozen=True)
class Stop:
    """The gateway refused in a way that would repeat (``STOP_KINDS``): the run stops BEFORE this candidate's write."""

    kind: str
    error: str

    @property
    def text(self) -> str:
        return f"{self.kind}: {self.error}"


@dataclass(frozen=True)
class Skipped:
    """The skip rule: the current proposal still matches (no call)."""


def skip(prev: Any, input_sha: str, mdl: str, veto_model: str | None, veto_mode: str) -> bool:
    """The old skip rule (``force`` off): a ``proposed`` proposal with the same input and the same models / mode."""
    return (
        isinstance(prev, Mapping)
        and prev.get("status") == "proposed"
        and prev.get("input_sha") == input_sha
        and (
            prev.get("stage") == "stage0"
            or (
                prev.get("model") == mdl and prev.get("veto_model") == veto_model and prev.get("veto_mode") == veto_mode
            )
        )
    )


def triage_one(
    c: Mapping[str, Any],
    prev: Any,
    *,
    call: Call,
    mdl: str,
    run_id: str,
    proposed_at: str,
    counts: Counter[str],
    model: str | None = None,
    veto_model: str | None = VETO_MODEL,
    veto_thinking: bool = False,
    force: bool = False,
) -> dict[str, Any] | Stop | Skipped:
    """The old loop body for one candidate: the entry to store, ``Stop`` or ``Skipped``. ``c`` is the old-shaped
    record (``ranking_input``); ``prev`` its current proposal record (or None); ``proposed_at`` the old
    ``ledger.now_ts()``."""
    veto_mode = "thinking" if veto_thinking else "no_thinking"
    card_text = card.candidate_card(c)
    input_sha = card.sha(PROMPT_VERSION + "\n" + card_text)
    if not force and skip(prev, input_sha, mdl, veto_model, veto_mode):
        counts["skipped_unchanged"] += 1
        return Skipped()
    entry: dict[str, Any] = {
        "candidate_id": c["id"],
        "name": c.get("name"),
        "tier": c.get("discovery_tier"),
        "source_id": c.get("source_id"),
        "prompt_version": PROMPT_VERSION,
        "input_sha": input_sha,
        "run_id": run_id,
        "proposed_at": proposed_at,
        "attention_gate": attention.gate(c),  # protected gate, recorded as a signal only
    }
    if isinstance(prev, Mapping) and prev.get("prompt_version") != PROMPT_VERSION:
        entry["previous"] = {k: prev.get(k) for k in ("prompt_version", "stage", "proposal", "model", "reasons")}
    junk = rules.stage0_junk(dict(c))
    if junk:
        entry.update(
            {
                "stage": "stage0",
                "status": "proposed",
                "proposal": "REJECT",
                "reject_basis": "NOT_AN_ENTITY",
                "reasons": [junk],
                "model": None,
                "usd": 0.0,
                "path": "stage0 junk",
            }
        )
        counts["stage0_reject"] += 1
        return entry
    validate = validator_for(card_text, c)
    res = complete_with_schema_retry(call, "CHEAP", c, validate, model=model, counts=counts)
    if res.must_stop:
        return Stop(res.error_kind, res.error)
    entry.update(
        {
            "stage": "stage1",
            "model": res.model,
            "veto_model": veto_model,
            "veto_mode": veto_mode,
            "provider": res.provider,
            "usd": res.usd,
            "cached": res.cached,
            "latency_ms": res.latency_ms,
            "call_id": res.call_id,
            "schema_retry": res.attempts > 1,
        }
    )
    if not res.ok and res.error_kind in rules.SCHEMA_ERRORS:
        # schema still broken after one retry: no machine label, no reject — a human looks at it
        entry.update(
            {
                "status": "needs_human",
                "proposal": "RESEARCH",
                "route": "HUMAN_REVIEW",
                "error_kind": res.error_kind,
                "error": res.error,
                "path": "schema failure after retry — routed to human review",
            }
        )
        counts["schema_failure_human"] += 1
    elif not res.ok:
        entry.update({"status": "error", "proposal": None, "error_kind": res.error_kind, "error": res.error})
        counts["stage1_error"] += 1
    else:
        entry.update({"status": "proposed", **res.data, "path": "stage1"})
        if res.data["proposal"] == "REJECT" and veto_model:
            counts["veto_calls"] += 1
            v = complete_with_schema_retry(
                call,
                "STANDARD",
                c,
                validate,
                model=veto_model,
                counts=counts,
                extra_body=None if veto_thinking else rules.NO_THINKING,
                purpose=VETO_PURPOSE,
            )
            if v.must_stop:
                return Stop(v.error_kind, v.error)
            second = v.data if v.ok else None
            final, path = rules._combine(res.data, second, "" if v.ok else f"{v.error_kind}")
            veto: dict[str, Any] = {
                "model": v.model,
                "mode": veto_mode,
                "ok": v.ok,
                "error_kind": v.error_kind or None,
                "usd": v.usd,
                "latency_ms": v.latency_ms,
                "schema_retry": v.attempts > 1,
            }
            if second:
                veto.update(
                    {
                        k: second.get(k)
                        for k in (
                            "proposal",
                            "model_proposal",
                            "reject_basis",
                            "reject_evidence",
                            "reasons",
                            "confidence",
                            "flags",
                        )
                    }
                )
            entry.update(
                {
                    "proposal": final,
                    "path": path,
                    "stage": "veto",
                    "usd": round(res.usd + v.usd, 8),
                    "latency_ms": res.latency_ms + v.latency_ms,
                    "veto": veto,
                }
            )
            counts["veto_" + ("confirmed" if final == "REJECT" else "overruled")] += 1
        counts["final_" + str(entry["proposal"]).lower()] += 1
    return entry


def run_summary(
    *,
    run_id: str,
    mdl: str,
    veto_model: str | None,
    veto_thinking: bool,
    finished: str,
    selected: int,
    counts: Counter[str],
    usd: float,
    run_cap_usd: float,
    override_reason: str | None,
    stopped: str,
) -> dict[str, Any]:
    """The old ``runs[]`` summary."""
    veto_mode = "thinking" if veto_thinking else "no_thinking"
    return {
        "run_id": run_id,
        "started_model": mdl,
        "veto_model": veto_model,
        "veto_mode": veto_mode,
        "prompt_version": PROMPT_VERSION,
        "system_prompt_sha256": rules.system_prompt_sha(),
        "locked_v3": mdl == LOCKED_V3["cheap_model"]
        and veto_model == LOCKED_V3["veto_model"]
        and veto_thinking == LOCKED_V3["veto_thinking"]
        and LOCKED_V3["prompt_version"] == PROMPT_VERSION,
        "finished": finished,
        "selected": selected,
        "counts": dict(counts),
        "usd": usd,
        "run_cap_usd": run_cap_usd,
        "override_reason": override_reason,
        "stopped": stopped or None,
    }
