-- Review 029a: the inference gateway core (no live call). The ledger the budget rules read, the per-attempt
-- reservations, and the response cache.
--
-- * model_ledger keeps every row it has (append-only). `usd` is widened to numeric(14, 8): imported rows keep their
--   imported values; new rows keep the old 8-decimal costs. The fields the budget filters on are promoted from
--   `detail` as STORED generated columns, so no existing row is updated: role, run_id, call_id, attempt, error_kind.
--   A unique (call_id, attempt) where call_id is not null makes settlement idempotent (one debit per attempt; the
--   imported rows have no `attempt` and stay outside it).
-- * model_reservations: one row per admitted attempt, until it is settled (deleted in the settlement's transaction) or
--   reconciled after `expires_at` into an `abandoned` ledger row charged its estimate. Mutable by design.
-- * model_cache: the response cache (no TTL, as before); it starts empty.
alter table pz.model_ledger alter column usd type numeric(14, 8);
alter table pz.model_ledger add column role text generated always as (detail ->> 'role') stored;
alter table pz.model_ledger add column run_id text generated always as (detail ->> 'run_id') stored;
alter table pz.model_ledger add column call_id text generated always as (detail ->> 'call_id') stored;
alter table pz.model_ledger add column attempt integer generated always as ((detail ->> 'attempt')::integer) stored;
alter table pz.model_ledger add column error_kind text generated always as (detail ->> 'error_kind') stored;
create unique index model_ledger_call_attempt_idx on pz.model_ledger (call_id, attempt) where call_id is not null;
create index model_ledger_role_at_idx on pz.model_ledger (role, at);
create index model_ledger_entity_idx on pz.model_ledger (entity_ref);
create index model_ledger_run_idx on pz.model_ledger (run_id);

create table pz.model_reservations (
  call_id           text not null check (call_id <> ''),
  attempt           integer not null check (attempt > 0),
  role              text not null,
  purpose           text not null,
  provider          text,
  model             text,
  entity_ref        text,
  run_id            text,
  usd_estimate      numeric(14, 8) not null check (usd_estimate >= 0),
  reserved_at       timestamptz not null,
  expires_at        timestamptz not null,
  detail            jsonb not null default '{}',        -- what an abandoned row keeps (prompt / request sha)
  primary key (call_id, attempt),
  check (expires_at > reserved_at)
);
create index model_reservations_expires_idx on pz.model_reservations (expires_at);

create table pz.model_cache (
  key               text primary key check (key ~ '^[0-9a-f]{64}$'),
  provider          text not null,
  model             text not null,
  text              text not null,
  stored_at         timestamptz not null default now()
);

alter table pz.model_reservations enable row level security;
alter table pz.model_cache enable row level security;
revoke all on pz.model_reservations, pz.model_cache from public, anon, authenticated;
