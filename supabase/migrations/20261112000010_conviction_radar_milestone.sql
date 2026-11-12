-- Review 019: the Radar funnel milestone. The first Radar composition that places an entry in the Top 10 appends
-- 'radar' to its record's q_milestones and writes ONE event, detail {source_id, legacy_credit, counted}
-- (counted = a source and no pre-fix credit: what the future Sources counters count). The write re-checks under the
-- Conviction lock; the partial unique index is the last line of defence: one Radar credit per entry, ever.
alter table pz.conviction_events drop constraint conviction_events_action_check;
alter table pz.conviction_events add constraint conviction_events_action_check
  check (action in ('create', 'save', 'status', 'radar_milestone'));

create unique index conviction_events_one_radar_milestone on pz.conviction_events (entry_id)
  where action = 'radar_milestone';
