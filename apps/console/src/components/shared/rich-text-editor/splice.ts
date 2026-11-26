/**
 * An edit changes only the blocks the person touched. The stored text is the source: its blocks are found with the
 * Markdown lexer, the editor's document is compared to them block by block, and only the blocks that differ are
 * written again, so every other line keeps its exact bytes (its `*`, `_`, `<`, bullets and spacing).
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
  /** The source text of one top-level block, with the blank lines after it. */
  raw: string;
  /** The editor nodes it reads as, in the schema's own JSON, so they compare with the editor's. */
  nodes: string[];
}

const keyOf = (schema: Schema, json: JSONContent) => JSON.stringify(PmNode.fromJSON(schema, json).toJSON());

function segmentsOf(io: MarkdownIO, schema: Schema, src: string): Segment[] {
  // Blank lines between blocks are a token of their own and read as no node; trailing ones are not part of a block.
  return io.instance.lexer(src).map((t) => ({ raw: t.raw, nodes: t.type === 'space' ? [] : (io.parse(t.raw.replace(/\n+$/, '')).content ?? []).map((n) => keyOf(schema, n)) }));
}

/** `src` with the blocks that differ from `doc` written again; `src` itself when none differ. */
export function spliceEdit(io: MarkdownIO, schema: Schema, src: string, doc: JSONContent): string {
  const segments = segmentsOf(io, schema, src);
  const flat = segments.flatMap((s, si) => s.nodes.map((key) => ({ key, si })));
  const next = (doc.content ?? []).map((n) => keyOf(schema, n));
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
  const trailing = replaced.length ? (/\n*$/.exec(replaced[replaced.length - 1].raw)?.[0] ?? '') : '';
  // A replaced block keeps the blank lines it had after it (a paragraph has none: the lexer holds them as their own token).
  const gap = replaced.length ? trailing : after ? '\n\n' : '';
  const sep = !replaced.length && before && !before.endsWith('\n\n') ? (before.endsWith('\n') ? '\n' : '\n\n') : '';
  return before + sep + written + (written ? gap : '') + after;
}
