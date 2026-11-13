"""PZ Associate endpoints (review 033a): the old ``/api/associate_*`` routes under ``/api/associate/``, with the old
bodies and answers.

* ``GET  /api/associate/status``               the model status, the paid switch and the docs index
* ``POST /api/associate/ask``                  ``{message, conversation_id?, context?{company|candidate}}`` ->
                                               ``{conversation: {id, title}, message}``; with ``saved: false`` and a
                                               ``notice`` when the conversation was deleted meanwhile (revision 2)
* ``GET  /api/associate/conversations``        ``{conversations}`` newest first
* ``GET  /api/associate/conversation?id=``     the conversation · 404 ``{ok: false, error}``
* ``POST /api/associate/conversation_delete``  ``{id}`` -> ``{ok}``
* ``GET  /api/associate/profile`` / ``POST``   ``{profile, fields}`` / ``{profile}``
* ``GET  /api/associate/drafts``               ``{drafts}`` newest first
* ``POST /api/associate/draft``                ``{title, body, ref?, conversation_id?, confirm: true}`` -> ``{draft}``
* ``POST /api/associate/draft_delete``         ``{id}`` -> ``{ok}``

Only the Associate's own tables are written (and the gateway's accounting). The ask is three-phase (decision b): a
bounded read of the history and the profile; the loop with NO transaction open while the model runs (each tool call
reads its own snapshot); one bounded transaction that appends the turn. The model is reached only through the
inference gateway; with paid calls off every answer is offline (decision a).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from psycopg import sql

from projectzero.api.clock import berlin_request_now
from projectzero.api.routers.conviction import Body
from projectzero.associate import caps, engine, tools
from projectzero.associate.reader import DbReader
from projectzero.associate.store import AssociateStore
from projectzero.core.db import schema_ident, transaction
from projectzero.core.inference import config as icfg
from projectzero.core.inference import gateway
from projectzero.core.inference.pg_store import PostgresBudgetStore
from projectzero.events.edits import EventsError
from projectzero.events.scan import bounded_transaction
from projectzero.validation.inputs import parse_archived

router = APIRouter(prefix="/api/associate", tags=["associate"])
ASK_DEADLINE_S = 240.0  # up to 4 model calls of the CHEAP role (60 s each) plus the reads; the old route had none
STORE_DEADLINE_S = 30.0  # the bounded reads and writes around it
UNSAVED = "This conversation was deleted while the answer was being prepared; the answer was not saved."
ASK_EXPIRED = "the answer took longer than the time allowed; nothing was saved"


class AskExpired(Exception):
    """The ask's deadline passed during phase 2 (Codex H-317): no further model call, no tool read, no save."""


