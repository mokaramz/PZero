"""Ecosystems (review 022): the city view, the city registry, coverage and adopting a candidate watcher.

A mechanical port of the old ``domain/ecosys.py`` (city registry, city page) and ``domain/coverage.py`` at revision
6c739b9. Pure functions over explicit inputs; the database / route layer loads the inputs and performs the one write.

Modules:

* ``catalog``  constants cut by script (``scripts/gen_ecosystems_catalog.py``) from the old modules: ``CITIES``,
  ``ORGS``, ``CITY_NOTES``, the coverage families / states / labels / thresholds / registries, the Founder Radar
  ``DEFAULT_REGIONS`` / ``RADAR_DEFAULT_SOURCES`` / ``SOURCES_SCHEMA``.
* ``cities``   ``registry(eco_doc)``, ``city_of(loc)``,
  ``city_registry(signals, events, people, eco_doc, today) -> dict`` (``GET /api/ecosystems/registry``) and
  ``eco_view(city, signals, events, people, eco_doc, today) -> dict`` (``GET /api/ecosystems/eco?city=``; the old
  route used ``"Karlsruhe"`` for an empty city). ``signals``: the Conviction records (old ``real_data.json``
  ``signals``); ``events``: the Events LISTING (``events.engine.listing(records, today, source_city, pins)``);
  ``people``: the person records; ``eco_doc``: the ``ecosystems.json`` body or ``None``; ``today``: the Berlin day.
* ``inputs``   ``CoverageInputs`` (frozen): ``sources`` (the normalized Deal Flow registry list,
  ``dealflow.sources.normalize.load_registry(stored)["sources"]``), ``event_health``, ``radar_regions``,
  ``radar_sources``, ``radar_health``, ``inbox`` / ``signals`` / ``people`` / ``events`` (records, in the old file
  order), ``coverage_sources`` / ``coverage_adopted`` / ``coverage_registry`` / ``coverage_candidates`` /
  ``ecosystems_doc`` (document bodies or ``None``), ``adoptions`` (``coverage_adoptions`` rows ``{candidate_id,
  source_id, families, countries, cities, note, by, adopted_at}``, by ``adopted_at``), and the shipped
  ``candidate_files`` / ``audit_files`` (defaults: ``resources/coverage``). ``merged_overrides(inputs)`` /
  ``merged_adoptions(inputs)``: the imported baseline overlaid by the rows (plan revision 2).
* ``coverage`` ``coverage_view(inputs, now) -> dict`` (``GET /api/ecosystems/coverage``), and its parts
  (``ecosystems``, ``declared_sources``, ``candidate_sources``, ``records_by_place``, ``family_state``, ...).
* ``adopt``    ``adopt_plan(inputs, candidate_id, confirm) -> AdoptDecision`` (``POST .../coverage/adopt``):
  ``response`` (the old body, HTTP 200) and, only for a real adoption (``writes``), ``source`` (the new Deal Flow
  source record), ``declaration`` ``{families, countries, cities, note}``, ``candidate_id``, ``source_id`` and
  ``by``. ``with_adoption(inputs, decision, adopted_at) -> CoverageInputs`` applies it in memory.
"""
