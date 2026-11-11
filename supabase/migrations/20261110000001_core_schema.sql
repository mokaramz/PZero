-- Project Zero (optimized) — core schema v1
-- DRAFT for review (Codex). Not yet applied to the hosted project.
--
-- Design notes
-- * Everything lives in schema `pz`, which PostgREST does not expose; RLS is also enabled with no policies, and
--   anon/authenticated have no grants. Only the backend (database URL / service role) can read or write.
-- * Relational columns for what we filter, join and constrain on; JSONB (`attrs`) for evolving detail.
-- * Migrated rows keep `legacy_id` + the untouched original record in `legacy`. Nothing is dropped.
-- * Status vocabularies are CHECK constraints (cheap to evolve), not Postgres enums.

create schema if not exists pz;
revoke all on schema pz from public, anon, authenticated;

-- ── helpers ────────────────────────────────────────────────────────────────────────────────────────────────────
create or replace function pz.touch_updated_at() returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end $$;

create or replace function pz.forbid_mutation() returns trigger language plpgsql as $$
begin
  raise exception 'pz.%: rows are append-only (% refused)', tg_table_name, tg_op;
end $$;

create or replace function pz.short_id() returns text language sql volatile as $$
  select substr(replace(gen_random_uuid()::text, '-', ''), 1, 12)
$$;

create or replace function pz.normalize_name(raw text) returns text language sql immutable as $$
  -- lower-case, strip legal suffixes and punctuation; the Python resolver uses the same rule (tested for parity)
  select nullif(trim(regexp_replace(
           regexp_replace(lower(coalesce(raw, '')),
             '\m(gmbh|ag|ug|ltd|limited|inc|llc|sas|sarl|bv|nv|ab|oy|as|aps|plc|co|corp|corporation)\M', '', 'g'),
           '[^a-z0-9]+', ' ', 'g')), '')
$$;

