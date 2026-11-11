"""Pure identity decisions for live intake (decision 0001 applied one record at a time).

The legacy import judges whole name groups over a frozen snapshot. Live intake sees one new record against what is
already stored, so the same criteria become a per-record decision:

* strong identifiers owned by one company -> join it; by two or more -> conflict (no company, operator decides);
* otherwise a name match joins only if EXACTLY ONE stored company has that normalised name, none of its records come
  from the same origin family, and no strong identifier of the same kind/namespace differs;
* every other name match -> a new company plus a merge suggestion.

Origin families: a family is one scout. Grok replaces Scout 00, so legacy Scout 00 records and Grok deliveries are the
same family; registry scans continue the legacy Deal Flow scans.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

StrongKey = tuple[str, str, str]  # (kind, namespace, value)

ORIGIN_FAMILY = {
    "legacy_dealflow": "dealflow",
    "registry_scan": "dealflow",
    "legacy_scout00": "scout",
    "grok": "scout",
    "legacy_native": "native",
    "manual": "manual",
    "research": "research",
}


def origin_family(origin: str) -> str:
    return ORIGIN_FAMILY.get(origin, origin)


def strong_conflict(a: Iterable[StrongKey], b: Iterable[StrongKey]) -> StrongKey | None:
    """A key of ``b`` whose kind/namespace ``a`` holds with a different value, else None."""
    held = {(kind, namespace): value for kind, namespace, value in a}
    for kind, namespace, value in b:
        if held.get((kind, namespace), value) != value:
            return (kind, namespace, value)
    return None


@dataclass(frozen=True)
class StoredCompany:
    """What the store knows about one existing company, as far as identity is concerned."""

    id: str
    families: frozenset[str]  # origin families of every record on it ("conviction" for a Conviction entry)
    strong_keys: frozenset[StrongKey] = field(default_factory=frozenset)


Action = Literal["join", "create", "conflict", "none"]


@dataclass(frozen=True)
class Decision:
    action: Action
    company_id: str | None = None
    basis: str = ""
    suggest_with: tuple[str, ...] = ()  # same-name companies to raise a merge suggestion against
    detail: str = ""


def decide(
    *,
    family: str,
    strong_keys: list[StrongKey],
    owners: list[str],
    same_name: list[StoredCompany],
    has_usable_name: bool,
    delivery_ambiguous: bool = False,
) -> Decision:
    """``owners``: distinct companies owning any of ``strong_keys``. ``same_name``: companies with the same name.

    ``delivery_ambiguous``: another group in the same delivery has this name too, so no name-only join is safe.
    """
    if len(owners) > 1:
        return Decision(
            "conflict", basis="identity_conflict", detail=f"strong identifiers owned by {len(owners)} companies"
        )
    if owners:
        return Decision("join", owners[0], basis="strong_identifier")
    if not has_usable_name:
        return Decision("none", basis="no_company", detail="placeholder or empty name and no strong identifier")
    if delivery_ambiguous:
        return Decision(
            "create",
            basis="created",
            suggest_with=tuple(c.id for c in same_name),
            detail="several records in this delivery share this name (ambiguous)",
        )
    if len(same_name) == 1:
        other = same_name[0]
        if family in other.families:
            reason = "same origin on both sides (ambiguous)"
        elif clash := strong_conflict(other.strong_keys, strong_keys):
            reason = f"conflicting {clash[0]} identifiers"
        else:
            return Decision("join", other.id, basis="same_name_cross_origin")
        return Decision("create", basis="created", suggest_with=(other.id,), detail=reason)
    if same_name:
        return Decision(
            "create",
            basis="created",
            suggest_with=tuple(c.id for c in same_name),
            detail=f"{len(same_name)} companies share this name (ambiguous)",
        )
    return Decision("create", basis="created")


# ── a whole delivery at once (review 004 #1): no result may depend on the order of entities in the file ─────────


@dataclass(frozen=True)
class EntityFacts:
    index: int  # position in the delivery (only used to name groups deterministically)
    keys: tuple[StrongKey, ...]
    normalized_name: str | None


@dataclass(frozen=True)
class GroupPlan:
    """Entities of one delivery that are the same company, and what is already stored for it."""

    members: tuple[int, ...]  # entity indexes, ascending
    keys: tuple[StrongKey, ...]  # every strong key of the members
    stored_company: str | None  # the existing company the group's keys point at, if any
    names: frozenset[str]
    name_ambiguous: bool  # another group in this delivery shares one of its names


@dataclass(frozen=True)
class DeliveryPlan:
    groups: tuple[GroupPlan, ...]
    conflicts: dict[int, str]  # entity index -> why it is left unresolved


def plan_delivery(entities: list[EntityFacts], owner_of: dict[StrongKey, str]) -> DeliveryPlan:
    """Group a delivery's company entities by strong identity, against what is already stored.

    Nodes are the delivery's entities plus the stored companies that own any of their keys. An entity is a BRIDGE when
    the other holders of its keys fall into two or more separate groups once it is left out (e.g. its domain belongs
    to stored company A and its DUNS to stored company B, or to two other entities that share nothing else). A bridge
    joins nobody (``identity_conflict``). The rest connect through shared keys; a group holding two stored companies
    can't occur without a bridge, and is treated as a conflict for all its members if it ever does.
    """
    nodes = [f"e{e.index}" for e in entities] + sorted({f"c{c}" for c in owner_of.values()})
    holders: dict[StrongKey, list[str]] = {}
    for e in entities:
        for key in e.keys:
            holders.setdefault(key, []).append(f"e{e.index}")
    for key, company in owner_of.items():
        holders.setdefault(key, []).append(f"c{company}")
    keys_of = {f"e{e.index}": e.keys for e in entities} | {
        f"c{c}": tuple(k for k, o in owner_of.items() if o == c) for c in set(owner_of.values())
    }

    def groups_without(excluded: str | None) -> list[set[str]]:
        seen: set[str] = set()
        out = []
        for start in nodes:
            if start == excluded or start in seen:
                continue
            group, frontier = set(), [start]
            while frontier:
                node = frontier.pop()
                if node in group or node == excluded:
                    continue
                group.add(node)
                frontier.extend(o for k in keys_of[node] for o in holders.get(k, []) if o not in group)
            seen |= group
            out.append(group)
        return out

    conflicts: dict[int, str] = {}
    for e in entities:
        node = f"e{e.index}"
        neighbours = {o for k in e.keys for o in holders[k] if o != node}
        if len(neighbours) < 2:
            continue
        touched = [g for g in groups_without(node) if g & neighbours]
        if len(touched) > 1:
            conflicts[e.index] = f"its strong identifiers belong to {len(touched)} different companies"

    remaining = [n for n in nodes if not (n.startswith("e") and int(n[1:]) in conflicts)]
    plans: list[GroupPlan] = []
    for group in _regroup(remaining, keys_of, holders):
        members = tuple(sorted(int(n[1:]) for n in group if n.startswith("e")))
        if not members:
            continue
        stored = sorted(n[1:] for n in group if n.startswith("c"))
        if len(stored) > 1:  # defensive: never join two stored companies
            for m in members:
                conflicts[m] = "the group reaches two stored companies"
            continue
        by_index = {e.index: e for e in entities}
        plans.append(
            GroupPlan(
                members=members,
                keys=tuple(dict.fromkeys(k for m in members for k in by_index[m].keys)),
                stored_company=stored[0] if stored else None,
                names=frozenset(n for m in members if (n := by_index[m].normalized_name)),
                name_ambiguous=False,
            )
        )
    # Names are counted over EVERY group of the delivery, strongly matched ones included (review 004 rev 2): if one
    # Twin Labs reaches a stored company by its domain, a second, name-only Twin Labs in the same delivery has no
    # evidence of being that company, so it must not join anything by name. Strong matches themselves are unaffected.
    name_count: dict[str, int] = {}
    for plan in plans:
        for name in plan.names:
            name_count[name] = name_count.get(name, 0) + 1
    plans = [
        GroupPlan(p.members, p.keys, p.stored_company, p.names, any(name_count.get(n, 0) > 1 for n in p.names))
        for p in plans
    ]
    return DeliveryPlan(tuple(sorted(plans, key=lambda p: p.members)), conflicts)


def _regroup(
    nodes: list[str], keys_of: dict[str, tuple[StrongKey, ...]], holders: dict[StrongKey, list[str]]
) -> list[set[str]]:
    allowed = set(nodes)
    seen: set[str] = set()
    out = []
    for start in nodes:
        if start in seen:
            continue
        group, frontier = set(), [start]
        while frontier:
            node = frontier.pop()
            if node in group:
                continue
            group.add(node)
            frontier.extend(o for k in keys_of[node] for o in holders.get(k, []) if o in allowed and o not in group)
        seen |= group
        out.append(group)
    return out