def _err(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


def _instant(request: Request) -> datetime:
    """The request instant, aware (the messages' ``at`` is UTC, as the old ``now()``)."""
    clock: Callable[[], datetime] | None = getattr(request.app.state, "clock", None)
    t = clock() if clock is not None else datetime.now(UTC)
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _monotonic(request: Request) -> Callable[[], float]:
    clock: Callable[[], float] = getattr(request.app.state, "monotonic", time.monotonic)
    return clock


def _settings(conn: Any, schema: str) -> dict[str, Any]:
    """The old ``_config()``: ``config.json`` ``associate`` (the byte-exact archive, else the documents row)."""
    s = schema_ident(schema)
    rows = conn.execute(sql.SQL("select raw from {}.legacy_documents where path = 'config.json'").format(s)).fetchall()
    cfg = parse_archived(rows[0][0]) if rows else None
    if cfg is None:
        doc = conn.execute(sql.SQL("select body from {}.documents where key = 'config.json'").format(s)).fetchall()
        cfg = doc[0][0] if doc else {}
    return engine.settings((cfg if isinstance(cfg, dict) else {}).get("associate"))


def _kill_switch() -> str | None:
    """Decision (f) of 032a: the paid switch's name while paid calls are off (the new semantics)."""
    import os

    return None if icfg.paid_enabled(os.environ) else icfg.PAID_ENV


@router.get("/status")
def get_status(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    with transaction(settings.db_url) as conn:
        cfg = _settings(conn, settings.schema)
    st = gateway.status(PostgresBudgetStore(settings.db_url, settings.schema))
    model = (st.get("roles") or {}).get(cfg["role"])
    body = engine.status(role=cfg["role"], max_steps=cfg["max_steps"], model=model, kill_switch=_kill_switch())
    return JSONResponse(jsonable_encoder(body))


@router.post("/ask")
def post_ask(request: Request, body: Body) -> JSONResponse:
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    msg = str(body.get("message") or "").strip()
    if not msg:
        return _err("message required")
    cid = str(body.get("conversation_id")) if body.get("conversation_id") else None
    ctx = body.get("context") if isinstance(body.get("context"), dict) else None
    mono = _monotonic(request)
    done_by = mono() + ASK_DEADLINE_S
    instant = _instant(request)
    try:
        # phase 1: the history, the profile and the settings, bounded
        with bounded_transaction(settings.db_url, min(done_by, mono() + STORE_DEADLINE_S), mono) as conn:
            store = AssociateStore(conn, settings.schema)
            if cid is not None:
                caps.safe_conversation_id(cid)  # ValueError: the old 400
            existed = cid is not None and store.exists(cid)  # an unknown id starts a new conversation, as before
            history = store.history(cid) if existed and cid else []
            profile = store.load_profile()
            cfg = _settings(conn, settings.schema)
    except ValueError as e:
        return _err(str(e))
    except EventsError as e:
        return _err(str(e), e.status)
    # phase 2: no transaction open while the model runs; each tool call reads its own snapshot
    kw: dict[str, Any] = dict(getattr(request.app.state, "associate_gateway_kw", {}) or {})
    budget = PostgresBudgetStore(settings.db_url, settings.schema)

    def call_model(messages: list[dict[str, str]]) -> engine.ModelReply:
        if mono() >= done_by:  # Codex H-317: no model call once the ask's time is up
            raise AskExpired
        res = gateway.complete(
            cfg["role"], messages, purpose=engine.PURPOSE, json_mode=True, validate=engine._validate,
            max_output_tokens=1600, store=budget, deadline=done_by, monotonic=mono, **kw,
        )  # fmt: skip
        return engine.ModelReply.of(res)

    read = tools.runner(DbReader(settings.db_url, settings.schema, berlin_request_now(request), done_by=done_by,
                                 clock=mono))  # fmt: skip

    def run_tool(name: str, args: Any) -> dict[str, Any]:
        """Codex H-317: a tool read is bounded by the ask's deadline; a read cut by it (or starting after it) ends the
        ask: the tools report a failed source as data, so the deadline is checked around each read here."""
        if mono() >= done_by:
            raise AskExpired
        out = read(name, args)
        if mono() >= done_by:
            raise AskExpired
        return out

    try:
        outcome = engine.ask(msg, history=history, profile=profile, context=ctx, call_model=call_model,
                             run_tool=run_tool, now=instant, max_steps=cfg["max_steps"])  # fmt: skip
    except AskExpired:
        return _err(ASK_EXPIRED, 503)
    hook = getattr(request.app.state, "associate_before_save", None)  # tests only: overlapping asks, a delete
    if hook is not None:
        hook()
    # phase 3: one bounded transaction appends the turn (or answers unsaved: the conversation is gone)
    try:
        with bounded_transaction(settings.db_url, done_by, mono) as conn:  # the ask's time left, never a fresh window
            saved = AssociateStore(conn, settings.schema).save_turn(
                cid if existed else None, outcome.title, outcome.messages, instant
            )
            fail = getattr(request.app.state, "associate_fail_after_append", None)  # tests only: phase 3 rolls back
            if fail is not None:
                fail()
    except EventsError as e:
        return _err(str(e), e.status)
    if not saved.saved:
        reply = {**outcome.reply(None, saved.title), "saved": False, "notice": UNSAVED}  # type: ignore[arg-type]
        return JSONResponse(jsonable_encoder(reply))
    assert saved.conversation_id is not None
    return JSONResponse(jsonable_encoder(outcome.reply(saved.conversation_id, saved.title)))


@router.get("/conversations")
def get_conversations(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    with transaction(settings.db_url) as conn:
        return JSONResponse(
            jsonable_encoder({"conversations": AssociateStore(conn, settings.schema).list_conversations()})
        )


@router.get("/conversation")
def get_conversation(request: Request, id: str = "") -> JSONResponse:
    settings = request.app.state.settings
    try:
        with transaction(settings.db_url) as conn:
            conv = AssociateStore(conn, settings.schema).load_conversation(id)
    except ValueError as e:
        return _err(str(e))
    if conv is None:
        return _err("conversation not found", 404)
    # the stored ``json`` bodies keep the old key order; serialize as stored
    return JSONResponse(content=json.loads(json.dumps(conv, ensure_ascii=False, default=str)))


@router.post("/conversation_delete")
def post_conversation_delete(request: Request, body: Body) -> JSONResponse:
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    try:
        with transaction(settings.db_url) as conn:
            return JSONResponse(
                {"ok": AssociateStore(conn, settings.schema).delete_conversation(str(body.get("id") or ""))}
            )
    except ValueError as e:
        return _err(str(e))


@router.get("/profile")
def get_profile(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    with transaction(settings.db_url) as conn:
        profile = AssociateStore(conn, settings.schema).load_profile()
    return JSONResponse(jsonable_encoder({"profile": profile, "fields": caps.profile_fields()}))


@router.post("/profile")
def post_profile(request: Request, body: Body) -> JSONResponse:
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    with transaction(settings.db_url) as conn:
        out = AssociateStore(conn, settings.schema).save_profile(body, _instant(request))
    return JSONResponse(jsonable_encoder({"profile": out}))


@router.get("/drafts")
def get_drafts(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    with transaction(settings.db_url) as conn:
        drafts = AssociateStore(conn, settings.schema).list_drafts()
    return JSONResponse(content=json.loads(json.dumps({"drafts": list(reversed(drafts))}, ensure_ascii=False)))


@router.post("/draft")
def post_draft(request: Request, body: Body) -> JSONResponse:
    """Save a prepared text to the Associate's OWN drafts — only with an explicit confirmation from the UI."""
    if isinstance(body, JSONResponse):
        return body
    try:
        title, text, ref, cid = caps.draft_request(body)
    except ValueError as e:
        return _err(str(e))
    settings = request.app.state.settings
    with transaction(settings.db_url) as conn:
        d = AssociateStore(conn, settings.schema).save_draft(title, text, ref, cid, _instant(request))
    return JSONResponse(content=json.loads(json.dumps({"draft": d}, ensure_ascii=False)))


@router.post("/draft_delete")
def post_draft_delete(request: Request, body: Body) -> JSONResponse:
    if isinstance(body, JSONResponse):
        return body
    settings = request.app.state.settings
    with transaction(settings.db_url) as conn:
        return JSONResponse({"ok": AssociateStore(conn, settings.schema).delete_draft(str(body.get("id") or ""))})
