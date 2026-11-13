-- Review 035a: machine triage, part 1 — the operator's decision log (accept / override / batch reject).
--
-- The old app appended one line per decision to `triage_decisions.jsonl` (`json.dumps(entry, sort_keys=True)`). The
-- imported file stays the byte-exact archive (`legacy_documents`); nothing is backfilled. Every reader takes the
-- archived lines FIRST, then these rows `order by seq` (the triage view's verdicts and calibration, Validation).
--
-- * triage_decisions: ONE row per old line, append-only (UPDATE and DELETE refused). `entry` is the old line with its
--   keys sorted, kept as `json` (not jsonb) so the text is byte-kept. `candidate_id` is the survivor the decision was
--   applied to (the entry's own `candidate_id` stays as recorded); `seq` is the explicit insertion order.
-- No lock or setting here names the schema.
create table pz.triage_decisions (
  seq               bigint generated always as identity primary key,
  candidate_id      text not null references pz.candidates (id),
  recorded_at       timestamptz not null default now(),
  entry             json not null check (json_typeof(entry) = 'object')
);
create index triage_decisions_candidate_idx on pz.triage_decisions (candidate_id, seq);
create trigger triage_decisions_no_update before update on pz.triage_decisions
  for each row execute function pz.forbid_mutation();
create trigger triage_decisions_no_delete before delete on pz.triage_decisions
  for each row execute function pz.forbid_mutation();

alter table pz.triage_decisions enable row level security;
revoke all on pz.triage_decisions from public, anon, authenticated;
