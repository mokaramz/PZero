"""The Network context (people, review 013): the person identity rules, the people read model and the people writes.

* ``identity`` — the person key ``fold`` and the profile / identifier rules (review 012);
* ``people`` — reading a row (``record_of``) and the ONE mapping of a record onto the columns and identifiers;
* ``view`` — the old ``/api/people``, ``/api/graph`` and ``/api/watchlist`` bodies (pure, the clock a parameter);
* ``edits`` — the write rules (``person_save``, the "3 most talented" ritual, the signal log) and the deliberate
  changes from the old code (decisions a and b, the deferred Founder Radar rename);
* ``store`` — the one people reader (``load_people``, Conviction's IMQ inputs use it too) and the transactional writes.

**People write model (review 012).** ``people.legacy`` is the imported ``people.json`` record and is never changed.
``people.attrs.record`` holds the WHOLE current record in the old ``people.json`` shape once the new app has written the
person (the same rule as ``conviction_entries.attrs.record``); until then ``legacy`` is the record. The columns
(``name``, ``normalized_name``, ``country``, ``identity_status``, ``founder_status``, ``radar_state``), the flattened
``attrs`` and ``person_identifiers`` mirror the current record on every write; every write appends a
``person_events`` row. Readers use ``people.record_of``.
"""
