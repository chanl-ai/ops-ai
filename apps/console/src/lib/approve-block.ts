import type { DocumentRead } from '@/lib/types/domain';

/** A reviewer's corrections, by record index then field key, as typed. */
export type ReadEdits = Record<number, Record<string, string>>;
/** Key fields a reviewer has confirmed, by record index. */
export type ReadConfirmed = Record<number, string[]>;

/** How many key fields are still to confirm across the records; 0 when the type marks none. */
export function keyFieldsLeft(read: DocumentRead, confirmed: ReadConfirmed): number {
  const keys = read.schema.filter((f) => f.keyField).map((f) => f.key);
  return read.records.reduce((n, _, i) => n + keys.filter((k) => !confirmed[i]?.includes(k)).length, 0);
}

/** What Approve waits for while key fields are unconfirmed ("confirm 2 key fields first"); undefined when nothing does. */
export function keyFieldsBlock(read: DocumentRead | null | undefined, confirmed: ReadConfirmed): string | undefined {
  const left = read ? keyFieldsLeft(read, confirmed) : 0;
  return left ? `confirm ${left === 1 ? '1 key field' : `${left} key fields`} first` : undefined;
}

const blank = (v: unknown) => v === null || v === undefined || (typeof v === 'string' && !v.trim());

/** Required fields still empty on a read no reply answered, across its records, counting what the person typed over what was read. */
export function requiredFieldsLeft(read: DocumentRead, edits: ReadEdits): number {
  if (!read.notRead) return 0;
  const keys = read.schema.filter((f) => f.required).map((f) => f.key);
  return read.records.reduce((n, r, i) => n + keys.filter((k) => blank(edits[i]?.[k] ?? r.values[k])).length, 0);
}

/**
 * What Approve waits for, in the order the server refuses it: a task that can only be rejected, in the server's own
 * words (`approveRefused`); required fields of a read with no answer still to type; key fields still to confirm.
 * Undefined when nothing does.
 */
export function approveBlock(read: DocumentRead | null | undefined, confirmed: ReadConfirmed, edits: ReadEdits): string | undefined {
  if (!read) return undefined;
  if (read.approveRefused) return read.approveRefused.message;
  const left = requiredFieldsLeft(read, edits);
  if (left) return `type ${left === 1 ? '1 required field' : `${left} required fields`} first`;
  return keyFieldsBlock(read, confirmed);
}
