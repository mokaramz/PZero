/**
 * A deliberately small Markdown renderer for PZ Associate answers: paragraphs, headings, bullet / numbered lists,
 * **bold**, *italic*, `code` and links. It builds React elements only (never innerHTML), and only internal PZ links
 * ("/…") become in-app links; external URLs are shown as plain, non-clickable text with their address visible.
 * Ported verbatim (review 033a), except that a link to a retired view (decision c) keeps only its label.
 */
import { Fragment, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { isRetiredLink } from "../model/associate";
import styles from "../Associate.module.css";

function inline(text: string, key: string): ReactNode[] {
  const out: ReactNode[] = [];
  // italics only at word edges, so identifiers like DEEPINFRA_API_KEY or a*b*c stay literal
  const re = /(\*\*[^*]+\*\*|(?<![\w*])\*[^*\s][^*]*\*(?![\w*])|(?<!\w)_[^_\s][^_]*_(?!\w)|`[^`]+`|\[[^\]]+\]\([^)\s]+\))/g;
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(re)) {
    const t = m[0];
    if (m.index! > last) out.push(text.slice(last, m.index));
    const k = `${key}-${i++}`;
    if (t.startsWith("**")) out.push(<strong key={k}>{t.slice(2, -2)}</strong>);
    else if (t.startsWith("`")) out.push(<code key={k}>{t.slice(1, -1)}</code>);
    else if (t.startsWith("[")) {
      const lm = t.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/)!;
      const [label, href] = [lm[1], lm[2]];
      out.push(
        isRetiredLink(href) ? (
          // a retired view (Scout Intake, Scout Bridge — review 033a decision c): its label only, no link, no address
          <span key={k}>{label}</span>
        ) : href.startsWith("/") && !href.startsWith("//") ? (
          <Link key={k} to={href}>
            {label}
          </Link>
        ) : (
          <span key={k} className={styles.extLink} title={href}>
            {label} ({href})
          </span>
        ),
      );
    } else out.push(<em key={k}>{t.slice(1, -1)}</em>);
    last = m.index! + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ text }: { text: string }) {
  const blocks = text.replace(/\r\n/g, "\n").split(/\n{2,}/);
  return (
    <div className={styles.md}>
      {blocks.map((b, bi) => {
        const lines = b.split("\n").filter((l) => l.trim() !== "");
        if (!lines.length) return null;
        const h = lines[0].match(/^(#{1,4})\s+(.*)$/);
        if (h && lines.length === 1) return <h4 key={bi}>{inline(h[2], `h${bi}`)}</h4>;
        if (lines.every((l) => /^\s*[-*•]\s+/.test(l)))
          return (
            <ul key={bi}>
              {lines.map((l, li) => (
                <li key={li}>{inline(l.replace(/^\s*[-*•]\s+/, ""), `u${bi}-${li}`)}</li>
              ))}
            </ul>
          );
        if (lines.every((l) => /^\s*\d+[.)]\s+/.test(l)))
          return (
            <ol key={bi}>
              {lines.map((l, li) => (
                <li key={li}>{inline(l.replace(/^\s*\d+[.)]\s+/, ""), `o${bi}-${li}`)}</li>
              ))}
            </ol>
          );
        return (
          <p key={bi}>
            {lines.map((l, li) => (
              <Fragment key={li}>
                {li > 0 && <br />}
                {inline(l.replace(/^#{1,4}\s+/, ""), `p${bi}-${li}`)}
              </Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}
