-- Names are normalised by the application (projectzero.dealflow.identity.normalize_name), not by SQL.
--
-- Why: the v1 SQL normaliser replaced every non [a-z0-9] character with a space, so accented names lost letters
-- ("Ölwerk Süd" -> "lwerk s d") and names in non-Latin scripts normalised to NULL. Postgres lower() and character
-- classes also depend on the database collation, which the app can't control on a hosted project. One Unicode-correct
-- implementation in Python (NFKC + casefold, legal-form suffixes stripped only at the end) is the single source of truth.
--
-- Tables are empty at this point (no import has run), so dropping the generated columns loses nothing.

drop index if exists pz.companies_normalized_name_idx;
alter table pz.companies drop column normalized_name;
alter table pz.companies add column normalized_name text;
create index companies_normalized_name_idx on pz.companies (normalized_name);

drop index if exists pz.people_normalized_name_idx;
alter table pz.people drop column normalized_name;
alter table pz.people add column normalized_name text;
create index people_normalized_name_idx on pz.people (normalized_name);

drop function if exists pz.normalize_name(text);
