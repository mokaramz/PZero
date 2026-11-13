"""The PZ Associate's own store in the database (review 033a, migration 0022): the old ``<data>/associate/`` folder.

Nothing here is a Project Zero record. The shapes are the old store's (``caps``); the rules are revision 2's:

* messages are immutable; a delete happens only in the two lifecycle operations (pruning beyond ``MAX_TURNS``, and
  deleting / evicting a conversation), which set ``associate.lifecycle`` local to their transaction;
* ``save_turn`` (the ask's phase 3) takes the conversation row ``FOR UPDATE``, appends the two messages after the
  HIGHEST retained ``seq`` and prunes to ``MAX_TURNS``; creating a conversation first takes the Associate index lock
  and evicts beyond ``MAX_CONVERSATIONS``. Lock order: the index lock, then the conversation row;
* a conversation that existed when the ask began but is gone at phase 3 is NOT recreated (``saved: False``).

Every call takes a connection inside the caller's transaction; the routes bound them (``events.scan`` pattern).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Json, Jsonb

from projectzero.associate import caps
from projectzero.core.db import schema_ident

PROFILE_KEY = "associate/profile.json"
INDEX_LOCK = "associate.index"  # one advisory lock: creating / evicting conversations
DRAFTS_LOCK = "associate.drafts"


def _ordered_json(value: Any) -> Json:
    """A ``json`` (not jsonb) parameter: the old object's key order is kept."""
    return Json(value, dumps=lambda v: json.dumps(v, ensure_ascii=False))


@dataclass(frozen=True)
class SavedTurn:
    conversation_id: str | None
    title: str
    saved: bool


