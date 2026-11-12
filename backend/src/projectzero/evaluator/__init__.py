"""Active Evaluator (review 024): sessions, the claim ledger, contradictions, ending a session, the why-now trigger.

A mechanical port of the old ``domain/evaluator.py``, ``api/routers/evaluator.py`` and the Founder Radar evidence
rules at revision 6c739b9. Pure functions over the evaluations DOCUMENT ``{sessions: {<id>: session}}`` (the old
``evaluations.json``: an id-keyed OBJECT whose insertion order matters — the workspace sorts its values by
``created``, stably, so ties keep the document order) plus explicit inputs. Nothing here reads or writes storage; the
DB layer loads the inputs, applies a function and writes every part of its ``Outcome`` in ONE transaction.

Modules:

* ``catalog``   constants cut by script (``scripts/gen_evaluator_catalog.py``): ``FILE_NAME``, ``STATES``,
  ``DECK_LABEL``, ``FOUNDER_LABEL``, ``UNKNOWN``, ``FAMILIES`` / ``FAM``, the patterns and ``CANONICAL_MAP``
  (``TIMING_KINDS`` stays in ``conviction.imq``).
* ``evidence``  the old ``founder_radar/evidence.py``: ``valid_activity_date(v, today)``, ``is_recent(d, today,
  window=90)``, ``add_evidence(kind, url, label, claim, field="", activity_date=None, *, now, today)`` (validates
  and returns ``{ok, row}`` / ``{ok: false, error}``; it never writes ``radar_companies.json``, decision e).
  ``conviction.imq.record_trigger(entry, kind, when, url, fact, confirm, *, now, today)`` uses it.
* ``core``      the old domain functions line for line over one session, with ``Clock(now, today, new_hex)`` for the
  old ``datetime.now()`` / ``date.today()`` / ``uuid4().hex``.
* ``routes``    the old routes, pure (below).

Inputs (keyword arguments): ``doc`` the evaluations document (``None`` / not a dict reads as ``{"sessions": {}}``,
the old ``load()``); ``conviction`` the STORED Conviction records, a list in the old ``real_data.json`` ``signals``
order (``[conviction.store.record_of(r) for r in ConvictionStore.entry_rows()]``); ``people`` the person records
(``network.store.load_people``, old ``people.json`` order; IMQ gate C); ``radar_companies`` the
``radar_companies.json`` body (``None``: missing; anything not a dict, e.g. ``conviction.inputs.UNREADABLE``: the old
unreadable file -> no research facts); ``founder_calls`` the founder_calls document (``FounderCallsStore.load()``,
``None``: none yet); ``today`` the Berlin day; ``now`` the request clock (aware, or naive Berlin wall time);
``new_hex()`` the id maker (default ``uuid4().hex``): a session id is ``ev-<YYYYmmddHHMMSS>-<new_hex()[:6]>``, a
question id ``q-<new_hex()[:8]>``, a founder-call id ``<prefix><new_hex()[:12]>``; task ids ``vt-…`` come from the
claim ids (sha1 of the family and text), as before.

Public signatures (``routes``, re-exported here):

* ``workspace(doc) -> dict`` — ``GET /api/evaluations`` (the old ``workspace()``).
* ``session_view(doc, session_id, *, conviction, people, today) -> dict | None`` — ``GET /api/evaluation?id=``
  ``{session, panel, next}``; ``None``: 404 ``{"error": UNKNOWN_SESSION}``. ``next`` includes skipped questions.
* ``start(doc, body, *, conviction, people, radar_companies, today, now, new_hex=None) -> Outcome``.
* ``deck`` / ``next_question`` / ``skip`` / ``answer`` / ``attach_evidence`` / ``resolve`` ``(doc, body, *, conviction,
  people, today, now, new_hex=None) -> Outcome``.
* ``end(doc, body, *, conviction, people, founder_calls, today, now, new_hex=None) -> Outcome``.
* ``action(act, doc, body, *, conviction, people, radar_companies=None, founder_calls=None, today, now,
  new_hex=None) -> Outcome`` — the old ``POST /api/eval_{act}`` dispatcher (incl. ``UNKNOWN_ACTION``).
* ``imq_trigger(body, *, conviction, today, now) -> TriggerOutcome`` — the old ``POST /api/imq_trigger``.

``Outcome`` (frozen): ``status`` (200), ``body`` (the old answer, ``panel`` / ``row`` included as the old router added
them), ``doc`` (the evaluations document after the request: the INPUT object when the session did not change — a
refusal that changed nothing, a repeated end, ``next`` with an open question —, else a new document; never the input
mutated; ``start`` appends the new session last), ``changed`` (the ids of the new / changed sessions), and, for
``end`` only, ``founder_calls`` (the ``founder_calls.routes.Outcome`` of the call save — its ``doc`` / ``changed``
are the founder_calls write — or ``None`` when no call was saved: no founder answer, or already ended) and
``conviction`` (``tuple[ConvictionChange, ...]``: ``index`` in the ``conviction`` list, ``slug``, the whole new
``record`` with ``verify_list`` / ``evaluator_provisional`` / ``evaluator_last``; empty when not linked).
``TriggerOutcome``: ``status`` (200), ``body`` (``{ok, trigger}`` or the old refusal ``{ok: false, error}``),
``conviction`` (the record(s) with the new ``imq_trigger``; empty on a refusal). The Conviction store persists the
IMQ snapshot on a written record as for its own writes.

Old behaviour kept (decision b): ``GET evaluation`` ``next`` includes skipped questions; ``answer`` overwrites an
answered question and adds a claim; every evidence attach appends a row; a repeated resolve overwrites; the panel's
IMQ uses only this session's open contradictions, with no research facts (the old ``imq.evaluate(e,
contradictions=...)``). Duplicate radar slugs among the Conviction records: like the old loop, ``end`` and
``imq_trigger`` change every matching record (one ``ConvictionChange`` each).
"""

from projectzero.evaluator.core import ConvictionChange
from projectzero.evaluator.routes import (
    ACTIONS,
    UNKNOWN_ACTION,
    UNKNOWN_SESSION,
    Outcome,
    TriggerOutcome,
    action,
    answer,
    attach_evidence,
    deck,
    end,
    imq_trigger,
    loaded,
    next_question,
    resolve,
    session_view,
    skip,
    start,
    workspace,
)

__all__ = [
    "ACTIONS",
    "UNKNOWN_ACTION",
    "UNKNOWN_SESSION",
    "ConvictionChange",
    "Outcome",
    "TriggerOutcome",
    "action",
    "answer",
    "attach_evidence",
    "deck",
    "end",
    "imq_trigger",
    "loaded",
    "next_question",
    "resolve",
    "session_view",
    "skip",
    "start",
    "workspace",
]
