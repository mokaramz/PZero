"""PZ Associate — the caps and the shapes of its own store (review 033a), for the database store to use.

The old ``services/associate/store.py`` at revision 6c739b9. Cut WHOLE by script (``python -m
projectzero.ops.parity_associate cuts``; checked by ``tests/associate``): ``MAX_CONVERSATIONS`` (60, the oldest
evicted), ``MAX_TURNS`` (80 messages kept per conversation), ``MAX_DRAFTS`` (200), ``PROFILE_FIELDS`` (6), ``now``
and ``_safe_id``. Hand-ported line for line from the old store and router bodies, with the file I/O taken out (the
store does it): ``conversation_title``, ``new_conversation_id``, ``trim_messages``, ``index_entry``, ``evict``,
``profile_of`` (``load_profile``), ``profile_from_body`` (``save_profile``), ``profile_fields``, ``draft_of``
(``save_draft``), ``keep_drafts`` and ``draft_request`` (the old route's checks: ``confirm: true`` and a body).
Pure: no clock (``now`` is the old helper; every shape takes its time stamp), no database, no file.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

# fmt: off
# ── cut from services/associate/store.py: MAX_CONVERSATIONS, MAX_TURNS, MAX_DRAFTS, PROFILE_FIELDS, now, _safe_id ──
MAX_CONVERSATIONS = 60
MAX_TURNS = 80
MAX_DRAFTS = 200
PROFILE_FIELDS = (
    ("interests", "Investment interests"),
    ("sourcing_priorities", "Sourcing priorities"),
    ("quality_standards", "Quality standards"),
    ("routines", "Working routines"),
    ("output_preferences", "Preferred output formats"),
    ("boundaries", "Decision boundaries"),
)


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_id(cid: str) -> str:
    if not re.fullmatch(r"c-[0-9a-f]{12}", cid or ""):
        raise ValueError("invalid conversation id")
    return cid
# ── end of cut ──
# fmt: on

PROFILE_CHARS = 1200  # each profile field (old load_profile / save_profile)
DRAFT_CHARS = 20000  # a draft's body (old save_draft)
DRAFT_TITLE_CHARS = 120
TITLE_CHARS = 80  # a conversation's title (old new_conversation)


def stamp(at: datetime) -> str:
    """A time stamp in the old ``now()`` format (UTC, to the second); a naive ``at`` is read as UTC."""
    return (at.astimezone(UTC) if at.tzinfo else at).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_conversation_id(cid: str) -> str:
    """The old ``_safe_id``: ``c-`` and 12 lowercase hex digits, else ``ValueError("invalid conversation id")``."""
    return _safe_id(cid)


def new_conversation_id() -> str:
    return "c-" + uuid.uuid4().hex[:12]


def new_draft_id() -> str:
    return "d-" + uuid.uuid4().hex[:10]


def conversation_title(title: str) -> str:
    """A new conversation's title (old ``new_conversation``; the engine passes the question's first 60 characters)."""
    return (title or "New conversation").strip()[:80]


def trim_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The old ``save_conversation``: only the last ``MAX_TURNS`` messages are kept."""
    return messages[-MAX_TURNS:]


def index_entry(conv: Mapping[str, Any]) -> dict[str, Any]:
    """One row of the old ``conversations.json`` index."""
    return {
        "id": conv["id"],
        "title": conv.get("title", ""),
        "updated": conv["updated"],
        "turns": len(conv["messages"]),
    }


def evict(idx: list[dict[str, Any]], conv: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The old ``save_conversation`` index rule: ``conv`` replaces its row, rows sort by ``updated`` (stable), and the
    oldest beyond ``MAX_CONVERSATIONS`` are dropped. Returns (kept, dropped)."""
    idx = [c for c in idx if c.get("id") != conv["id"]]
    idx.append(index_entry(conv))
    idx.sort(key=lambda c: c.get("updated", ""))
    drop = idx[:-MAX_CONVERSATIONS]
    idx = idx[-MAX_CONVERSATIONS:]
    return idx, drop


def listed(idx: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The old ``list_conversations``: the index, newest first."""
    return sorted(idx, key=lambda c: c.get("updated", ""), reverse=True)


def profile_of(raw: Any) -> dict[str, Any]:
    """The old ``load_profile`` over the stored document (``{}`` when absent)."""
    raw = raw if isinstance(raw, dict) else {}
    return {k: str(raw.get(k) or "")[:1200] for k, _ in PROFILE_FIELDS} | {"updated": raw.get("updated")}


def profile_from_body(body: Mapping[str, Any], at: str) -> dict[str, Any]:
    """The old ``save_profile``: the document to store (and the route's answer), stamped ``at``."""
    out: dict[str, Any] = {k: str(body.get(k) or "").strip()[:1200] for k, _ in PROFILE_FIELDS}
    out["updated"] = at
    return out


def profile_fields() -> list[dict[str, str]]:
    """The old ``GET /api/associate_profile`` ``fields``."""
    return [{"key": k, "label": label} for k, label in PROFILE_FIELDS]


def draft_of(title: str, body: str, ref: Any, conversation_id: str | None, *, id: str, at: str) -> dict[str, Any]:
    """The old ``save_draft`` record (``id`` from ``new_draft_id``, ``at`` from ``stamp``)."""
    return {
        "id": id,
        "title": (title or "Draft").strip()[:120],
        "body": (body or "").strip()[:20000],
        "ref": ref if isinstance(ref, dict) else None,
        "conversation_id": conversation_id,
        "created": at,
    }


def keep_drafts(drafts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The old ``save_draft``: only the last ``MAX_DRAFTS`` drafts are kept (oldest first, as stored)."""
    return drafts[-MAX_DRAFTS:]


def draft_request(body: Mapping[str, Any]) -> tuple[str, str, Any, str | None]:
    """The old ``POST /api/associate_draft`` checks: ``(title, body, ref, conversation_id)`` for ``draft_of``, or
    ``ValueError`` with the old 400 message (a draft is saved only with ``confirm: true``)."""
    if body.get("confirm") is not True:
        raise ValueError("saving a draft needs your explicit confirmation (confirm: true)")
    text = str(body.get("body") or "").strip()
    if not text:
        raise ValueError("draft body required")
    cid = body.get("conversation_id")
    return str(body.get("title") or "Associate draft"), text, body.get("ref"), str(cid) if cid else None
