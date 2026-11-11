-- Review 012: a person's `profile_urls` hold real profile pages (LinkedIn /in/, GitHub user, ORCID, OpenAlex author,
-- Scholar, X) AND other links -- the GitHub profile's `blog` field is often a personal or COMPANY site, which several
-- people can list. Only a profile names one person, so only a profile may be a strong (globally unique) identifier.
-- The new kind `url` is WEAK: unique per person only, like `alias`.
--
-- ONE statement, so it is atomic however the runner wraps it (like 0003): the ACCESS EXCLUSIVE lock is taken first
-- and held while the kind check, the generated `strength` column and the strong-unique index are replaced. No stored
-- value changes: every existing kind keeps its strength (no row can have kind 'url' before this migration), so it is
-- safe over existing rows and needs no emptiness check. The live table is still empty (the import has not run).
do $$
begin
  lock table pz.person_identifiers in access exclusive mode;
  alter table pz.person_identifiers drop constraint person_identifiers_kind_check;
  alter table pz.person_identifiers add constraint person_identifiers_kind_check
    check (kind in ('orcid', 'openalex', 'github', 'patent_inventor', 'profile_url', 'url', 'alias'));
  drop index pz.person_identifiers_strong_unique;
  alter table pz.person_identifiers drop column strength;
  alter table pz.person_identifiers add column strength text generated always as
    (case when kind in ('alias', 'url') then 'weak' else 'strong' end) stored;
  create unique index person_identifiers_strong_unique on pz.person_identifiers (kind, value)
    where strength = 'strong';
end $$;

comment on column pz.person_identifiers.kind is
  'orcid | openalex | github | patent_inventor | profile_url (a page naming one person): strong, globally unique; '
  'url (any other link, e.g. a personal or company site) | alias: weak, unique per person';
