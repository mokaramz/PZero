import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { ArdeaAvatar, ArdeaIllustration, ArdeaMark } from "./Ardea";
import { Markdown } from "./Markdown";

const md = (text: string) =>
  renderToStaticMarkup(
    <MemoryRouter>
      <Markdown text={text} />
    </MemoryRouter>,
  );

describe("Associate Markdown", () => {
  it("renders lists, emphasis and code without raw HTML", () => {
    const html = md("**Bold** and *it* with `code`\n\n- one\n- two\n\n1. first\n2. second\n\n<script>alert(1)</script>");
    expect(html).toContain("<strong>Bold</strong>");
    expect(html).toContain("<em>it</em>");
    expect(html).toContain("<code>code</code>");
    expect(html).toMatch(/<ul><li>one<\/li><li>two<\/li><\/ul>/);
    expect(html).toMatch(/<ol><li>first<\/li><li>second<\/li><\/ol>/);
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
  });
  it("keeps identifiers literal (no italics inside words)", () => {
    const html = md("Set DEEPINFRA_API_KEY and a*b*c");
    expect(html).toContain("DEEPINFRA_API_KEY");
    expect(html).not.toContain("<em>");
  });
  it("links internal pages only; external URLs stay visible, non-clickable text", () => {
    const html = md("[Open Lumenfold](/conviction?company=lumenfold) and [site](https://example.com) and [x](javascript:alert(1))");
    expect(html).toContain('href="/conviction?company=lumenfold"');
    expect(html).not.toContain('href="https://example.com"');
    expect(html).toContain("site (https://example.com)");
    expect(html).not.toContain('href="javascript');
  });
  it("a heading line becomes a small heading", () => {
    expect(md("## Manager gates")).toContain("<h4>Manager gates</h4>");
    expect(md("## Manager gates\nline two")).toContain("<p>Manager gates<br/>line two</p>");
  });
  it("a link to a retired Scout view keeps only its label: no link, no address (decision c)", () => {
    const html = md("[the item](/scout-intake?item=s-1), [signals](/scout-intake?tab=native) and [jobs](/scout-bridge)");
    expect(html).not.toContain("href");
    expect(html).not.toMatch(/scout/i);
    expect(html).toContain("the item");
    expect(html).toContain("signals");
    expect(html).toContain("jobs");
  });
});

describe("Ardea", () => {
  it("names the illustration for screen readers and hides decorative duplicates", () => {
    expect(renderToStaticMarkup(<ArdeaIllustration />)).toMatch(/role="img".*<title[^>]*>Ardea, the PZ Associate heron<\/title>/);
    const deco = renderToStaticMarkup(<ArdeaAvatar decorative />);
    expect(deco).toContain('aria-hidden="true"');
    expect(deco).not.toContain("<title");
    expect(renderToStaticMarkup(<ArdeaAvatar state="thinking" />)).toContain("PZ Associate — reading Project Zero");
    expect(renderToStaticMarkup(<ArdeaAvatar state="done" />)).toContain("PZ Associate — answer ready");
    expect(renderToStaticMarkup(<ArdeaAvatar state="uncertain" />)).toContain("PZ Associate — not certain");
    expect(renderToStaticMarkup(<ArdeaMark />)).toContain('aria-hidden="true"');
    expect(renderToStaticMarkup(<ArdeaMark title="Ardea" />)).toMatch(/role="img".*<title[^>]*>Ardea<\/title>/);
  });
  it("each state is a distinct, static pose (no animation element)", () => {
    const poses = (["ready", "thinking", "done", "uncertain"] as const).map((s) => renderToStaticMarkup(<ArdeaAvatar state={s} decorative />));
    expect(new Set(poses).size).toBe(4);
    for (const p of poses) expect(p).not.toMatch(/<animate|<set /);
  });
  it("the state shows as data-state; thinking lowers the lid, uncertain raises the plume", () => {
    expect(renderToStaticMarkup(<ArdeaAvatar state="done" decorative />)).toContain('data-state="done"');
    expect(renderToStaticMarkup(<ArdeaAvatar state="thinking" decorative />)).not.toContain("<circle cx=\"184.1\"");
    expect(renderToStaticMarkup(<ArdeaAvatar state="ready" decorative />)).toContain('cx="184.1"');
    expect(renderToStaticMarkup(<ArdeaAvatar state="uncertain" decorative />)).toContain("data-raised");
    expect(renderToStaticMarkup(<ArdeaAvatar state="ready" decorative />)).not.toContain("data-raised");
  });
  it("the mark is 3:1 at its size; the illustration enters once unless told not to", () => {
    expect(renderToStaticMarkup(<ArdeaMark size={12} />)).toMatch(/width="36" height="12"/);
    const still = renderToStaticMarkup(<ArdeaIllustration enter={false} />);
    const entering = renderToStaticMarkup(<ArdeaIllustration />);
    expect(entering).not.toBe(still);
  });
});
