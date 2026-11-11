# 0001 — Same company name from two different scouts merges automatically

Date: 2026-11-11 · Decided by: Mohamed (owner) · Status: accepted

## Context
The approved identity rule (review 001) treated a name-only match as too weak to merge: it created separate companies
and a merge suggestion for the operator. The real data showed that this hides exactly the convergence the merged
Deal Flow exists to surface. Kontext, Elvio Robotics and RhymeQ were each found by both Deal Flow and Scout Intake,
and Bleu Robotics by both Scout Intake and Native Scout.

## Decision
A record with no strong-identifier match **joins** an existing company when all of these hold:
1. its normalised name equals that company's normalised name;
2. it is the **only** company with that name (no ambiguity);
3. the record comes from a **different origin** than every record already on that company
   (Deal Flow, Scout Intake, Native Scout, Conviction; later Grok, registry scan, manual);
4. there is **no conflicting strong identifier**, i.e. no different value for the same kind and namespace (two
   different domains, two different DUNS numbers, …).

Open candidates of the joined company then merge into one candidate, as with any shared company. The merge event
records `basis: same_name_cross_origin`, and every old id keeps resolving.

Everything else stays a **suggestion**: a same-origin duplicate (e.g. two Deal Flow records called "Namespace"), an
ambiguous name, or a conflict.

## Consequences
- Cross-scout convergence appears as one candidate with several origins, instead of two cards and a suggestion.
- Risk: two genuinely different companies with an identical name, found by different scouts, and with no
  conflicting identifiers on record. Mitigation: the merge is recorded, so the operator can see why it happened, and
  the candidate keeps every observation per origin. A future "split" action can undo it from that record.
- The live intake resolver (Grok deliveries, registry scans) applies the same rule.
