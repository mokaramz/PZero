-- Review 032c: the background-jobs runner. The old runner kept its state in four files of the data folder
-- (`schedule/jobs.json`, `runs.jsonl`, `runner.json` and the `run.lock` file); here:
--
-- * job_state (0001): one row per job, `detail` the old record whole (now with the claiming runner's `generation`).
-- * job_runs (0001): the history, append-only. An imported row has the old line's `at` as `started_at` and no
--   `finished_at`; a NEW row has its real `started_at` (the claim) and `finished_at` (the completion), and `detail` is
--   the old line whole. From here on a history row is immutable too (UPDATE refused, as DELETE already was).
-- * job_lease: ONE row, the fencing generation. The runner holds a SESSION advisory lock on a dedicated connection;
--   taking it increments `generation` (never decreasing), and every claim and completion is a transaction conditional
--   on the generation it took, so a worker whose lock connection died writes nothing more (revision 2). `holder` is
--   the last taker (source, pid, since) for the status display; whether it still holds the lock is read from pg_locks.
-- * job_runner: the old `runner.json`, one row per source (`app`, `background`, `cli`, ...), `record` kept as `json`
--   (not jsonb) so the key order survives. The readers OVERLAY these rows on the archived `schedule/runner.json` by
--   source; nothing is backfilled (the archive stays the base).
-- The lock keys are derived from the schema name at run time; no string here names the schema.
create table pz.job_lease (
  id                smallint primary key default 1 check (id = 1),
  generation        bigint not null default 0 check (generation >= 0),
  holder            json,
  taken_at          timestamptz
);
insert into pz.job_lease (id) values (1);

create or replace function pz.job_lease_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'job_lease: the lease row is never deleted';
  end if;
  if new.generation < old.generation then
    raise exception 'job_lease: the generation never decreases (% -> %)', old.generation, new.generation;
  end if;
  return new;
end $$;
create trigger job_lease_guard before update or delete on pz.job_lease
  for each row execute function pz.job_lease_guard();

create table pz.job_runner (
  source            text primary key check (source ~ '^[a-z][a-z_]{0,31}$'),
  record            json not null,                        -- the old runner.json entry whole (its key order: json)
  created_at        timestamptz not null default now(),   -- first written: a NEW source is listed in this order
  updated_at        timestamptz not null default now()
);

alter table pz.job_runs add constraint job_runs_finished_check
  check (finished_at is null or finished_at >= started_at);
create trigger job_runs_no_update before update on pz.job_runs
  for each row execute function pz.forbid_mutation();

alter table pz.job_lease enable row level security;
alter table pz.job_runner enable row level security;
revoke all on pz.job_lease, pz.job_runner from public, anon, authenticated;
revoke all on function pz.job_lease_guard() from public, anon, authenticated;
