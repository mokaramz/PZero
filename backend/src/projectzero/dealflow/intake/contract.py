"""The intake contract: validation of external submissions and of entities passed by trusted in-process callers.

Two entry points share one entity definition (``contracts/intake_submission.schema.json#/$defs/entity``):

* external callers (Grok via the CLI, the operator's paste via HTTP) send the full envelope and may assert only the
  origins in ``EXTERNAL_ORIGINS``;
* trusted callers (registry connectors, research jobs, the legacy importer) never build an envelope: the service sets
  their origin server-side, but each entity is validated exactly like an external one.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from projectzero.core.paths import CONTRACTS_DIR
from projectzero.dealflow.ranking.tagging import interstitial_check_text, is_interstitial

CONTRACT_VERSION = "1.0"
SCHEMA_PATH = CONTRACTS_DIR / "intake_submission.schema.json"


class Origin(StrEnum):
    GROK = "grok"
    MANUAL = "manual"
    REGISTRY_SCAN = "registry_scan"
    RESEARCH = "research"
    EVENT_DEBRIEF = "event_debrief"  # startup leads met at an event (review 016), set server-side
    LEGACY_SCOUT00 = "legacy_scout00"
    LEGACY_NATIVE = "legacy_native"
    LEGACY_DEALFLOW = "legacy_dealflow"


EXTERNAL_ORIGINS: frozenset[Origin] = frozenset({Origin.GROK, Origin.MANUAL})
TRUSTED_ORIGINS: frozenset[Origin] = frozenset(Origin) - EXTERNAL_ORIGINS


@dataclass(frozen=True, order=True)
class Issue:
    """One validation problem, addressed by a JSON-pointer-like path ("$" is the document root)."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


@cache
def _schema() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


@cache
def _envelope_validator() -> Draft202012Validator:
    return Draft202012Validator(_schema(), format_checker=FormatChecker())


@cache
def _entity_validator() -> Draft202012Validator:
    schema = _schema()
    entity_schema = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/entity"}
    return Draft202012Validator(entity_schema, format_checker=FormatChecker())


def _issues(errors: Iterable[ValidationError], prefix: str = "$") -> list[Issue]:
    found = []
    for error in errors:
        path = "/".join(str(part) for part in error.absolute_path)
        found.append(Issue(f"{prefix}/{path}" if path else prefix, error.message))
    return sorted(set(found))


