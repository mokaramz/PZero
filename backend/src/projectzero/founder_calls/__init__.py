"""Founder Calls (review 023): the call log, follow-ups, links (with the merge), the memo and the Manager briefing.

A mechanical port of the old ``domain/founder_calls.py`` and ``api/routers/calls.py`` at revision 6c739b9. Pure
functions over the founder_calls DOCUMENT ``{version, label, companies{}, founders{}, calls{}}`` (the old file, as
``store.load`` rebuilds it, insertion order included) plus explicit inputs. The clock is a parameter: ``today`` is the
Europe/Berlin day and ``now`` the request clock (aware, or naive Berlin wall time; ``network.view.berlin_now``); the
old ``_today()`` / ``_now()`` became them. Nothing here reads or writes storage; the DB layer loads the document,
applies a function and writes the changed records.

Modules:

* ``catalog``  constants cut by script (``scripts/gen_founder_calls_catalog.py``): ``FILE_NAME``, ``LABEL``,
  ``SUMMARY_LABEL``, ``UNKNOWN``, ``CHANNELS``, ``CALL_TYPES``, ``RECOMMENDATIONS``, ``CONFIDENCE``, ``OWNERS``,
  ``UPCOMING_DAYS``, ``TEMPLATES``, ``ASSESSMENT_FIELDS``.
* ``core``     the old domain functions line for line over a MUTABLE ``d`` (``loaded``, ``resolve_*``,
  ``ensure_company`` / ``ensure_founder``, ``link_founder`` / ``link_company`` (+ ``_merge_founders``), ``save_call``,
  ``set_followup``, ``due_state``, ``summary``, ``call_view``, ``history``, ``due_followups``, ``workspace``,
  ``memo_markdown``, ``briefing_markdown``), with ``Clock(now, today, new_id)`` for the old ``_now`` / ``_today`` /
  ``_id``.
* ``routes``   the old routes, pure (below).

Public signatures (``routes``, re-exported here). ``doc`` is the stored document (``None`` / not a dict reads as the
old empty document); ``people`` the person records (``network.store.load_people``, old ``people.json`` order);
``pipeline`` the stored Conviction records (the old ``real_data.json`` ``signals``, ``[conviction.store.record_of(r)
for r in ConvictionStore.entry_rows()]``); ``evaluations`` the ``evaluations.json`` body (``{}`` when missing or
unreadable, the old tolerant read):

* ``workspace(doc, *, people, pipeline, evaluations, today) -> dict`` — the ``GET /api/calls`` body, incl. the people
  and pipeline pickers (``people_picker(people, today)``, ``pipeline_picker(pipeline)``).
* ``call_view(doc, call_id, *, today) -> dict | None`` — ``GET /api/call?id=``; ``None``: 404
  ``{"error": UNKNOWN_CALL}``.
* ``memo(doc, call_id, *, today) -> dict | None`` — ``GET /api/call_memo?id=`` ``{markdown, label}``; ``None``: 404
  ``{"error": UNKNOWN_CALL}``.
* ``briefing(doc, body, *, today) -> tuple[int, dict]`` — ``POST /api/call_briefing`` (400 without ``confirm``, 404
  when the founder has no calls).
* ``save(doc, body, *, today, now, new_id=None) -> Outcome`` — ``POST /api/call_save`` (200 or 400). ``new_id(prefix)``
  makes the ids of new records (default ``prefix + uuid4().hex[:12]``, as before). The answer carries
  ``pipeline_slug`` when the call's company is linked to one (the old ``case_prep.request`` is a no-op: decision a).
* ``followup(doc, body, *, today, now) -> Outcome`` — ``POST /api/call_followup {id, done}`` (200 or 404).
* ``link(doc, body, *, people, pipeline, today, now) -> Outcome`` — ``POST /api/call_link`` (200, also
  ``{ok: false}`` for an unknown founder / company; 404 unknown person / pipeline company; 400 neither id).
* ``due_state(call, today) -> str`` — ``"" | "done" | "open" | "overdue" | "due" | "upcoming" | "scheduled"``.

``Outcome`` (frozen): ``status`` (the old HTTP code), ``body`` (the old answer; ``{"error": msg}`` when refused),
``doc`` (the document after the request: the INPUT object, unchanged, when the old route saved nothing or saved the
same content; else a new document — never the input mutated), ``changed`` (``{"companies": [ids], "founders":
[ids], "calls": [ids]}``: the records of ``doc`` that are new or differ from the input, in document order; all empty
when nothing changed). New records are appended to their object; a merge keeps both records in place (the loser gains
``merged_into``), so ``doc``'s key order is the old file's. An unchanged save answers ``changed: false`` and returns
the input document.
"""

from projectzero.founder_calls.core import due_state
from projectzero.founder_calls.routes import (
    UNKNOWN_CALL,
    Outcome,
    briefing,
    call_view,
    followup,
    link,
    memo,
    people_picker,
    pipeline_picker,
    save,
    workspace,
)

__all__ = [
    "UNKNOWN_CALL",
    "Outcome",
    "briefing",
    "call_view",
    "due_state",
    "followup",
    "link",
    "memo",
    "people_picker",
    "pipeline_picker",
    "save",
    "workspace",
]
