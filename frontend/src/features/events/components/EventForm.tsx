import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { Button, Callout, Field } from "@/components/ui";
import { useToast } from "@/components/Toast";
import { get } from "@/lib/api";
import { useAction } from "@/lib/hooks";
import { collisionOf, EVENT_KEYS, eventLink, LABEL, SAVE, SUGGEST, type SaveResult } from "../api";
import type { EventLead, EventRecord, EventsPayload } from "../model/types";
import { priceText } from "../model/eventUtil";
import styles from "../Events.module.css";

type Props = {
  ev: EventsPayload;
  event: EventRecord | null;
  lead: EventLead | null;
  onDone: (id?: string) => void;
};

const TEXT_FIELDS = ["name", "type", "organizer", "start", "end", "city", "venue", "url", "deadline", "price", "audience_estimate", "domains", "notes"] as const;

/** Add / edit an event, or convert a lead (v1 openEvent + saveEvent + evAutoSuggest). A conversion is ONE save that
 *  carries `convert_lead` (review 016; the old form sent a second `event_lead` request). An add that collides with an
 *  existing event of the same name and date but other details is refused (409) and offers that event instead; any
 *  other refusal keeps the form as typed. */
export function EventForm({ ev, event: e, lead, onDone }: Props) {
  const toast = useToast();
  const navigate = useNavigate();
  const formRef = useRef<HTMLFormElement>(null);
  const [collision, setCollision] = useState<{ id: string; message: string } | null>(null);
  const save = useAction<Record<string, unknown>, SaveResult>(SAVE, { invalidates: EVENT_KEYS, label: LABEL.save });
  const parts = e?.score_parts ?? null;
  const [dims, setDims] = useState<Record<string, number>>(() => {
    const o: Record<string, number> = {};
    for (const k of ev.dim_order) o[k] = parts?.[k] ?? ev.dims[k]?.ladder[0]?.[0] ?? 0;
    return o;
  });
  const shownPrice = e ? priceText(e.price) : "";

  const suggest = async () => {
    const f = formRef.current;
    if (!f) return;
    const val = (n: string) => (f.elements.namedItem(n) as HTMLInputElement | null)?.value ?? "";
    try {
      const r = await get<{ parts: Record<string, number | null> }>(SUGGEST, {
        name: val("name"),
        type: val("type"),
        city: val("city"),
        organizer: val("organizer"),
        domains: val("domains"),
      });
      setDims((cur) => {
        const next = { ...cur };
        for (const k of ev.dim_order) {
          const target = r.parts[k];
          if (target == null) continue;
          let best = next[k];
          let bd = Infinity;
          for (const [p] of ev.dims[k]?.ladder ?? []) {
            const d = Math.abs(p - target);
            if (d < bd) {
              bd = d;
              best = p;
            }
          }
          next[k] = best;
        }
        return next;
      });
    } catch (err) {
      toast.show(err instanceof Error ? err.message : String(err), "error");
    }
  };

  // v1: a new event (no human ladder yet) gets an auto-suggestion right away.
  const suggested = useRef(false);
  useEffect(() => {
    if (!parts && !suggested.current) {
      suggested.current = true;
      void suggest();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = async (evt: FormEvent<HTMLFormElement>) => {
    evt.preventDefault();
    setCollision(null);
    const fd = new FormData(evt.currentTarget);
    const o: Record<string, unknown> = e ? { id: e.id } : {};
    for (const k of TEXT_FIELDS) o[k] = String(fd.get(k) ?? "");
    // Structured offers are kept as data unless the operator changed the price text.
    if (e && e.price && typeof e.price === "object" && o.price === shownPrice) o.price = e.price;
    o.score_parts = Object.fromEntries(ev.dim_order.map((k) => [k, dims[k]]));
    if (lead) o.convert_lead = lead.id;
    const r = await save.mutateAsync(o).catch((err: unknown) => {
      setCollision(collisionOf(err));
      return null;
    });
    if (!r) return;
    const id = String(r.id);
    toast.show(id.includes("|merged:") ? `Merged into existing event: ${id.split("|merged:")[1]}` : "Event saved & scored", "ok");
    onDone(id.split("|merged:")[0]);
  };

  const openExisting = (id: string) => {
    onDone();
    navigate(eventLink(id));
  };

  const typeDefault = e?.type ?? lead?.type ?? "founder_meetup";
  const sc = e?.sc;

  return (
    <div className="stack">
      {sc && sc.total != null && (
        <Callout tone="blue">
          <b>
            Event Score {sc.total} — {sc.band}.
          </b>{" "}
          Evidence: {(sc.evidence ?? []).map((x) => `${x[0]} ${x[1]}/${x[2]} — ${x[3]}`).join(" · ") || "—"}
        </Callout>
      )}
      {!!e?.sources?.length && (
        <div className="small">
          <b>Seen on:</b>{" "}
          {e.sources.map((s, i) => (
            <span key={i}>
              {i > 0 && " · "}
              {s.url ? (
                <a href={s.url} target="_blank" rel="noreferrer">
                  {s.source}
                </a>
              ) : (
                s.source
              )}
            </span>
          ))}
        </div>
      )}
      <form ref={formRef} className={styles.formGrid} onSubmit={submit} aria-label="Event form">
        <Field label="Event name" className={styles.fullCol}>
          <input name="name" required defaultValue={e?.name ?? lead?.title ?? ""} />
        </Field>
        <Field label="Type">
          <select name="type" defaultValue={typeDefault} onChange={() => void suggest()}>
            {Object.entries(ev.types).map(([k, l]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Organizer">
          <input name="organizer" defaultValue={e ? (e.organizer === "UNKNOWN" ? "" : e.organizer ?? "") : lead?.source ?? ""} />
        </Field>
        <Field label="Start (YYYY-MM-DD)">
          <input name="start" defaultValue={e?.start ?? lead?.date ?? ""} placeholder="2026-09-20" />
        </Field>
        <Field label="End (optional)">
          <input name="end" defaultValue={e?.end ?? ""} />
        </Field>
        <Field label="City">
          <input name="city" defaultValue={e?.city ?? lead?.city ?? ""} onBlur={() => void suggest()} />
        </Field>
        <Field label="Venue">
          <input name="venue" defaultValue={e?.venue ?? ""} />
        </Field>
        <Field label="Link / registration">
          <input name="url" defaultValue={e?.url ?? lead?.url ?? ""} />
        </Field>
        <Field label="Registration deadline">
          <input name="deadline" defaultValue={e?.deadline ?? ""} />
        </Field>
        <Field label="Price">
          <input name="price" defaultValue={shownPrice} title="structured offers are kept as data unless you change this field" />
        </Field>
        <Field label="Expected audience">
          <input name="audience_estimate" defaultValue={String(e?.audience_estimate ?? "")} placeholder="e.g. 200 ETH students + researchers" />
        </Field>
        <Field label="Domains / keywords" className={styles.fullCol}>
          <input name="domains" defaultValue={e?.domains ?? ""} placeholder="robotics, defence, AI agents" />
        </Field>
        <Field label="Notes" className={styles.fullCol}>
          <textarea name="notes" rows={2} defaultValue={e?.notes ?? ""} />
        </Field>
        <Callout tone="blue" className={styles.fullCol}>
          <div className="row">
            <b className="grow">Event Score — pick the evidence, the number follows.</b>
            <Button size="sm" onClick={() => void suggest()}>
              Auto-suggest from type/city/keywords
            </Button>
          </div>
        </Callout>
        {ev.dim_order.map((k) => {
          const D = ev.dims[k];
          if (!D) return null;
          return (
            <Field key={k} label={`${D.label} (max ${D.max})`} className={styles.fullCol}>
              <select name={`dim_${k}`} value={dims[k]} onChange={(x) => setDims((c) => ({ ...c, [k]: Number(x.target.value) }))}>
                {D.ladder.map(([p, lab]) => (
                  <option key={p} value={p}>
                    {lab} ({p})
                  </option>
                ))}
              </select>
            </Field>
          );
        })}
        {collision && (
          <Callout tone="amber" role="alert" className={styles.fullCol} data-testid="save-collision">
            <div className="row">
              <span className="grow">{collision.message}</span>
              <Button size="sm" variant="primary" onClick={() => openExisting(collision.id)}>
                Open existing event
              </Button>
            </div>
          </Callout>
        )}
        <div className={styles.fullCol}>
          <Button type="submit" variant="success" size="lg" busy={save.isPending}>
            Save event
          </Button>
        </div>
      </form>
    </div>
  );
}