class AssociateStore:
    def __init__(self, conn: psycopg.Connection[Any], schema: str) -> None:
        self.conn = conn
        self.s = schema_ident(schema)

    def _rows(self, query: str, params: Any = ()) -> list[dict[str, Any]]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql.SQL(query).format(s=self.s), params)
            return list(cur.fetchall()) if cur.description else []

    def _lifecycle(self) -> None:
        self._rows("select set_config('associate.lifecycle', 'on', true)")

    def _lock(self, name: str) -> None:
        self._rows("select pg_advisory_xact_lock(hashtext(%s))", (f"{name}",))

    # ── conversations ─────────────────────────────────────────────────────────────────────────────────────────
    def _index(self) -> list[dict[str, Any]]:
        rows = self._rows(
            "select c.id, c.title, c.updated_at, (select count(*) from {s}.associate_messages m "
            "where m.conversation_id = c.id) as turns from {s}.associate_conversations c order by c.updated_at, c.id"
        )
        return [{"id": r["id"], "title": r["title"], "updated": caps.stamp(r["updated_at"]), "turns": int(r["turns"])}
                for r in rows]  # fmt: skip

    def list_conversations(self) -> list[dict[str, Any]]:
        """The old ``list_conversations``: the index, newest first."""
        return caps.listed(self._index())

    def exists(self, cid: str) -> bool:
        return bool(self._rows("select 1 from {s}.associate_conversations where id = %s", (cid,)))

    def load_conversation(self, cid: str) -> dict[str, Any] | None:
        """The old ``load_conversation`` (``ValueError`` for a malformed id): the conversation file's shape."""
        caps.safe_conversation_id(cid)
        rows = self._rows("select * from {s}.associate_conversations where id = %s", (cid,))
        if not rows:
            return None
        c = rows[0]
        msgs = self._rows(
            "select body from {s}.associate_messages where conversation_id = %s order by seq", (cid,)
        )  # fmt: skip
        return {"id": c["id"], "title": c["title"], "created": caps.stamp(c["created_at"]),
                "updated": caps.stamp(c["updated_at"]), **(c["detail"] or {}),
                "messages": [m["body"] for m in msgs]}  # fmt: skip

    def history(self, cid: str) -> list[dict[str, Any]]:
        conv = self.load_conversation(cid)
        return list(conv["messages"]) if conv else []

    def delete_conversation(self, cid: str) -> bool:
        """The old ``delete_conversation``: ``True`` when it existed. Its messages go with it (the cascade)."""
        caps.safe_conversation_id(cid)
        if not self._rows("select id from {s}.associate_conversations where id = %s for update", (cid,)):
            return False
        self._lifecycle()
        self._rows("delete from {s}.associate_conversations where id = %s", (cid,))
        return True

    def save_turn(self, cid: str | None, title: str, messages: tuple[dict[str, Any], ...], now: datetime) -> SavedTurn:
        """Phase 3 of an ask: append ``messages`` (the user's, then the assistant's) to ``cid``, or to a NEW
        conversation titled ``title`` when ``cid`` is ``None``. ``now`` is aware (UTC)."""
        at = now.astimezone(UTC)
        if cid is None:
            self._lock(INDEX_LOCK)
            cid = caps.new_conversation_id()
            self._rows(
                "insert into {s}.associate_conversations (id, title, created_at, updated_at) values (%s, %s, %s, %s)",
                (cid, title, at, at),
            )
            self._evict(cid)
        else:
            row = self._rows("select title from {s}.associate_conversations where id = %s for update", (cid,))
            if not row:  # deleted or evicted while the answer was being prepared: never recreated (revision 2)
                return SavedTurn(None, title, False)
            title = row[0]["title"]
        top = self._rows("select coalesce(max(seq), 0) as top from {s}.associate_messages where conversation_id = %s",
                         (cid,))[0]["top"]  # fmt: skip
        for i, m in enumerate(messages, start=1):  # after the HIGHEST retained seq, never the capped count
            self._rows(
                "insert into {s}.associate_messages (conversation_id, seq, at, role, body) values (%s, %s, %s, %s, %s)",
                (cid, int(top) + i, at, m["role"], _ordered_json(m)),
            )
        self._rows("update {s}.associate_conversations set updated_at = %s where id = %s", (at, cid))
        self._prune(cid)
        return SavedTurn(cid, title, True)

    def _prune(self, cid: str) -> None:
        """The old ``save_conversation`` truncation: only the last ``MAX_TURNS`` messages are kept."""
        rows = self._rows(
            "select seq from {s}.associate_messages where conversation_id = %s order by seq desc offset %s",
            (cid, caps.MAX_TURNS),
        )
        if rows:
            self._lifecycle()
            self._rows("delete from {s}.associate_messages where conversation_id = %s and seq <= %s",
                       (cid, max(r["seq"] for r in rows)))  # fmt: skip

    def _evict(self, keep: str) -> None:
        """The old index rule: the oldest by ``updated`` beyond ``MAX_CONVERSATIONS`` go, with their messages."""
        rows = self._rows("select id from {s}.associate_conversations order by updated_at desc, id desc offset %s",
                          (caps.MAX_CONVERSATIONS,))  # fmt: skip
        gone = [r["id"] for r in rows if r["id"] != keep]
        if gone:
            self._lifecycle()
            self._rows("delete from {s}.associate_conversations where id = any(%s)", (gone,))

    # ── the profile ───────────────────────────────────────────────────────────────────────────────────────────
    def load_profile(self) -> dict[str, Any]:
        rows = self._rows("select body from {s}.documents where key = %s", (PROFILE_KEY,))
        return caps.profile_of(rows[0]["body"] if rows else {})

    def save_profile(self, body: dict[str, Any], now: datetime) -> dict[str, Any]:
        out = caps.profile_from_body(body, caps.stamp(now))
        self._rows(
            "insert into {s}.documents (key, body) values (%s, %s) "
            "on conflict (key) do update set body = excluded.body",
            (PROFILE_KEY, Jsonb(out)),
        )
        return out

    # ── drafts ────────────────────────────────────────────────────────────────────────────────────────────────
    def list_drafts(self) -> list[dict[str, Any]]:
        """The old ``list_drafts``: oldest first, as stored."""
        return [r["record"] for r in self._rows("select record from {s}.associate_drafts order by created_at, id")]

    def save_draft(self, title: str, body: str, ref: Any, cid: str | None, now: datetime) -> dict[str, Any]:
        self._lock(DRAFTS_LOCK)
        d = caps.draft_of(title, body, ref, cid, id=caps.new_draft_id(), at=caps.stamp(now))
        self._rows(
            "insert into {s}.associate_drafts (id, title, body, ref, conversation_id, created_at, record) "
            "values (%s, %s, %s, %s, %s, %s, %s)",
            (d["id"], d["title"], d["body"], Jsonb(d["ref"]) if d["ref"] is not None else None, d["conversation_id"],
             now.astimezone(UTC), _ordered_json(d)),
        )  # fmt: skip
        self._rows("delete from {s}.associate_drafts where id in (select id from {s}.associate_drafts "
                   "order by created_at desc, id desc offset %s)", (caps.MAX_DRAFTS,))  # fmt: skip
        return d

    def delete_draft(self, did: str) -> bool:
        return bool(self._rows("delete from {s}.associate_drafts where id = %s returning id", (did,)))
