-- Review 033a: the PZ Associate's own store (the old `<data>/associate/` folder). Nothing here is a Project Zero
-- record; the Associate never writes outside these tables (and the gateway's accounting). The old data folder holds
-- no Associate data (an empty conversation index), so nothing is backfilled; its files stay archived as usual.
--
-- * associate_conversations: the index (the old `conversations.json`, at most 60, the oldest by `updated_at` evicted)
--   plus each conversation's own fields (the old `c/<id>.json` without its messages).
-- * associate_messages: the messages in order (`seq`), at most 80 per conversation (the oldest pruned, as the old
--   store truncated). Messages are IMMUTABLE to edits: every UPDATE is refused. A DELETE is allowed only inside the
--   store's two lifecycle operations (pruning, and deleting / evicting a conversation, whose cascade runs in the same
--   transaction), which set `associate.lifecycle = 'on'` locally to their transaction; an unset flag is off
--   (revision 2, Codex H-314/H-315). The setting's name holds no `pz` word: the scratch schemas rewrite `pz`.
-- * associate_drafts: the saved drafts (at most 200, the oldest dropped); written only after the page's confirmation.
-- * The operating profile is the `documents` row `associate/profile.json`.
create table pz.associate_conversations (
  id                text primary key check (id ~ '^c-[0-9a-f]{12}$'),
  title             text not null default '',
  created_at        timestamptz not null,
  updated_at        timestamptz not null,
  detail            jsonb not null default '{}'          -- any further field of the old conversation file
);
create index associate_conversations_updated_idx on pz.associate_conversations (updated_at, id);

create table pz.associate_messages (
  conversation_id   text not null references pz.associate_conversations (id) on delete cascade,
  seq               integer not null check (seq > 0),
  at                timestamptz not null,
  role              text not null check (role in ('user', 'assistant')),
  body              json not null,                        -- the old message object whole (its key order: json)
  primary key (conversation_id, seq)
);

create or replace function pz.associate_message_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'UPDATE' then
    raise exception 'pz.associate_messages: messages are immutable (UPDATE refused)';
  end if;
  if coalesce(current_setting('associate.lifecycle', true), '') <> 'on' then
    raise exception 'pz.associate_messages: a message is deleted only by pruning or by deleting its conversation';
  end if;
  return old;
end $$;
create trigger associate_messages_guard before update or delete on pz.associate_messages
  for each row execute function pz.associate_message_guard();

create table pz.associate_drafts (
  id                text primary key check (id ~ '^d-[0-9a-f]{10}$'),
  title             text not null,
  body              text not null,
  ref               jsonb,
  conversation_id   text,                                 -- kept as written, even after that conversation is gone
  created_at        timestamptz not null,
  record            json not null                         -- the old draft object whole (its key order: json)
);
create index associate_drafts_created_idx on pz.associate_drafts (created_at, id);

alter table pz.associate_conversations enable row level security;
alter table pz.associate_messages enable row level security;
alter table pz.associate_drafts enable row level security;
revoke all on pz.associate_conversations, pz.associate_messages, pz.associate_drafts from public, anon, authenticated;
revoke all on function pz.associate_message_guard() from public, anon, authenticated;