def cross_entity_issues(entities: Sequence[Any], already_refused: Collection[int] = ()) -> dict[int, list[Issue]]:
    """Rules JSON Schema can't express. Returns NEW issues keyed by entity index.

    ``already_refused`` are entities the caller has refused for their own structure (schema issues). The result is a
    closed accepted set: after applying it, every link of every accepted entity resolves to another accepted entity.

    1. Structure first: only mappings with a string ``external_id`` hold an id, and only string references are
       followed. Malformed values never raise; the schema reports them on their entity.
    2. ``external_id`` is unique within a delivery among entities that are not refused: the first holder wins, later
       holders are refused (two entities claiming one strong identifier).
    3. References are checked against the accepted holders only, and refusal propagates to a fixed point: if C is
       refused, B -> C is refused, then A -> B is refused. Unrelated entities and valid linked groups stay eligible.
    """
    refused: set[int] = set(already_refused)
    found: dict[int, list[Issue]] = {}

    def refuse(index: int, issue: Issue) -> None:
        refused.add(index)
        found.setdefault(index, []).append(issue)

    def own_id(index: int) -> str | None:
        entity = entities[index]
        value = entity.get("external_id") if isinstance(entity, Mapping) else None
        return value if isinstance(value, str) else None

    def references(index: int) -> list[tuple[int, str]]:
        entity = entities[index]
        related = entity.get("related_external_ids") if isinstance(entity, Mapping) else None
        if not isinstance(related, list):
            return []
        return [(position, ref) for position, ref in enumerate(related) if isinstance(ref, str)]

    # 2. unique ids among the entities still eligible
    holder: dict[str, int] = {}
    for index in range(len(entities)):
        if index in refused or (external_id := own_id(index)) is None:
            continue
        if external_id in holder:
            refuse(
                index,
                Issue(
                    f"$/entities/{index}/external_id",
                    f"external_id '{external_id}' is already used by entity {holder[external_id]}",
                ),
            )
        else:
            holder[external_id] = index

    # every id ever claimed in the delivery, to tell "refused target" from "missing target" in messages
    claimed: dict[str, int] = {}
    for index in range(len(entities)):
        if (external_id := own_id(index)) is not None:
            claimed.setdefault(external_id, index)

    # 3. self-references, then propagate refusals until no accepted entity links outside the accepted set
    for index in range(len(entities)):
        if index in refused:
            continue
        for position, ref in references(index):
            if ref == own_id(index):
                refuse(
                    index,
                    Issue(f"$/entities/{index}/related_external_ids/{position}", "an entity cannot reference itself"),
                )

    changed = True
    while changed:
        changed = False
        for index in range(len(entities)):
            if index in refused:
                continue
            for position, ref in references(index):
                target = holder.get(ref)
                if target is not None and target not in refused:
                    continue
                if ref not in claimed:
                    problem = f"references external_id '{ref}', which no entity in this delivery has"
                else:
                    problem = (
                        f"references external_id '{ref}', whose entity {holder.get(ref, claimed[ref])} was refused"
                    )
                refuse(index, Issue(f"$/entities/{index}/related_external_ids/{position}", problem))
                changed = True
                break
    return found


COMPANY_KINDS = frozenset({"company", "opportunity"})


def content_issues(entity: Any, *, prefix: str = "$") -> list[Issue]:
    """Rules on what an entity SAYS (review 007). A company / opportunity whose name and key fact read like page
    plumbing (cookie banner, consent page, bot check, login wall) is refused with the reason. The old scan dropped
    such records silently; the text tested is the old one: ``(name[:120] + " " + key_fact[:600])[:400]``."""
    if not isinstance(entity, Mapping):
        return []
    kind = entity.get("kind")
    if not isinstance(kind, str) or kind not in COMPANY_KINDS:  # a list / object kind is unhashable: schema reports it
        return []
    name, key_fact = entity.get("name"), entity.get("key_fact")
    if not isinstance(name, str) or not isinstance(key_fact, (str, type(None))):
        return []  # the schema reports malformed values
    if is_interstitial(interstitial_check_text(name.strip(), key_fact or "")):
        return [Issue(prefix, "reads like a cookie banner, consent page, bot check or login wall, not a company")]
    return []


def validate_external(payload: Any) -> list[Issue]:
    """Issues for an external submission; an empty list means it may be accepted."""
    if isinstance(payload, dict):
        origin = payload.get("origin")
        if isinstance(origin, str) and origin in {o.value for o in TRUSTED_ORIGINS}:
            return [
                Issue(
                    "$/origin",
                    f"origin '{origin}' is server-side only; external callers may assert "
                    + " or ".join(sorted(o.value for o in EXTERNAL_ORIGINS)),
                )
            ]
    issues = _issues(_envelope_validator().iter_errors(payload))
    if issues:
        return issues
    entities = payload["entities"]
    content = [i for index, e in enumerate(entities) for i in content_issues(e, prefix=f"$/entities/{index}")]
    cross = cross_entity_issues(entities)
    return sorted(content + [issue for index in sorted(cross) for issue in cross[index]])


def validate_entity(entity: Any, *, prefix: str = "$") -> list[Issue]:
    """Issues for one entity, using the same rules as entities inside an external submission."""
    return _issues(_entity_validator().iter_errors(entity), prefix) + content_issues(entity, prefix=prefix)


def canonical_sha256(document: Any) -> str:
    """Stable fingerprint of a JSON document: key order and insignificant whitespace do not change it."""
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
