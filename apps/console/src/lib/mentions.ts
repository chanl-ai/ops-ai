/**
 * How a mention (`@tool:order_lookup`) is written in stored text: the one grammar every reader of that text shares, the
 * service's `REF_TOKEN` (ops_contracts) in JavaScript. The editors, the Markdown reader, the save gate and the mock's
 * publish check all read mentions through this file.
 */
import type { Ref, RefKind } from '@/lib/types/references';

/** The reference itself, anchored nowhere: `@kind:id`. An id ends in a letter, digit or underscore, so a full stop after it is text. */
export const MENTION_SOURCE = String.raw`@(tool|knowledge|skill|agent|workflow):([A-Za-z0-9](?:[A-Za-z0-9_.\-]{0,126}[A-Za-z0-9_])?)`;
/**
 * A mention does not start after a letter, digit, underscore or `@`, in any script: the service reads stored text with
 * Unicode word characters, and JavaScript's `\w` is ASCII only.
 */
export const NOT_AFTER_WORD = String.raw`(?<![\p{L}\p{N}_@])`;

/** Text that ends in what a mention may not follow. */
export const ENDS_IN_WORD = /[\p{L}\p{N}_@]$/u;
const FROM_START = new RegExp(`^${MENTION_SOURCE}`, 'u');
const ANYWHERE = new RegExp(`${NOT_AFTER_WORD}${MENTION_SOURCE}`, 'gu');

export const mentionToken = (r: Ref) => `@${r.kind}:${r.id}`;

/** The mention at the start of `src`, given the text just before it; undefined when it would continue a word. */
export function mentionAt(src: string, before: string): (Ref & { raw: string }) | undefined {
  if (ENDS_IN_WORD.test(before)) return undefined;
  const m = FROM_START.exec(src);
  return m ? { kind: m[1] as RefKind, id: m[2], raw: m[0] } : undefined;
}

/** Every mention written in `text`, in order, each once. */
export function mentionsIn(text: string): Ref[] {
  const found = new Map<string, Ref>();
  for (const m of text.matchAll(ANYWHERE)) found.set(m[0], { kind: m[1] as RefKind, id: m[2] });
  return [...found.values()];
}
