-- Review 010: a Conviction entry's `verified` is the old per-claim record {founders, traction, funding}, not one flag.
-- The boolean column could not hold it (the importer collapsed any non-empty record to true). The table is still
-- empty on the live project (the legacy import has not run), so the column is replaced; the migration refuses to run
-- over existing rows rather than invent flags for them.
--
-- ONE statement, so it is atomic however the runner wraps it: the ACCESS EXCLUSIVE lock is taken BEFORE the emptiness
-- check and held through the type change (Codex, H-068). A writer holding an uncommitted insert makes the migration
-- wait; once it commits, the check sees the row and the migration aborts with that row untouched.
do $$
begin
  lock table pz.conviction_entries in access exclusive mode;
  if exists (select 1 from pz.conviction_entries) then
    raise exception 'conviction_entries is not empty: convert verified by hand before applying this migration';
  end if;
  alter table pz.conviction_entries alter column verified drop default;
  alter table pz.conviction_entries alter column verified type jsonb using '{}'::jsonb;
  alter table pz.conviction_entries alter column verified set default '{}'::jsonb;
  alter table pz.conviction_entries add constraint conviction_entries_verified_is_object
    check (jsonb_typeof(verified) = 'object');
end $$;

comment on column pz.conviction_entries.verified is
  'the old per-claim verification record, e.g. {"founders": true, "traction": false, "funding": false}';
