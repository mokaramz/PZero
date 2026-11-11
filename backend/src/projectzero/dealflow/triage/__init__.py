"""Triage review read side (old ``services/triage_review.py::view`` and the pure rules it calls), ported verbatim.

* ``routing`` — operating-queue routing (old ``domain/routing.py``)
* ``entity_repair`` — entity-name repair, with the headline extractor it reuses (old ``domain/entity_repair.py`` and
  ``connectors.extract_company`` / ``_valid_company``)
* ``portfolio_check`` — the Project A portfolio / relationship / conflict lookup (old ``domain/portfolio_check.py``)
* ``card`` — the candidate card the triage models saw, its hash, and the locked v3 architecture constants
* ``view`` — ``GET /api/deal-flow/triage``: the old ``GET /api/triage`` payload, built from ``pz``
"""
