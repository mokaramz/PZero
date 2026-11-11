"""The Events context (not ported yet; review 014 prepares the import).

* ``when`` — the old event date rules (``parse_when``, ``extract_date``, ``event_span``), ported verbatim with the clock
  as a parameter, plus ``stated`` / ``span_of`` / ``coordinate``: how the importer turns a legacy value into columns.

**Events write model (review 014).** ``events.legacy`` / ``event_leads.legacy`` are the imported ``events.json``
records and are never changed. ``attrs.record`` is reserved for the WHOLE current record in the old ``events.json``
shape once the new app writes the event or lead (the same rule as ``people`` and ``conviction_entries``); an imported
field named ``record`` stays in ``legacy`` only. The columns mirror the current record: ``start_date`` / ``start_time``
/ ``end_date`` / ``end_time`` are the dates as stated (``NULL`` time = no time stated, ``NULL`` date = not stated or not
parseable), and ``starts_at`` / ``ends_at`` the derived instants of the old ``event_span`` (``ends_at`` is EXCLUSIVE).
"""
