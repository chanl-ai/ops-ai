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

const group = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);

/**
 * As `keptEdits`, for a form whose fields may each hold a group of settings (limits, guardrails): a field that is a
 * group in all three copies is carried setting by setting, so a person who changed one limit keeps it and takes the
 * other person's change to another limit. Carried whole, the group would put the other person's settings back as
 * they were before their save.
 */
export function keptEditsByGroup<T extends object>(readBefore: T, edited: T, newer: T): T {
  const out = keptEdits(readBefore, edited, newer);
  for (const k of Object.keys(edited) as (keyof T)[]) {
    const [before, mine, theirs] = [readBefore[k], edited[k], newer[k]];
    if (group(before) && group(mine) && group(theirs)) out[k] = keptEdits(before, mine, theirs) as T[keyof T];
  }
  return out;
}

/** A form's edits and the saved copy they were made on, held by a page while its form is drawn again. */
export interface Carried<T> {
  readBefore: T;
  edited: T;
}
