-- Review 026b: Founder Radar part 2 (the founder scan and company research). The runs write the people (through the
-- Network write model), the research records (0016), and the radar documents kept as `documents` rows (the cursor,
-- the health, the metrics and the research queue); each changed record or document is one radar_events row.
alter table pz.radar_events drop constraint radar_events_entity_check;
alter table pz.radar_events add constraint radar_events_entity_check
  check (entity in ('company', 'research', 'metrics', 'document'));

alter table pz.radar_events drop constraint radar_events_action_check;
alter table pz.radar_events add constraint radar_events_action_check
  check (action in ('action', 'import', 'company', 'promote', 'boardy', 'pair', 'review', 'refs', 'snapshot',
                    'scan', 'research'));