-- ── sources ────────────────────────────────────────────────────────────────────────────────────────────────────
create table pz.sources (
  id                text primary key,                    -- legacy ids kept ('us-nih', 'legacy-48f1…')
  name              text not null,
  url               text,
  kind              text not null,
  parser            text,
  enabled           boolean not null default true,
  country           text,
  geo_scope         text,
  sectors           text[] not null default '{}',
  reliability       numeric,
  last_scan_at      timestamptz,
  last_ok_at        timestamptz,
  failures_in_row   integer not null default 0,
  attrs             jsonb not null default '{}',          -- yield, quality, queries, hwm, probation, …
  legacy            jsonb,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

-- ── companies (one identity per real-world company) ─────────────────────────────────────────────────────────────
create table pz.companies (
  id                uuid primary key default gen_random_uuid(),
  name              text not null,
  normalized_name   text generated always as (pz.normalize_name(name)) stored,
  website           text,
  country           text,
  location          text,
  lat               double precision,
  lng               double precision,
  description       text,
  sectors           text[] not null default '{}',
  attrs             jsonb not null default '{}',
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create index companies_normalized_name_idx on pz.companies (normalized_name);

-- Every way we can recognise a company. The resolver matches on these.
-- Strength decides uniqueness (review 001 #1):
--   strong  (domain, registry, legacy_key, submitter_key) — globally unique per (kind, namespace, value): one
--           registry id, company domain or submitter entity id can never belong to two companies.
--   weak    (normalized_name, alias) — unique only per company: two different companies may share a name
--           (e.g. same name, different registries) and both keep their assertion until the operator reviews it.
-- `namespace` qualifies the value: registry → 'duns' | 'handelsregister' | 'companies_house' | …;
-- legacy_key → the old document ('real_data', 'radar', 'founder_calls', 'claims', …); submitter_key → the origin
-- ('grok'), from the contract's entity `external_id`; '' when not applicable.
-- The resolver must not record shared-host domains (university, github.io, linktr.ee, …) as a company domain.
create table pz.company_identifiers (
  id                bigint generated always as identity primary key,
  company_id        uuid not null references pz.companies (id) on delete cascade,
  kind              text not null check (kind in ('domain', 'registry', 'legacy_key', 'submitter_key',
                                                   'normalized_name', 'alias')),
  namespace         text not null default '',
  value             text not null check (btrim(value) <> ''),
  strength          text generated always as
                    (case when kind in ('domain', 'registry', 'legacy_key', 'submitter_key') then 'strong'
                          else 'weak' end) stored,
  source            text,                                 -- which origin asserted it
  created_at        timestamptz not null default now(),
  check (kind not in ('registry', 'legacy_key', 'submitter_key') or namespace <> ''),
  -- last line of defence: a placeholder must never become a strong identifier shared by unrelated companies
  constraint company_identifiers_no_placeholder check (
    kind not in ('domain', 'registry', 'legacy_key', 'submitter_key')
    or lower(btrim(value)) !~ '^(none|null|nil|nan|n/?a|unknown|tbd|0+|-+|\?)$')
);
create unique index company_identifiers_strong_unique on pz.company_identifiers (kind, namespace, value)
  where strength = 'strong';
create unique index company_identifiers_per_company_unique on pz.company_identifiers (company_id, kind, namespace, value);
create index company_identifiers_lookup_idx on pz.company_identifiers (kind, namespace, value);

-- ── people ─────────────────────────────────────────────────────────────────────────────────────────────────────
create table pz.people (
  id                text primary key,                     -- legacy 'p-<slug>' kept
  name              text not null,
  normalized_name   text generated always as (pz.normalize_name(name)) stored,
  country           text,
  identity_status   text,
  founder_status    text,
  radar_state       text,
  attrs             jsonb not null default '{}',          -- provenance, evidence, profile urls, history, …
  legacy            jsonb,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create index people_normalized_name_idx on pz.people (normalized_name);

-- Same strong/weak rule as company_identifiers: registry-style ids are globally unique, aliases only per person.
create table pz.person_identifiers (
  id                bigint generated always as identity primary key,
  person_id         text not null references pz.people (id) on delete cascade,
  kind              text not null check (kind in ('orcid', 'openalex', 'github', 'patent_inventor', 'profile_url',
                                                   'alias')),
  value             text not null check (btrim(value) <> ''),
  strength          text generated always as (case when kind = 'alias' then 'weak' else 'strong' end) stored
);
create unique index person_identifiers_strong_unique on pz.person_identifiers (kind, value) where strength = 'strong';
create unique index person_identifiers_per_person_unique on pz.person_identifiers (person_id, kind, value);

create table pz.company_people (
  company_id        uuid not null references pz.companies (id) on delete cascade,
  person_id         text not null references pz.people (id) on delete cascade,
  role              text,
  confirmed         boolean not null default false,       -- provisional ≠ verified
  evidence          jsonb not null default '[]',
  primary key (company_id, person_id)
);

-- ── intake (single entry point for every origin) ───────────────────────────────────────────────────────────────
create table pz.intake_submissions (
  id                uuid primary key default gen_random_uuid(),
  origin            text not null check (origin in ('grok', 'registry_scan', 'manual', 'research',
                                                    'legacy_scout00', 'legacy_native', 'legacy_dealflow')),
  submitted_by      text not null,                        -- 'grok', 'operator', 'scheduler:deal_flow_scan', …
  external_ref      text,                                 -- e.g. Grok cycle id, scan run id
  sha256            text not null unique,                 -- same delivery twice → no-op
  contract_version  text not null,
  payload           jsonb not null,                       -- the submission exactly as received
  outcome           text not null default 'received'
                    check (outcome in ('received', 'accepted', 'partial', 'rejected')),
  outcome_detail    jsonb not null default '{}',          -- counts, per-entity results, rejection reasons
  received_at       timestamptz not null default now(),
  processed_at      timestamptz
);
create trigger intake_submissions_no_delete before delete on pz.intake_submissions
  for each row execute function pz.forbid_mutation();

-- Atomic insert-if-absent (review 001 rev 2, #2). Both intake doors call this instead of "look up, then insert":
-- under concurrent deliveries of the same sha256 exactly one caller gets inserted = true; the other waits for the
-- winner's commit (ON CONFLICT semantics) and gets the winner's id with inserted = false. Never a unique violation.
create or replace function pz.record_submission(
  p_origin text, p_submitted_by text, p_external_ref text, p_sha256 text, p_contract_version text,
  p_payload jsonb, p_outcome text, p_outcome_detail jsonb
) returns table (submission_id uuid, inserted boolean)
language plpgsql as $$
begin
  insert into pz.intake_submissions as s
         (origin, submitted_by, external_ref, sha256, contract_version, payload, outcome, outcome_detail, processed_at)
  values (p_origin, p_submitted_by, p_external_ref, p_sha256, p_contract_version, p_payload, p_outcome,
          p_outcome_detail, now())
  on conflict (sha256) do nothing
  returning s.id into submission_id;

  if submission_id is not null then
    inserted := true;
  else
    select s.id into submission_id from pz.intake_submissions s where s.sha256 = p_sha256;
    inserted := false;
  end if;
  return next;
end $$;

-- ── candidates (the merged Deal Flow item) ─────────────────────────────────────────────────────────────────────
create table pz.candidates (
  id                text primary key default pz.short_id(), -- legacy 12-hex ids kept (deep links keep working)
  company_id        uuid references pz.companies (id),
  subject_kind      text not null default 'company'
                    check (subject_kind in ('company', 'person', 'opportunity', 'event')),
  name              text not null,
  status            text not null default 'new'
                    check (status in ('new', 'reviewing', 'watch', 'baseline', 'rejected', 'archived', 'kept')),
  legacy_status     text,                                 -- original value before vocabulary unification
  origins           text[] not null default '{}',         -- every origin that has reported it
  primary_source_id text references pz.sources (id),
  priority          integer,
  country           text,
  location          text,
  description       text,
  why               text,
  key_fact          text,                                 -- from intake packets
  key_unknown       text,
  recommended_object_type text,
  sectors           text[] not null default '{}',
  first_seen_at     timestamptz not null default now(),
  last_observed_at  timestamptz not null default now(),
  decided_at        timestamptz,
  attrs             jsonb not null default '{}',          -- tier, archetype hits, twins, noise, geo, milestones, …
  legacy            jsonb,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create index candidates_status_idx on pz.candidates (status, last_observed_at desc);
create index candidates_company_idx on pz.candidates (company_id);
create index candidates_origins_idx on pz.candidates using gin (origins);
-- one open candidate per company: a re-report attaches, it never duplicates
create unique index candidates_one_open_per_company on pz.candidates (company_id)
  where company_id is not null and status not in ('rejected', 'archived');

-- Every id a candidate has ever had (review 001 #4). Each candidate gets a row for its own id; when import or
-- resolution merges candidates, the absorbed ids are re-pointed here, so old deep links and Grok references keep
-- resolving to the surviving candidate. Namespaces: 'candidate' (current ids, incl. legacy 12-hex Deal Flow ids),
-- 'scout_intake' ('si-…'), 'native_scout' ('sig-…').
create table pz.candidate_aliases (
  namespace         text not null check (namespace in ('candidate', 'scout_intake', 'native_scout')),
  alias_id          text not null,
  candidate_id      text not null references pz.candidates (id) on delete cascade,
  reason            text not null default 'own_id' check (reason in ('own_id', 'legacy_import', 'merge')),
  created_at        timestamptz not null default now(),
  primary key (namespace, alias_id)
);
create index candidate_aliases_candidate_idx on pz.candidate_aliases (candidate_id);

create or replace function pz.resolve_candidate(p_namespace text, p_id text) returns text
language sql stable as $$
  select candidate_id from pz.candidate_aliases where namespace = p_namespace and alias_id = p_id
$$;

-- Every sighting of a candidate, from any origin. Immutable.
create table pz.observations (
  id                bigint generated always as identity primary key,
  candidate_id      text not null references pz.candidates (id) on delete cascade,
  submission_id     uuid references pz.intake_submissions (id),
  origin            text not null,
  source_id         text references pz.sources (id),
  observed_at       timestamptz not null default now(),
  url               text,
  title             text,
  evidence          jsonb not null default '[]',          -- [{url, title, published_at, quote}]
  payload           jsonb not null default '{}'           -- the entity as that origin described it
);
create index observations_candidate_idx on pz.observations (candidate_id, observed_at desc);
create trigger observations_append_only before update or delete on pz.observations
  for each row execute function pz.forbid_mutation();

-- Status changes and operator/machine actions. Immutable audit trail.
create table pz.candidate_events (
  id                bigint generated always as identity primary key,
  candidate_id      text not null references pz.candidates (id) on delete cascade,
  actor             text not null,                        -- 'operator', 'machine:triage', 'grok', 'import', …
  action            text not null,                        -- 'status', 'note', 'merge', 'link', …
  from_status       text,
  to_status         text,
  reason            text,
  detail            jsonb not null default '{}',
  at                timestamptz not null default now()
);
create index candidate_events_candidate_idx on pz.candidate_events (candidate_id, at desc);
create trigger candidate_events_append_only before update or delete on pz.candidate_events
  for each row execute function pz.forbid_mutation();

-- ── triage, routing, committee (machine proposals; never decisions) ───────────────────────────────────────────
create table pz.triage_proposals (
  id                bigint generated always as identity primary key,
  candidate_id      text not null references pz.candidates (id) on delete cascade,
  run_id            text,
  prompt_version    text,
  input_sha         text,
  proposal          text not null,                        -- KEEP | RESEARCH | WATCH | REJECT
  status            text,
  model             text,
  veto_model        text,
  usd               numeric(12, 6),
  detail            jsonb not null default '{}',
  proposed_at       timestamptz not null default now(),
  is_current        boolean not null default true
);
create unique index triage_proposals_one_current on pz.triage_proposals (candidate_id) where is_current;

create table pz.candidate_routing (
  candidate_id      text primary key references pz.candidates (id) on delete cascade,
  state             text not null,                        -- NEEDS_OPERATOR, CASE_PREPARING, MACHINE_WATCH, …
  priority          integer,
  reason            text,
  detail            jsonb not null default '{}',
  updated_at        timestamptz not null default now()
);

create table pz.committee_reviews (
  id                bigint generated always as identity primary key,
  candidate_id      text not null references pz.candidates (id) on delete cascade,
  seat              text not null check (seat in ('chair', 'outside', 'second_pass')),
  model             text,
  verdict           text,
  detail            jsonb not null default '{}',
  reviewed_at       timestamptz not null default now()
);
create index committee_reviews_candidate_idx on pz.committee_reviews (candidate_id, seat);

-- ── conviction ─────────────────────────────────────────────────────────────────────────────────────────────────
create table pz.conviction_entries (
  id                uuid primary key default gen_random_uuid(),
  company_id        uuid not null unique references pz.companies (id),
  candidate_id      text references pz.candidates (id),   -- the Keep that created it (null for legacy entries)
  slug              text unique,                          -- legacy key kept for deep links
  status            text not null,                        -- new | contacted | dropped | …
  verified          boolean not null default false,
  scores            jsonb not null default '{}',
  attrs             jsonb not null default '{}',          -- thesis, bull/bear, founders, next action, findings, …
  legacy            jsonb,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

-- ── events ─────────────────────────────────────────────────────────────────────────────────────────────────────
create table pz.events (
  id                text primary key,                     -- legacy 'ev-<slug>-<date>' kept
  name              text not null,
  starts_at         timestamptz,
  ends_at           timestamptz,
  city              text,
  country           text,
  url               text,
  status            text,
  lat               double precision,
  lng               double precision,
  attrs             jsonb not null default '{}',
  legacy            jsonb,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create index events_starts_at_idx on pz.events (starts_at);

-- ── research jobs (replaces Scout Bridge; always through the capped gateway) ───────────────────────────────────
create table pz.research_jobs (
  id                uuid primary key default gen_random_uuid(),
  job_type          text not null,                        -- COMPANY_RESEARCH, VERIFY_CLAIM, …
  target_kind       text not null,
  target_id         text not null,
  status            text not null default 'queued'
                    check (status in ('queued', 'running', 'staged', 'failed', 'cancelled')),
  cost_cap_usd      numeric(10, 4) not null,
  request           jsonb not null,
  result            jsonb,
  error             text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

-- ── model spend ledger (append-only) ───────────────────────────────────────────────────────────────────────────
create table pz.model_ledger (
  id                bigint generated always as identity primary key,
  at                timestamptz not null default now(),
  purpose           text not null,
  provider          text,
  model             text,
  entity_ref        text,
  usd               numeric(12, 6) not null default 0,
  tokens_in         integer,
  tokens_out        integer,
  cached            boolean not null default false,
  outcome           text,
  detail            jsonb not null default '{}'
);
create index model_ledger_at_idx on pz.model_ledger (at desc);
create index model_ledger_purpose_idx on pz.model_ledger (purpose, at desc);
create trigger model_ledger_append_only before update or delete on pz.model_ledger
  for each row execute function pz.forbid_mutation();

-- ── scheduler ──────────────────────────────────────────────────────────────────────────────────────────────────
create table pz.job_state (
  job               text primary key,
  interval_hours    numeric not null,
  enabled           boolean not null default true,
  last_started_at   timestamptz,
  last_finished_at  timestamptz,
  last_outcome      text,
  detail            jsonb not null default '{}'
);

create table pz.job_runs (
  id                bigint generated always as identity primary key,
  job               text not null,
  started_at        timestamptz not null,
  finished_at       timestamptz,
  outcome           text,
  detail            jsonb not null default '{}'
);
create index job_runs_job_idx on pz.job_runs (job, started_at desc);
create trigger job_runs_no_delete before delete on pz.job_runs
  for each row execute function pz.forbid_mutation();

-- ── long-tail state + legacy archive ───────────────────────────────────────────────────────────────────────────
-- Small singleton documents (radar metrics, cursors, health snapshots, settings) until their context is modelled.
create table pz.documents (
  key               text primary key,
  body              jsonb not null,
  updated_at        timestamptz not null default now()
);

-- Every file of the old data folder, byte for byte (review 001 #2). `raw` is the exact file content (whitespace, key
-- order, CRLF line endings, BOM, binary formats); the database itself refuses a row whose bytes don't match the
-- recorded SHA-256 or size. `parsed` is a convenience copy for querying and is never used for restore.
-- Whole folder is ~27 MB, so every file (caches included) fits in the table; no Storage indirection.
create table pz.legacy_documents (
  path              text primary key,                     -- relative to the old data folder, forward slashes
  sha256            text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  bytes             bigint not null,
  raw               bytea not null,
  parsed            jsonb,                                -- JSON, or JSONL as an array; null for non-JSON / unparsable
  imported_at       timestamptz not null default now(),
  constraint legacy_documents_bytes_match check (octet_length(raw) = bytes),
  constraint legacy_documents_sha_match check (encode(sha256(raw), 'hex') = sha256)
);
create trigger legacy_documents_append_only before update or delete on pz.legacy_documents
  for each row execute function pz.forbid_mutation();

-- ── updated_at triggers ────────────────────────────────────────────────────────────────────────────────────────
do $$
declare t text;
begin
  foreach t in array array['sources', 'companies', 'people', 'candidates', 'conviction_entries', 'events',
                           'research_jobs', 'documents']
  loop
    execute format('create trigger %I_touch before update on pz.%I for each row execute function pz.touch_updated_at()',
                   t, t);
  end loop;
end $$;

-- ── lock it down ───────────────────────────────────────────────────────────────────────────────────────────────
do $$
declare t record;
begin
  for t in select tablename from pg_tables where schemaname = 'pz'
  loop
    execute format('alter table pz.%I enable row level security', t.tablename);
    execute format('revoke all on pz.%I from public, anon, authenticated', t.tablename);
  end loop;
end $$;
revoke all on all functions in schema pz from public, anon, authenticated;
