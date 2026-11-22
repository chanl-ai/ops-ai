// The console's copy of the one name rule and slug maker, `ops_service_kit.names` (packages/ops_service_kit). The
// server stays the source: a field checks here so a person sees the server's sentence before sending, and
// names.test.ts pins the same slugs and messages the kit gives. A new hand-written slug or name validator is refused
// by scripts/check-standards.mjs (rule 16, `nameRule`).

const LINE_BREAKS = /[\n\v\f\r\u0085\u2028\u2029]/;
// What a reader cannot see: controls, format characters (zero-width space, bidi marks), separators, unassigned.
const INVISIBLE = /^[\p{Cc}\p{Cf}\p{Cn}\p{Co}\p{Cs}\p{Z}]*$/u;
const CONTROL = /\p{Cc}/u;

export const NAME_MESSAGES = {
  blank: 'The name cannot be blank.',
  lineBreak: 'The name must be on one line; remove the line break.',
  control: 'The name cannot hold a control character.',
} as const;

/** NFKC-normalised, runs of spaces and tabs made one space, trimmed; line breaks are kept so `nameProblem` sees them. */
export function tidyName(name: string): string {
  return name.normalize('NFKC').replace(/[ \t\u00a0\u3000]+/g, ' ').trim();
}

/** The server's refusal for this name, or undefined when it may be sent. `max` is the column's width. */
export function nameProblem(raw: string, max = 200): string | undefined {
  const name = tidyName(raw);
  if (!name || INVISIBLE.test(name)) return NAME_MESSAGES.blank;
  if (LINE_BREAKS.test(name)) return NAME_MESSAGES.lineBreak;
  if (CONTROL.test(name)) return NAME_MESSAGES.control;
  if ([...name].length > max) return `The name is at most ${max} characters.`;
  return undefined;
}

/** 32-bit FNV-1a over the lower-cased UTF-8 name, as 8 hex characters; the kit's `name_hash` gives the same. */
export function nameHash(text: string): string {
  let h = 0x811c9dc5;
  for (const b of new TextEncoder().encode(text.toLowerCase())) h = Math.imul(h ^ b, 0x01000193) >>> 0;
  return h.toString(16).padStart(8, '0');
}

const untranslated = (text: string) =>
  [...text].some((c) => /[\p{L}\p{N}]/u.test(c) && !/[a-zA-Z0-9]/.test(c.normalize('NFKD').replace(/[^\x00-\x7f]/g, '')));

/** The kit's `slugify`: Latin letters keep their base letter, a name with letters that have no ASCII spelling gets its
 * hash appended so such names stay distinct, and the result fits `width` less `reserve`. */
export function slugify(name: string, { width = 120, fallback = '', sep = '-', reserve = 0 } = {}): string {
  const text = name.normalize('NFKC');
  const ascii = text.normalize('NFKD').replace(/[^\x00-\x7f]/g, '').toLowerCase();
  const esc = sep.replace(/[.*+?^${}()|[\]\\-]/g, '\\$&');
  let base = sep ? ascii.replace(/[^a-z0-9]+/g, sep).replace(new RegExp(`^(?:${esc})+|(?:${esc})+$`, 'g'), '') : ascii.replace(/[^a-z0-9]+/g, '');
  let tail = '';
  if (untranslated(text)) {
    tail = nameHash(text);
    base = base || fallback;
  } else if (!base) return fallback;
  const room = width - reserve - (tail ? tail.length + sep.length : 0);
  base = base.slice(0, room);
  if (sep) base = base.replace(new RegExp(`(?:${esc})+$`), '');
  return tail && base ? `${base}${sep}${tail}` : tail || base;
}

/** A name field's error: `empty` (the field's own prompt, e.g. "Name the guardrail.") when blank, else the server's
 * refusal, else undefined. Every name field checks through this, so it refuses what the server refuses. */
export function nameError(raw: string, empty: string, max = 200): string | undefined {
  const problem = nameProblem(raw, max);
  return problem === NAME_MESSAGES.blank ? empty : problem;
}
