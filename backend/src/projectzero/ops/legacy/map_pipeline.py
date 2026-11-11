"""Mappers for the Deal Flow pipeline: sources, Conviction, Deal Flow, merging, companies."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from projectzero.dealflow.identity import company_domain
from projectzero.dealflow.ranking.names import slug as company_slug
from projectzero.dealflow.sources.registry import country_code, registry_value
from projectzero.ops.legacy.companies import StrongKey
from projectzero.ops.legacy.convert import (
    DEALFLOW_STATUS,
    OPEN_STATUSES,
    STATUS_RANK,
    day,
    records,
    stable_uuid,
    str_list,
    text_or_none,
    timestamp,
)
from projectzero.ops.legacy.state import (
    BuilderState,
    _Candidate,
)


def verified_flags(value: Any) -> dict[str, bool]:
    """The old per-claim verification record; anything that is not one reads as nothing verified (never as all)."""
    if not isinstance(value, dict):
        return {}
    return {str(k): v for k, v in value.items() if isinstance(v, bool)}


class PipelineMapper(BuilderState):
    # ── sources ─────────────────────────────────────────────────────────────────────────────────────────────────
    def sources(self) -> None:
        for s in records((self.src.json("sources.json", {}) or {}).get("sources")):
            promoted = {
                "id",
                "name",
                "url",
                "kind",
                "parser",
                "enabled",
                "geo_scope",
                "sectors",
                "reliability",
                "last_scan",
                "last_ok",
                "failures_in_row",
            }
            reliability = s.get("reliability")
            self.t["sources"].append(
                {
                    "id": s["id"],
                    "name": s.get("name") or s["id"],
                    "url": s.get("url"),
                    "kind": s.get("kind") or "unknown",
                    "parser": s.get("parser"),
                    "enabled": bool(s.get("enabled", True)),
                    "country": country_code(s),
                    "geo_scope": s.get("geo_scope") if isinstance(s.get("geo_scope"), str) else None,
                    "sectors": str_list(s.get("sectors")),
                    "reliability": reliability
                    if isinstance(reliability, int | float) and not isinstance(reliability, bool)
                    else None,
                    "last_scan_at": timestamp(s.get("last_scan")),
                    "last_ok_at": timestamp(s.get("last_ok")),
                    "failures_in_row": int(s.get("failures_in_row") or 0),
                    "attrs": {k: v for k, v in s.items() if k not in promoted},
                    "legacy": s,
                }
            )
            self.source_ids.add(s["id"])

    def _source_ref(self, source_id: Any, name: Any = None) -> str | None:
        """A source id usable as a foreign key; unknown legacy ids get a disabled stub so nothing is dropped."""
        if not isinstance(source_id, str) or not source_id:
            return None
        if source_id not in self.source_ids and source_id not in self.stub_sources:
            self.stub_sources[source_id] = {
                "id": source_id,
                "name": str(name or source_id),
                "url": None,
                "kind": "legacy_stub",
                "parser": None,
                "enabled": False,
                "country": None,
                "geo_scope": None,
                "sectors": [],
                "reliability": None,
                "last_scan_at": None,
                "last_ok_at": None,
                "failures_in_row": 0,
                "attrs": {"stub": True, "reason": "referenced by legacy records, absent from sources.json"},
                "legacy": None,
            }
        return source_id

    # ── conviction ──────────────────────────────────────────────────────────────────────────────────────────────
    def conviction(self) -> None:
        signals = records((self.src.json("real_data.json", {}) or {}).get("signals"))
        seen_slugs: dict[str, str] = {}
        for s in signals:
            name = s.get("company") or ""
            slug = company_slug(name)  # the old radar.slug: deep links, case and Omar keys use it (review 010)
            if slug in seen_slugs:
                self.identity_blockers.append(
                    f"conviction entries {seen_slugs[slug]!r} and {name!r} share the slug {slug!r}: rename one first"
                )
                continue
            seen_slugs[slug] = name
            keys: list[StrongKey] = [("legacy_key", "real_data", slug)]
            if domain := company_domain(s.get("website")):
                keys.append(("domain", "", domain))
            company_id = self.book.resolve(
                seed=f"real_data:{slug}",
                name=name,
                strong_keys=keys,
                source="legacy_conviction",
                website=text_or_none(s.get("website")),
                country=country_code(s),
                location=s.get("location"),
                description=s.get("one_liner"),
            )
            promoted = {"company", "status", "verified", "scores"}
            row = {
                "id": stable_uuid(f"conviction:{slug}"),
                "company_id": company_id,  # a handle until finalize_identity()
                "_seed": f"real_data:{slug}",
                "candidate_id": None,
                "slug": slug,
                "status": s.get("status") or "new",
                "verified": verified_flags(s.get("verified")),
                "scores": s.get("scores") if isinstance(s.get("scores"), dict) else {"value": s.get("scores")},
                "attrs": {k: v for k, v in s.items() if k not in promoted},
                "legacy": s,
            }
            self.t["conviction_entries"].append(row)
        self.report["reconciliation"]["real_data.json signals"] = {
            "in": len(signals),
            "conviction_entries": len(self.t["conviction_entries"]),
        }

    # ── Deal Flow (inbox.json) ──────────────────────────────────────────────────────────────────────────────────
    def dealflow(self) -> None:
        inbox = self.src.json("inbox.json", {}) or {}
        promoted = {
            "id",
            "name",
            "decision",
            "description",
            "why",
            "sectors",
            "first_seen",
            "last_observed",
            "source_id",
            "location",
            "priority",
        }
        for c in records(inbox.get("candidates")):
            keys: list[StrongKey] = []
            for kind, value in (c.get("entity_ids") or {}).items():
                if (v := registry_value(value)) is None:
                    continue
                namespace = (
                    "gtr_org"
                    if kind == "org_id" and c.get("source_id") == "uk-gtr"
                    else (kind if kind == "duns" else f"{kind}:{c.get('source_id')}")
                )
                keys.append(("registry", namespace, v))
            company_id = self.book.resolve(
                seed=f"inbox:{c['id']}",
                name=c.get("name"),
                strong_keys=keys,
                source="legacy_dealflow",
                country=country_code(c),
                location=c.get("location"),
                description=c.get("description"),
                sectors=str_list(c.get("sectors")),
            )
            status = DEALFLOW_STATUS.get(str(c.get("decision")), "new")
            first_seen = timestamp(c.get("first_seen")) or day(c.get("date")) or self.now
            why = c.get("why")
            row = self._candidate_row(
                id=c["id"],
                company_id=company_id,
                name=c.get("name") or "UNKNOWN",
                status=status,
                legacy_status=c.get("decision"),
                origins=["legacy_dealflow"],
                primary_source_id=self._source_ref(c.get("source_id"), c.get("source")),
                priority=c.get("priority") if isinstance(c.get("priority"), int) else None,
                country=country_code(c),
                location=c.get("location") if isinstance(c.get("location"), str) else None,
                description=c.get("description"),
                why="; ".join(str_list(why)) or None,
                sectors=str_list(c.get("sectors")),
                first_seen_at=first_seen,
                last_observed_at=timestamp(c.get("last_observed")) or first_seen,
                attrs={k: v for k, v in c.items() if k not in promoted},
                legacy=c,
            )
            observations = [
                self._observation(
                    "legacy_dealflow",
                    self._source_ref(c.get("source_id"), c.get("source")),
                    first_seen,
                    c.get("source_url"),
                    c.get("raw_title") or c.get("name"),
                    {
                        "source": c.get("source"),
                        "discovery_tier": c.get("discovery_tier"),
                        "source_date": c.get("source_date"),
                    },
                )
            ]
            for seen in c.get("also_seen") or []:
                observations.append(
                    self._observation(
                        "legacy_dealflow",
                        self._source_ref(seen.get("source_id"), seen.get("source")),
                        timestamp(seen.get("first_seen")) or first_seen,
                        seen.get("url"),
                        seen.get("source"),
                        seen,
                    )
                )
            self.cands.append(_Candidate(row, "candidate", c["id"], observations))
        self.report["reconciliation"]["inbox.json candidates"] = {
            "in": len(records(inbox.get("candidates"))),
        }

    def finalize_identity(self) -> None:
        """Decide every company over the whole snapshot, then point rows at their final company (or none)."""
        self.book.finalize()
        unresolved: dict[str, int] = defaultdict(int)
        for cand in self.cands:
            seed = self._seed(cand)
            company_id = self.book.company_of(seed) if cand.row["company_id"] else None
            cand.row["company_id"] = company_id
            if company_id is None:
                cand.row["attrs"] = cand.row["attrs"] | self._identity_attrs(seed)
                unresolved[cand.row["attrs"]["identity"]] += 1
        kept = []
        for entry in self.t["conviction_entries"]:
            seed = entry.pop("_seed")
            entry["company_id"] = self.book.company_of(seed)
            if entry["company_id"] is None:
                # a Conviction entry needs a company; importing it without one would lose it, so it blocks apply
                reason = "conflicting strong identifiers" if seed in self.book.conflicted_seeds else "no usable name"
                company = entry["legacy"].get("company")
                self.identity_blockers.append(f"conviction entry {company!r} cannot be imported: {reason}")
                continue
            kept.append(entry)
        self.t["conviction_entries"] = kept
        self.report["reconciliation"]["real_data.json signals"]["conviction_entries"] = len(kept)
        self.conviction_by_company = {e["company_id"]: e for e in kept}
        self.report["reconciliation"]["unresolved_candidates"] = dict(sorted(unresolved.items()))

    @staticmethod
    def _seed(cand: _Candidate) -> str:
        return f"{'inbox' if cand.namespace == 'candidate' else cand.namespace}:{cand.legacy_id}"

    def merge_candidates(self) -> dict[str, str]:
        """Returns legacy Deal Flow id -> surviving candidate id (for triage, routing, committee)."""
        groups: dict[str, list[_Candidate]] = defaultdict(list)
        for cand in self.cands:
            company_id = cand.row["company_id"]
            if company_id and cand.row["status"] in OPEN_STATUSES:
                groups[company_id].append(cand)
        absorbed_into: dict[int, _Candidate] = {}
        for members in groups.values():
            if len(members) < 2:
                continue
            members.sort(key=lambda c: (-STATUS_RANK.get(c.row["status"], 0), c.row["first_seen_at"], c.row["id"]))
            survivor = members[0]
            for other in members[1:]:
                absorbed_into[id(other)] = survivor
        merges = 0
        alias_map: dict[str, str] = {}
        for cand in self.cands:
            survivor = absorbed_into.get(id(cand), cand)
            target = survivor.row["id"]
            reason = "own_id" if survivor is cand and cand.namespace == "candidate" else "legacy_import"
            if survivor is not cand:
                reason = "merge"
            self.t["candidate_aliases"].append(
                {"namespace": cand.namespace, "alias_id": cand.legacy_id, "candidate_id": target, "reason": reason}
            )
            if cand.namespace == "candidate":
                alias_map[cand.legacy_id] = target
            for obs in cand.observations:
                self.t["observations"].append(obs | {"candidate_id": target})
            if survivor is cand:
                if cand.namespace != "candidate":  # its own new id also resolves
                    self.t["candidate_aliases"].append(
                        {
                            "namespace": "candidate",
                            "alias_id": cand.row["id"],
                            "candidate_id": target,
                            "reason": "own_id",
                        }
                    )
                self.t["candidates"].append(cand.row)
                self._event(
                    target,
                    "imported",
                    to_status=cand.row["status"],
                    detail={
                        "namespace": cand.namespace,
                        "legacy_id": cand.legacy_id,
                        "legacy_status": cand.row["legacy_status"],
                    },
                )
                if cand.row["attrs"].get("identity") == "identity_conflict":
                    prefix = "inbox" if cand.namespace == "candidate" else cand.namespace
                    conflict = next(c for c in self.book.conflicts if c["seed"] == f"{prefix}:{cand.legacy_id}")
                    self._event(target, "identity_conflict", detail=conflict)
            else:
                merges += 1
                self.t["observations"].append(
                    self._observation(
                        cand.row["origins"][0],
                        None,
                        cand.row["first_seen_at"],
                        None,
                        cand.row["name"],
                        {"merged_record": cand.row["legacy"]},
                    )
                    | {"candidate_id": target}
                )
                self._event(
                    target,
                    "merge",
                    detail={
                        "absorbed": {
                            "namespace": cand.namespace,
                            "legacy_id": cand.legacy_id,
                            "status": cand.row["status"],
                            "legacy_status": cand.row["legacy_status"],
                        },
                    }
                    | self.book.merge_basis(self._seed(survivor), self._seed(cand)),
                )
                survivor.row["origins"] = sorted(set(survivor.row["origins"]) | set(cand.row["origins"]))
        # conviction entries point at the Deal Flow lead they were kept from (old inbox_id, through merges); otherwise
        # at the kept candidate of their company, when there is one
        for kept_entry in self.t["conviction_entries"]:
            inbox_id = kept_entry["legacy"].get("inbox_id")
            if isinstance(inbox_id, str) and inbox_id in alias_map:
                kept_entry["candidate_id"] = alias_map[inbox_id]
        for cand in self.cands:
            entry = self.conviction_by_company.get(cand.row["company_id"] or "")
            if entry and cand.row["status"] == "kept" and absorbed_into.get(id(cand)) is None:
                entry["candidate_id"] = entry["candidate_id"] or cand.row["id"]
        self.report["reconciliation"]["candidates"] = {
            "legacy_records": len(self.cands),
            "inserted": len(self.t["candidates"]),
            "merged_into_survivor": merges,
        }
        return alias_map

    def suggestion_events(self) -> None:
        by_company: dict[str, list[str]] = defaultdict(list)
        for row in self.t["candidates"]:
            if row["company_id"]:
                by_company[row["company_id"]].append(row["id"])
        emitted = 0
        for suggestion in self.book.suggestions:
            a, b = suggestion["companies"]
            for here, there in ((a, b), (b, a)):
                for candidate_id in by_company.get(here, []):
                    self._event(
                        candidate_id,
                        "merge_suggested",
                        detail={
                            "reason": "same normalised name, no shared strong identifier",
                            "normalized_name": suggestion["normalized_name"],
                            "other_company": there,
                            "other_candidates": by_company.get(there, []),
                            "other_is_conviction": there in self.conviction_by_company,
                        },
                    )
                    emitted += 1
        self.report["identity"] = {
            "companies": len(self.book.companies),
            "merge_suggestions": len(self.book.suggestions),
            "merge_suggested_events": emitted,
            "strong_key_conflicts": self.book.conflicts,
            "cross_origin_name_merges": [
                m | {"name": self.book.companies[m["company"]].name} for m in self.book.name_merges
            ],
            "merge_suggestion_detail": [
                {
                    "normalized_name": sug["normalized_name"],
                    "companies": [
                        {"id": cid, "name": self.book.companies[cid].name, "seed": self.book.companies[cid].seed}
                        for cid in sug["companies"]
                    ],
                    "reason": sug["reason"],
                }
                for sug in self.book.suggestions
            ],
        }

    # ── companies, documents ────────────────────────────────────────────────────────────────────────────────────
    def companies_rows(self) -> None:
        for c in self.book.companies.values():
            self.t["companies"].append(
                {
                    "id": c.id,
                    "name": c.name,
                    "normalized_name": c.normalized_name,
                    "website": c.website,
                    "country": c.country,
                    "location": c.location if isinstance(c.location, str) else None,
                    "lat": None,
                    "lng": None,
                    "description": c.description if isinstance(c.description, str) else None,
                    "sectors": c.sectors,
                    "attrs": {"seed": c.seed},
                }
            )
        self.t["company_identifiers"].extend(self.book.identifiers)
