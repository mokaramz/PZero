"""Company identity for the legacy import, decided over the WHOLE captured snapshot.

``resolve()`` only registers a record and returns a handle. Nothing is decided until ``finalize()``, so the order in
which records are read can never change the result (review 003 revisions 3 and 4).

**Phase A — strong identity (registry, domain, legacy_key).**
Records sharing a strong identifier are connected. A record is a **bridge** when the other holders of its keys fall
into two or more separate groups once the bridge itself is left out — e.g. A owns a domain, B owns a DUNS number, C
carries both. A bridge joins nobody: it stays unresolved (``identity_conflict``) and both groups keep their own
identity, exactly as review 003 #3 requires, whatever the order. All bridges are found against the full graph, then
the remaining records form the strong groups. A group whose records all have placeholder names gets no company.

**Phase B — names (decision 0001).** Strong groups sharing a normalised name are connected; a connected set merges
into one company only if its origins are pairwise disjoint and no strong identifier of the same kind/namespace
differs. Otherwise every pair gets a merge suggestion.

Company id, display name and details come from the records in a fixed priority (Conviction, Deal Flow, Scout Intake,
Native; then by id). Every record keeps its evidence for the audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from projectzero.dealflow.identity import is_placeholder_name, normalize_name
from projectzero.ops.legacy.convert import stable_uuid

StrongKey = tuple[str, str, str]  # (kind, namespace, value)
_ORIGIN_PRIORITY = {"real_data": 0, "inbox": 1, "scout_intake": 2, "native_scout": 3}


def origin_of(seed: str) -> str:
    """'inbox:4225…' -> 'inbox'. Seeds are '<legacy document>:<legacy id>'."""
    return seed.split(":", 1)[0]


def seed_rank(seed: str) -> tuple[int, str]:
    """Deterministic priority of a legacy record: Conviction, Deal Flow, Scout Intake, Native; then by id."""
    return (_ORIGIN_PRIORITY.get(origin_of(seed), 9), seed)


@dataclass
class _Record:
    seed: str
    name: str | None
    keys: tuple[StrongKey, ...]
    source: str
    details: dict[str, Any]


@dataclass
class Company:
    id: str
    name: str
    normalized_name: str | None
    seed: str  # its highest-priority record
    seeds: list[str] = field(default_factory=list)
    keys: set[StrongKey] = field(default_factory=set)
    origins: set[str] = field(default_factory=set)
    website: str | None = None
    country: str | None = None
    location: str | None = None
    description: str | None = None
    sectors: list[str] = field(default_factory=list)


class _UnionFind:
    def __init__(self, items: list[str]) -> None:
        self.parent = {i: i for i in items}

    def find(self, item: str) -> str:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)  # deterministic root

    def groups(self) -> list[list[str]]:
        out: dict[str, list[str]] = {}
        for item in self.parent:
            out.setdefault(self.find(item), []).append(item)
        return [sorted(g, key=seed_rank) for g in out.values()]


@dataclass
class CompanyBook:
    records: dict[str, _Record] = field(default_factory=dict)
    companies: dict[str, Company] = field(default_factory=dict)
    company_of_seed: dict[str, str | None] = field(default_factory=dict)
    strong_group_of: dict[str, str] = field(default_factory=dict)  # seed -> phase-A group id (its best seed)
    identifiers: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    suggestions: list[dict[str, Any]] = field(default_factory=list)
    name_merges: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    conflicted_seeds: set[str] = field(default_factory=set)
    finalized: bool = False

    # ── registration ────────────────────────────────────────────────────────────────────────────────────────────
    def resolve(
        self, *, seed: str, name: str | None, strong_keys: list[StrongKey], source: str, **details: Any
    ) -> str | None:
        """Register a record. Returns a handle (the seed), or None when it can never have a company."""
        if self.finalized:
            raise RuntimeError("resolve() after finalize(): the snapshot is already decided")
        keys = tuple(dict.fromkeys(strong_keys))
        self.records[seed] = _Record(seed, name, keys, source, details)
        if not keys and is_placeholder_name(name):
            return None
        return seed

    def company_of(self, seed: str) -> str | None:
        if not self.finalized:
            raise RuntimeError("company_of() before finalize()")
        return self.company_of_seed.get(seed)

    # ── decision ────────────────────────────────────────────────────────────────────────────────────────────────
    def finalize(self) -> None:
        seeds = sorted(self.records, key=seed_rank)
        holders: dict[StrongKey, list[str]] = {}
        for seed in seeds:
            for key in self.records[seed].keys:
                holders.setdefault(key, []).append(seed)

        bridges = {seed for seed in seeds if self._bridge_groups(seed, holders)}
        for seed in sorted(bridges, key=seed_rank):
            groups = self._bridge_groups(seed, holders)
            self.conflicts.append(
                {"seed": seed, "name": self.records[seed].name, "groups": groups,
                 "keys": [list(k) for k in self.records[seed].keys]}
            )  # fmt: skip
            self.conflicted_seeds.add(seed)
            self.evidence[seed] = {"basis": "identity_conflict", "groups": groups}
            self.company_of_seed[seed] = None

        strong = _UnionFind([s for s in seeds if s not in bridges])
        for owners in holders.values():
            kept = [s for s in owners if s not in bridges]
            for other in kept[1:]:
                strong.union(kept[0], other)

        groups = [g for g in strong.groups() if self._has_usable_name(g)]
        for group in strong.groups():
            if not self._has_usable_name(group):
                for seed in group:
                    self.company_of_seed[seed] = None
                    self.evidence[seed] = {
                        "basis": "no_company",
                        "reason": "placeholder name, no named record shares its keys",
                    }
        for group in groups:
            for seed in group:
                self.strong_group_of[seed] = group[0]
                shared = [list(k) for k in self.records[seed].keys if any(o != seed and o in group for o in holders[k])]
                self.evidence[seed] = (
                    {"basis": "strong_identifier", "matched": shared} if shared else {"basis": "own_record"}
                )
        self._names(groups)
        self.finalized = True

    def _bridge_groups(self, seed: str, holders: dict[StrongKey, list[str]]) -> list[list[str]]:
        """Groups that the other holders of ``seed``'s keys form when ``seed`` is left out (empty = not a bridge)."""
        neighbours = {o for k in self.records[seed].keys for o in holders[k] if o != seed}
        if len(neighbours) < 2:
            return []
        # connectivity of the component around seed, without seed
        component: set[str] = set()
        frontier = list(neighbours)
        while frontier:
            current = frontier.pop()
            if current in component or current == seed:
                continue
            component.add(current)
            for key in self.records[current].keys:
                frontier.extend(o for o in holders[key] if o != seed and o not in component)
        uf = _UnionFind(sorted(component))
        for owners in holders.values():
            inside = [o for o in owners if o in component]
            for other in inside[1:]:
                uf.union(inside[0], other)
        touched = [g for g in uf.groups() if neighbours & set(g)]
        return sorted(touched, key=lambda g: seed_rank(g[0])) if len(touched) > 1 else []

    def _has_usable_name(self, group: list[str]) -> bool:
        return any(not is_placeholder_name(self.records[s].name) for s in group)

    def _names(self, strong_groups: list[list[str]]) -> None:
        names_of = {
            g[0]: {
                n
                for s in g
                if not is_placeholder_name(self.records[s].name) and (n := normalize_name(self.records[s].name))
            }
            for g in strong_groups
        }
        members = {g[0]: g for g in strong_groups}
        origins = {gid: {origin_of(s) for s in g} for gid, g in members.items()}
        keys = {gid: {k for s in g for k in self.records[s].keys} for gid, g in members.items()}
        uf = _UnionFind(sorted(members))
        by_name: dict[str, list[str]] = {}
        for gid in sorted(members):
            for name in names_of[gid]:
                by_name.setdefault(name, []).append(gid)
        for gids in by_name.values():
            for other in gids[1:]:
                uf.union(gids[0], other)

        for name_group in sorted(uf.groups(), key=lambda g: seed_rank(g[0])):
            name_group.sort(key=seed_rank)
            shared = sorted(n for n in set().union(*(names_of[g] for g in name_group))
                            if sum(n in names_of[g] for g in name_group) > 1)  # fmt: skip
            problem = self._group_problem(name_group, origins, keys) if len(name_group) > 1 else None
            if len(name_group) > 1 and problem is None:
                self._make_company([s for g in name_group for s in members[g]], name_group)
                self.name_merges.append(
                    {
                        "normalized_name": " / ".join(shared),
                        "company": self.company_of_seed[name_group[0]],
                        "absorbed_groups": name_group[1:],
                        "origins": sorted(set().union(*(origins[g] for g in name_group))),
                        "basis": "same_name_cross_origin",
                    }
                )
                for gid in name_group[1:]:
                    for seed in members[gid]:
                        self.evidence[seed] = self.evidence[seed] | {"then": "same_name_cross_origin"}
                continue
            for gid in name_group:
                self._make_company(members[gid], [gid])
            for a, b in combinations(name_group, 2):
                pair = sorted(names_of[a] & names_of[b]) or shared
                self.suggestions.append(
                    {"companies": [self.company_of_seed[a], self.company_of_seed[b]],
                     "normalized_name": " / ".join(pair), "reason": problem}
                )  # fmt: skip

    @staticmethod
    def _group_problem(group: list[str], origins: dict[str, set[str]], keys: dict[str, set[StrongKey]]) -> str | None:
        for a, b in combinations(group, 2):
            if origins[a] & origins[b]:
                return "same origin on both sides (ambiguous)"
            held = {(k, ns): v for k, ns, v in keys[a]}
            for kind, namespace, value in keys[b]:
                if held.get((kind, namespace), value) != value:
                    return f"conflicting {kind} identifiers"
        return None

    def _make_company(self, seeds: list[str], strong_groups: list[str]) -> None:
        seeds = sorted(seeds, key=seed_rank)
        named = [s for s in seeds if not is_placeholder_name(self.records[s].name)]
        best = seeds[0]
        company = Company(
            id=stable_uuid(f"company:{best}"),
            name=str(self.records[(named or seeds)[0]].name).strip(),
            normalized_name=None,
            seed=best,
            seeds=seeds,
        )
        company.normalized_name = normalize_name(company.name)
        for seed in seeds:
            record = self.records[seed]
            company.origins.add(origin_of(seed))
            self._fill(company, record.details)
            for key in record.keys:
                if key not in company.keys:
                    company.keys.add(key)
                    self.identifiers.append(
                        {"company_id": company.id, "kind": key[0], "namespace": key[1], "value": key[2],
                         "source": record.source}
                    )  # fmt: skip
            self.company_of_seed[seed] = company.id
        if company.normalized_name:
            self.identifiers.append(
                {"company_id": company.id, "kind": "normalized_name", "namespace": "",
                 "value": company.normalized_name, "source": f"legacy:{origin_of(best)}"}
            )  # fmt: skip
        self.companies[company.id] = company

    # ── audit ───────────────────────────────────────────────────────────────────────────────────────────────────
    def merge_basis(self, survivor_seed: str, absorbed_seed: str) -> dict[str, Any]:
        """Why two records ended on one company: same strong group, or a cross-origin name merge."""
        same = self.strong_group_of.get(survivor_seed) == self.strong_group_of.get(absorbed_seed)
        return {
            "basis": "strong_identifier" if same else "same_name_cross_origin",
            "survivor_evidence": self.evidence.get(survivor_seed),
            "absorbed_evidence": self.evidence.get(absorbed_seed),
        }

    @staticmethod
    def _fill(company: Company, details: dict[str, Any]) -> None:
        """First non-empty value wins, in record priority order."""
        for attr in ("website", "country", "location", "description"):
            if details.get(attr) and not getattr(company, attr):
                setattr(company, attr, details[attr])
        for sector in details.get("sectors") or []:
            if sector not in company.sectors:
                company.sectors.append(sector)
