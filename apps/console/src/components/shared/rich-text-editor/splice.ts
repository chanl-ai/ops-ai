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
/** The line breaks that make `b` a block after `a`: two between blocks, none where the text already has them. */
const between = (a: string, b: string) => (a && b ? '\n'.repeat(Math.max(0, 2 - newlinesAfter(a) - newlinesBefore(b))) : '');

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
  const last = oldMid.length ? oldMid[oldMid.length - 1].si : first - 1;
  // Nodes of a replaced segment that were not changed are written again with it, so take them into the new middle.
  let keepBefore = 0;
  while (keepBefore < head && flat[head - 1 - keepBefore].si >= first) keepBefore++;
  let keepAfter = 0;
  while (keepAfter < tail && flat[flat.length - tail + keepAfter].si <= last) keepAfter++;
  const content = (doc.content ?? []).slice(head - keepBefore, next.length - tail + keepAfter);
  const written = content.length ? io.serialize({ type: 'doc', content }) : '';
  const before = segments.slice(0, first).map((s) => s.raw).join('');
  const after = segments.slice(last + 1).map((s) => s.raw).join('');
  const replaced = segments.slice(first, last + 1);
  // The text's last line break stays when its last block is the one written again.
  const ending = !after && replaced.length ? '\n'.repeat(Math.min(newlinesAfter(replaced[replaced.length - 1].raw), 1)) : '';
  return before + between(before, written) + written + (written ? ending : '') + between(written || before, after) + after;
}

/** The index of the editor block that holds a line (from 1) of the stored text; the last block for a line past the end. */
export function blockAtLine(io: MarkdownIO, schema: Schema, src: string, line: number): number {
  let seen = 1;
  let blocks = 0;
  for (const s of segmentsOf(io, schema, src) ?? []) {
    const lines = s.raw.split('\n').length - (s.raw.endsWith('\n') ? 1 : 0);
    if (s.nodes.length && line < seen + lines) return blocks;
    seen += lines;
    blocks += s.nodes.length;
  }
  return Math.max(0, blocks - 1);
}
