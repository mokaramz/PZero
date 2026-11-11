/** The placeholder page of a view that is not ported to the rewrite yet: the shell and the link still work. */
export function NotPorted({ label }: { label: string }) {
  return (
    <section data-testid="not-ported" aria-label={label}>
      <p className="muted">{label} — not ported yet</p>
    </section>
  );
}
