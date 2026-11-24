import type { Extraction } from './types/extractions';
import type { FileData } from './types/files';

const pct = (n: number) => `${Math.floor(n * 100)}%`;

const NOT_READ_WHY: Record<string, string> = {
  cut_off: 'the model’s reply stopped at its length limit',
  empty: 'the model’s reply held no answer',
  declined: 'the model declined to read this file',
  filtered: 'the provider’s filter stopped the reply',
};

/**
 * Why a read waits for a person, in one line: each field it marked for a check and what marked it (read under the
 * floor, a type rule it broke, not found), or that Detect matched no type. Null when the read marked nothing, so the
 * page never says a person is needed without saying why.
 */
export function waitReason(read: Extraction | null | undefined): string | null {
  // A read no reply answered marks every field, which says nothing: its reason is the model's, and a person types the values.
  if (read?.outcome === 'incomplete') return `nothing was read, because ${NOT_READ_WHY[read.incomplete?.reason ?? ''] ?? 'no model reply answered'}`;
  const keys = read?.needsReview ?? [];
  if (!read || keys.length === 0) return null;
  if (keys.includes('documentType')) return 'the file matched none of the team’s document types';
  const floor = read.floor ?? null;
  const parts = keys.map((key) => {
    const f = read.fields?.[String(key)];
    if (!f) return `${key} needs a check`;
    if (f.rejected) return `${key} broke a rule (${f.rejected})`;
    if (f.value === null || f.value === undefined || f.confidence === null) return `${key} was not found`;
    return floor !== null && f.confidence < floor
      ? `${key} was read with ${pct(f.confidence)} confidence, under the ${pct(floor)} floor`
      : `${key} was read with ${pct(f.confidence)} confidence, under its type's threshold`;
  });
  return parts.join('; ');
}

/**
 * The header's line for a read that saved nothing on the file: a proposed read (no type yet, so nothing is recorded)
 * or a full-text read. Null when the file has its own Read as, or was never read.
 */
export function readBadge(data: FileData | null | undefined, latest: Extraction | null | undefined, textRead = false): string | null {
  if (data) return null;
  if (latest?.status === 'done' && latest.proposal) return 'Fields proposed · not saved as a type';
  if ((latest?.status === 'done' && typeof latest.text === 'string') || textRead) return 'Read as full text';
  return null;
}
