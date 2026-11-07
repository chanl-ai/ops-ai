// Where a record id breaks into words: snake_case, kebab-case, dotted and path-like ids.
const BREAK = /[_\-.:/]/;

/**
 * A long value shortened in the middle ("gr_no_…advice"), keeping whole words at each end: the start ends after a word
 * break near `head` characters and the end starts after one near `tail`, so an id is never cut mid-word. A value with
 * no break near either point is cut at the counts. A value the ellipsis would not shorten is returned whole.
 */
export function middleShorten(text: string, head = 6, tail = 4): string {
  if (text.length <= head + tail + 1) return text;
  let start = text.slice(0, head);
  for (let i = Math.min(text.length - 1, head + 4); i >= Math.ceil(head / 2); i--) {
    if (BREAK.test(text[i - 1] ?? '')) {
      start = text.slice(0, i);
      break;
    }
  }
  let end = text.slice(-tail);
  let best: string | null = null;
  for (let i = 1; i < text.length; i++) {
    if (!BREAK.test(text[i - 1])) continue;
    const word = text.slice(i);
    if (word.length >= Math.max(3, tail - 3) && word.length <= tail + 6 && (best === null || Math.abs(word.length - tail) < Math.abs(best.length - tail))) best = word;
  }
  if (best !== null) end = best;
  const short = `${start}…${end}`;
  return short.length < text.length ? short : text;
}
