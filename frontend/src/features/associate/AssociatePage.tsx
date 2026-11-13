/**
 * PZ ASSOCIATE (v1 view `associate`, review 033a) — a read-only conversational operating associate. It explains how
 * Project Zero works, investigates records through a closed set of read-only tools, and prepares drafts and questions.
 * It never sends, approves, scores, promotes or changes anything: every action stays with the Smooth Operator. Its
 * character is Ardea, a grey heron (components/Ardea).
 *
 * Ported faithfully from the old page (the CSS and Ardea byte-identical), with these changes:
 * - (c) the `?item=` context (a Scout Intake item) and every Scout mention are gone; `?company=`, `?candidate=`, `?q=`
 *   (the command-palette hand-over) and `?c=` (the open conversation) stay;
 * - revision 2: an answer the server could not save (`saved: false`, its conversation was deleted meanwhile) is shown
 *   with its notice, kept only on this page, and its conversation is not opened or added back to the drawer.
 */
import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";

import { Icon } from "@/components/Icon";
import { Button, ErrorBox, Spinner } from "@/components/ui";
import { useAction } from "@/lib/hooks";
import { ASSOCIATE, useConversation, useConversations, useStatus } from "./api";
import {
  CONTEXT_KEYS,
  CONTEXT_LABEL,
  SUGGESTIONS,
  UNSAVED_NOTICE,
  contextBody,
  headerState,
  isOffline,
  lastAssistantOf,
  offlineReason,
  readContext,
} from "./model/associate";
import type { AskBody, AskRes, Msg } from "./model/types";
import { ArdeaAvatar, ArdeaIllustration } from "./components/Ardea";
import { AssistantMessage } from "./components/AssistantMessage";
import { ConversationList } from "./components/ConversationList";
import { DraftModal, type DraftSeed } from "./components/DraftModal";
import { DraftsDrawer } from "./components/DraftsDrawer";
import { ProfileDrawer } from "./components/ProfileDrawer";
import styles from "./Associate.module.css";

/** An answer the server did not save (revision 2): the question, the reply and the notice, on this page only. */
type Unsaved = { question: string; message: Msg; notice: string };

