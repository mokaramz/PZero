"""Triage review read side (old ``services/triage_review.py::view`` and the pure rules it calls), ported verbatim.

* ``routing`` — operating-queue routing (old ``domain/routing.py``)
* ``entity_repair`` — entity-name repair, with the headline extractor it reuses (old ``domain/entity_repair.py`` and
  ``connectors.extract_company`` / ``_valid_company``)
* ``portfolio_check`` — the Project A portfolio / relationship / conflict lookup (old ``domain/portfolio_check.py``)
* ``card`` — the candidate card the triage models saw, its hash, and the locked v3 architecture constants
* ``view`` — ``GET /api/deal-flow/triage``: the old ``GET /api/triage`` payload, built from ``pz``
* ``decide`` / ``log`` — the operator's accept / override / batch reject and the decision log (review 035a)
* ``cascade_rules`` / ``cascade`` — the cascade (review 035b): the pure rules cut by script (the sha-pinned prompt,
  Stage 0, the reject support, the veto repair and combination) and the hand-ported validator and one candidate's
  calls
* ``runner`` / ``records`` — one runner run over the gateway with a short locked write per candidate, and the
  stored state (the run lock, the runs, the dispositions, the retry state)
* ``auto_rules`` / ``auto`` — automatic triage after a scan, the hourly retry and Retry now (the cut retry items and
  summary sentence; the selection, recovery and the triggers)
"""
