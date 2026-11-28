/**
 * An edit changes only the blocks the person touched. The stored text is the source: its blocks are found with the
 * Markdown lexer, the editor's document is compared to them block by block, and only the blocks that differ are
 * written again, so every other line keeps its exact bytes (its `*`, `_`, `<`, bullets, tables and spacing).
 */
import { Node as PmNode, type Schema } from '@tiptap/pm/model';
import type { JSONContent } from '@tiptap/core';

/** What the splice needs of the Markdown manager: its lexer, its reader and its writer. */
export interface MarkdownIO {
  instance: { lexer: (src: string) => { raw: string; type: string }[] };
  parse: (src: string) => JSONContent;
  serialize: (doc: JSONContent) => string;
}

interface Segment {
  /** The source text of one top-level block, or of the blank lines between two. */
  raw: string;
  /** The editor nodes it reads as, in the schema's own JSON, so they compare with the editor's. */
  nodes: string[];
}

const keyOf = (schema: Schema, json: JSONContent) => JSON.stringify(PmNode.fromJSON(schema, json).toJSON());
const EMPTY = JSON.stringify({ type: 'paragraph' });

/**
 * The text cut into blocks, each with the nodes it reads as. A block is read on its own; the blank lines between blocks
 * hold the empty paragraphs the whole text reads as, so they are taken from the whole text's reading. Null when the
 * two readings do not line up, which makes the caller write the whole text again.
 */
function segmentsOf(io: MarkdownIO, schema: Schema, src: string): Segment[] | null {
  const whole = (io.parse(src).content ?? []).map((n) => keyOf(schema, n));
  const segments: Segment[] = [];
  let at = 0;
  for (const t of io.instance.lexer(src)) {
    if (t.type === 'space') {
      let n = 0;
      while (whole[at + n] === EMPTY) n++;
      segments.push({ raw: t.raw, nodes: whole.slice(at, at + n) });
      at += n;
      continue;
    }
    const nodes = (io.parse(t.raw.replace(/\n+$/, '')).content ?? []).map((n) => keyOf(schema, n));
    if (nodes.some((k, i) => whole[at + i] !== k)) return null;
    segments.push({ raw: t.raw, nodes });
    at += nodes.length;
  }
  return at === whole.length ? segments : null;
}

const newlinesAfter = (s: string) => /\n*$/.exec(s)![0].length;
const newlinesBefore = (s: string) => /^\n*/.exec(s)![0].length;

/** `src` with the blocks that differ from `doc` written again; `src` itself when none differ. */
export function spliceEdit(io: MarkdownIO, schema: Schema, src: string, doc: JSONContent): string {
  const segments = segmentsOf(io, schema, src);
  const next = (doc.content ?? []).map((n) => keyOf(schema, n));
  // Blocks that do not line up with the text are written again whole.
  if (!segments) return next.length ? io.serialize(doc) : '';
  const flat = segments.flatMap((s, si) => s.nodes.map((key) => ({ key, si })));
  let head = 0;
  while (head < flat.length && head < next.length && flat[head].key === next[head]) head++;
  let tail = 0;
  while (tail < flat.length - head && tail < next.length - head && flat[flat.length - 1 - tail].key === next[next.length - 1 - tail]) tail++;
  if (head === flat.length && head === next.length) return src;

  // The segments that hold a changed old node are replaced whole; a segment shared with an unchanged node keeps it.
  const oldMid = flat.slice(head, flat.length - tail);
  const first = oldMid.length ? oldMid[0].si : head < flat.length ? flat[head].si : segments.length;
  // A block inserted between two nodes of one segment (two empty paragraphs of one run of blank lines) replaces that segment.
  const splits = !oldMid.length && head > 0 && head < flat.length && flat[head - 1].si === flat[head].si;
  const last = oldMid.length ? oldMid[oldMid.length - 1].si : splits ? first : first - 1;
  // Nodes of a replaced segment that were not changed are written again with it, so take them into the new middle.
  let keepBefore = 0;
  while (keepBefore < head && flat[head - 1 - keepBefore].si >= first) keepBefore++;
  let keepAfter = 0;
  while (keepAfter < tail && flat[flat.length - tail + keepAfter].si <= last) keepAfter++;
  const content = (doc.content ?? []).slice(head - keepBefore, next.length - tail + keepAfter);
  // The library writes an empty paragraph as nothing, so the ones at either end of what is written are counted here and
  // become the blank lines around it.
  const keys = content.map((n) => keyOf(schema, n));
  let lead = 0;
  while (lead < keys.length && keys[lead] === EMPTY) lead++;
  let trail = 0;
  while (trail < keys.length - lead && keys[keys.length - 1 - trail] === EMPTY) trail++;
  const core = content.slice(lead, content.length - trail);
  const written = core.length ? io.serialize({ type: 'doc', content: core }) : '';
  const before = segments.slice(0, first).map((s) => s.raw).join('');
  const after = segments.slice(last + 1).map((s) => s.raw).join('');
  const replaced = segments.slice(first, last + 1);
  // The text's last line break stays when its last block is the one written again.
  const ending = !after && replaced.length ? '\n'.repeat(Math.min(newlinesAfter(replaced[replaced.length - 1].raw), 1)) : '';
  if (!written && before && after) return lead ? before + gap(before, after, lead) + after : joinAround(before, after);
  if (!written && before) return before.replace(/\n+$/, '') + ending;
  if (!written) return after.replace(/^\n+/, '');
  return before + gap(before, written, lead) + written + ending + gap(written, after, trail) + after;
}

/** The line breaks that make `b` a block after `a` with `empties` empty paragraphs between: none where the text has them. */
const gap = (a: string, b: string, empties: number) => (a && b ? '\n'.repeat(Math.max(0, 2 + 2 * empties - newlinesAfter(a) - newlinesBefore(b))) : '');

/** The empty paragraphs a gap of `n` line breaks holds: two breaks end a block, and each further pair is one paragraph. */
const emptiesIn = (n: number) => Math.max(0, Math.floor((n - 2) / 2));

/**
 * What lies between two blocks once the one between them is gone: the gaps on both sides become one gap that holds both
 * sets of empty paragraphs, rather than the two gaps laid end to end, which would hold one empty paragraph too many.
 */
function joinAround(before: string, after: string): string {
  const [n1, n2] = [newlinesAfter(before), newlinesBefore(after)];
  if (n1 < 2 || n2 < 2) return before + gap(before, after, 0) + after;
  const drop = n1 + n2 - (2 + 2 * (emptiesIn(n1) + emptiesIn(n2)));
  const fromAfter = Math.min(drop, n2);
  return before.slice(0, before.length - (drop - fromAfter)) + after.slice(fromAfter);
}

/** The index of the editor block that holds a line (from 1) of the stored text; the last block for a line past the end. */
export function blockAtLine(io: MarkdownIO, schema: Schema, src: string, line: number): number {
  const breaks = (t: string) => t.split('\n').length - 1;
  // The line each segment's text starts on: a block begins on it, and the empty paragraphs of a run of blank lines sit
  // on the blank lines after it.
  let at = 1;
  let blocks = 0;
  for (const s of segmentsOf(io, schema, src) ?? []) {
    const gap = /^\n+$/.test(s.raw);
    const last = gap ? at + breaks(s.raw) - 1 : at + breaks(s.raw.replace(/\n+$/, ''));
    if (s.nodes.length && line <= last) return blocks;
    at += breaks(s.raw);
    blocks += s.nodes.length;
  }
  return Math.max(0, blocks - 1);
}
