/** Legal-form words that never become initials ("Acme GmbH" → "AC"). */
const LEGAL_FORM = /^(gmbh|ag|sa|se|ug|ltd|inc|bv|ab|oy|sas|srl|plc|the)$/i;

/** Two initials from a name: the first letters of the first two words, else the first two letters of one word. */
export function initials(name: string): string {
  const words = String(name || "?")
    .replace(/[^\p{L}\p{N} ]/gu, " ")
    .split(/\s+/)
    .filter((w) => w && !LEGAL_FORM.test(w));
  return (words.length > 1 ? words[0][0] + words[1][0] : (words[0] ?? "?").slice(0, 2)).toUpperCase();
}