export default function AssociatePage() {
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const [cid, setCid] = useState<string | null>(params.get("c"));
  const [text, setText] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [unsaved, setUnsaved] = useState<Unsaved | null>(null);
  const [profileOpen, setProfileOpen] = useState(false);
  const [draftsOpen, setDraftsOpen] = useState(false);
  const [draft, setDraft] = useState<DraftSeed | null>(null);
  const context = useMemo(() => readContext(params), [params]);

  const status = useStatus();
  const convs = useConversations();
  const conv = useConversation(cid);
  const ask = useAction<AskBody, AskRes>(ASSOCIATE.ask, { quiet: true, label: "Asking PZ Associate", invalidates: [ASSOCIATE.conversations] });
  const del = useAction<{ id: string }>(ASSOCIATE.conversationDelete, { quiet: true, label: "Removing conversation", invalidates: [ASSOCIATE.conversations] });

  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const messages = cid ? (conv.data?.messages ?? []) : [];

  /** The answer arrived: open its conversation (re-read), or — not saved — keep it here with its notice. */
  async function settle(r: AskRes | undefined, question: string) {
    try {
      if (!r?.message) return; // the same question already in flight (a double send): nothing new
      if (r.saved === false) {
        setUnsaved({ question, message: r.message, notice: r.notice || UNSAVED_NOTICE });
        setCid(null);
        setParams(
          (p) => {
            const n = new URLSearchParams(p);
            n.delete("c");
            n.delete("q");
            return n;
          },
          { replace: true },
        );
        return;
      }
      await qc.invalidateQueries({ queryKey: [ASSOCIATE.conversation] });
      if (r.conversation?.id) {
        const id = r.conversation.id;
        setCid(id);
        setParams(
          (p) => {
            const n = new URLSearchParams(p);
            n.set("c", id);
            n.delete("q");
            return n;
          },
          { replace: true },
        );
      }
    } finally {
      setPending(null);
    }
  }

  function send(message: string, conversationId: string | null = cid) {
    const m = message.trim();
    if (!m || ask.isPending || pending) return;
    setPending(m);
    setUnsaved(null);
    setText("");
    ask.mutate(
      { message: m, conversation_id: conversationId, context: contextBody(context) },
      { onSuccess: (r) => void settle(r, m), onError: () => setPending(null) },
    );
  }

  // ?q= from the command palette: ask it once — also when PZ Associate is already open (same route, new query)
  const asked = useRef<string | null>(null);
  const q = params.get("q");
  useEffect(() => {
    if (q && asked.current !== q) {
      asked.current = q;
      const c = params.get("c"); // a palette question (no ?c=) starts a fresh conversation
      setCid(c);
      send(q, c);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  useEffect(() => {
    // follow the conversation as it grows — never on an empty page (the header and welcome stay in view)
    if (messages.length || pending || unsaved) endRef.current?.scrollIntoView?.({ block: "end", behavior: "smooth" });
  }, [messages.length, pending, unsaved]);

  function newConversation() {
    setCid(null);
    setUnsaved(null);
    setParams((p) => {
      const n = new URLSearchParams(p);
      n.delete("c");
      n.delete("q");
      return n;
    });
    inputRef.current?.focus();
  }

  function open(id: string) {
    setCid(id);
    setUnsaved(null);
    setParams((p) => {
      const n = new URLSearchParams(p);
      n.set("c", id);
      n.delete("q");
      return n;
    });
  }

  function remove(id: string) {
    del.mutate({ id });
    if (id === cid) newConversation();
  }

  function clearContext() {
    setParams((p) => {
      const n = new URLSearchParams(p);
      for (const k of CONTEXT_KEYS) n.delete(k);
      return n;
    });
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    send(text);
  }
  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send(text);
    }
  }

  const st = status.data;
  const offline = isOffline(st);
  const empty = !messages.length && !pending && !unsaved;
  const lastAssistant = unsaved?.message ?? lastAssistantOf(messages);
  const avatar = headerState(!!pending, lastAssistant);

  return (
    <div className={styles.page}>
      <header className={styles.head}>
        <div className={styles.identity}>
          <ArdeaAvatar size={44} state={avatar} decorative />
          <div>
            <h1 className={styles.title}>PZ Associate</h1>
            <p className={styles.sub}>Explains, investigates and prepares — read-only. Every decision and message stays with you.</p>
          </div>
        </div>
        <div className={styles.headActions}>
          <Button size="sm" onClick={() => setProfileOpen(true)}>
            Your context
          </Button>
          <Button size="sm" onClick={() => setDraftsOpen(true)}>
            Drafts
          </Button>
          <Button size="sm" variant="primary" onClick={newConversation}>
            New conversation
          </Button>
        </div>
      </header>

      {offline && (
        <div className={styles.banner} role="status" data-testid="associate-offline">
          <strong>Model not available</strong> — {offlineReason(st)}. PZ Associate still answers from the Project Zero documentation; record lookups need the
          model.
        </div>
      )}

      <div className={styles.layout}>
        <ConversationList rows={convs.data?.conversations ?? []} loading={convs.isLoading} current={cid} onOpen={open} onDelete={remove} />

        <section className={styles.main} aria-label="Conversation with PZ Associate">
          <div className={styles.transcript} aria-live="polite" aria-busy={!!pending}>
            {cid && conv.isLoading && <Spinner label="Opening conversation…" />}
            {cid && conv.error && <ErrorBox error={conv.error} onRetry={() => conv.refetch()} />}
            {empty && !(cid && conv.isLoading) && (
              <div className={styles.welcome} data-testid="associate-welcome">
                <ArdeaIllustration className={styles.hero} />
                <div className={styles.welcomeText}>
                  <p className={styles.kicker}>Meet Ardea</p>
                  <h2 className={styles.welcomeTitle}>Patient, selective, and always grounded in your records.</h2>
                  <p className={styles.welcomeBody}>
                    Ask how Project Zero works, what a record says, or what to prepare next. Ardea reads Conviction, Deal Flow, Radar, events and the PZ
                    documentation — and cites what it used. It can draft, but it never sends, approves, scores or changes anything.
                  </p>
                  <ul className={styles.suggest} aria-label="Suggested questions">
                    {SUGGESTIONS.map((s) => (
                      <li key={s}>
                        <button type="button" className={styles.suggestion} onClick={() => send(s)}>
                          {s}
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            )}

            {messages.map((m, i) =>
              m.role === "user" ? (
                <div key={i} className={styles.userRow}>
                  <div className={styles.userBubble}>{m.text}</div>
                </div>
              ) : (
                <AssistantMessage
                  key={i}
                  m={m}
                  latest={m === lastAssistant && !pending}
                  onDraft={(title) => setDraft({ title, body: m.text, ref: m.focus?.[0] })}
                />
              ),
            )}

            {unsaved && !pending && (
              <>
                <div className={styles.userRow}>
                  <div className={styles.userBubble}>{unsaved.question}</div>
                </div>
                <AssistantMessage
                  m={unsaved.message}
                  latest
                  notice={unsaved.notice}
                  onDraft={(title) => setDraft({ title, body: unsaved.message.text, ref: unsaved.message.focus?.[0] })}
                />
              </>
            )}

            {pending && (
              <>
                <div className={styles.userRow}>
                  <div className={styles.userBubble}>{pending}</div>
                </div>
                <div className={styles.thinking} data-testid="associate-thinking">
                  <ArdeaAvatar size={32} state="thinking" decorative />
                  <span>Reading Project Zero…</span>
                </div>
              </>
            )}
            {ask.error && !pending && <ErrorBox error={ask.error} />}
            <div ref={endRef} />
          </div>

          <form className={styles.composer} onSubmit={onSubmit}>
            {context && (
              <div className={styles.contextChip} data-testid="associate-context">
                <span>
                  About: {CONTEXT_LABEL[context.key]} <strong>{context.value}</strong>
                </span>
                <button type="button" onClick={clearContext} aria-label="Clear the selected record">
                  <Icon name="close" size={12} />
                </button>
              </div>
            )}
            <div className={styles.inputRow}>
              <label className="sr-only" htmlFor="associate-input">
                Ask PZ Associate
              </label>
              <textarea
                id="associate-input"
                ref={inputRef}
                className={styles.input}
                rows={2}
                maxLength={4000}
                placeholder="Ask about a company, a candidate, today's work, or how Project Zero works…"
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={onKey}
              />
              <Button type="submit" variant="primary" busy={ask.isPending} disabled={!text.trim()}>
                Ask
              </Button>
            </div>
            <p className={styles.hint}>Enter to ask · Shift+Enter for a new line · Read-only: nothing in Project Zero is changed. With paid model access on, your question and the records used to answer go to the configured model provider.</p>
          </form>
        </section>
      </div>

      <DraftModal draft={draft} conversationId={cid} onClose={() => setDraft(null)} />
      <ProfileDrawer open={profileOpen} onClose={() => setProfileOpen(false)} />
      <DraftsDrawer open={draftsOpen} onClose={() => setDraftsOpen(false)} />
    </div>
  );
}
