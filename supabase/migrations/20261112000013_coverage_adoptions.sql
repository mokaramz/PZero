-- Review 022: adopting a coverage candidate as a Deal Flow watcher is ONE transaction (the old code wrote three files,
-- not atomically): the source (pz.sources, attrs.record), its source_events row ('adopt') and this row, which carries
-- both the candidate's adoption (the old coverage_adopted.json) and the new source's declaration (the old
-- coverage_sources.json override). The imported documents stay the baseline, never rewritten; these rows overlay them.
create table pz.coverage_adoptions (
  candidate_id      text primary key check (candidate_id <> ''),  -- one adoption per candidate, ever
  source_id         text not null references pz.sources (id),
  families          text[] not null default '{}',
  countries         text[] not null default '{}',
  cities            text[] not null default '{}',
  note              text,
  by                text not null,                        -- 'operator'
  adopted_at        timestamptz not null default now()
);
create trigger coverage_adoptions_append_only before update or delete on pz.coverage_adoptions
  for each row execute function pz.forbid_mutation();
alter table pz.coverage_adoptions enable row level security;
revoke all on pz.coverage_adoptions from public, anon, authenticated;

alter table pz.source_events drop constraint source_events_action_check;
alter table pz.source_events add constraint source_events_action_check check (action in ('toggle', 'adopt'));
