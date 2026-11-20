/**
 * A form's unsaved edits carried onto a newer saved copy. When someone else saves first, the page reads their copy;
 * each field the person changed since their own last read keeps the person's value, and every other field takes the
 * newer copy's. Fields are compared whole, so two people who changed the same field leave the person's value in it.
 */
export function keptEdits<T extends object>(readBefore: T, edited: T, newer: T): T {
  const out = { ...newer };
  for (const k of Object.keys(edited) as (keyof T)[]) if (JSON.stringify(edited[k]) !== JSON.stringify(readBefore[k])) out[k] = edited[k];
  return out;
}

/** A form's edits and the saved copy they were made on, held by a page while its form is drawn again. */
export interface Carried<T> {
  readBefore: T;
  edited: T;
}
