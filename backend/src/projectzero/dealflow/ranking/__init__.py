"""Deal Flow ranking — the PROTECTED Taste Map attention rules, ported from Project Zero v2 (revision 6c739b9).

Behaviour is byte-for-byte that of the old modules (``domain/themes.py``, ``domain/attention.py``,
``domain/feedback.py`` read path, ``connectors.norm_company``, ``radar.slug``), verified by the v1 golden fixtures
and by ``ops/parity_ranking`` against the old code on the real snapshot (review 006).

Rules here change ONLY with Mohamed's explicit approval, recorded in ``docs/decisions/``. Anything that looks odd —
including the legacy text building in ``pytext`` — is part of the scores and stays as it is.
"""
