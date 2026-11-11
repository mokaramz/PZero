"""The Network context (people). Not ported yet: today it holds the shared person identity rules and the write model.

**People write model (review 012).** ``people.legacy`` is the imported ``people.json`` record and is never changed.
``people.attrs.record`` holds the WHOLE current record in the old ``people.json`` shape once the new app has written the
person (the same rule as ``conviction_entries.attrs.record``); until then ``legacy`` is the record. The columns
(``name``, ``normalized_name``, ``country``, ``identity_status``, ``founder_status``, ``radar_state``) and
``person_identifiers`` mirror the current record on every write. Readers use ``people.record_of``.
"""
