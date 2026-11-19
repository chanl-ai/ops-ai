/**
 * The instruction document as data. A document is a view of stored fields (an agent's brief, or a skill's notes and
 * steps): text with `@kind:id` references and `{{dotted.name}}` variables inside it. This file turns those fields into
 * the editor's node tree and back, and says what each reference chip shows. Nothing here imports the editor, so the
 * stored format never depends on it.
 *
 * Token rules, which the service's parser has to share:
 *   - A reference is `@kind:id`. The id ends in a letter, digit or underscore, so the full stop after
 *     "…with @tool:open_dispute." is text. It does not start after a letter, digit, underscore or `@`.
 *   - A variable is `{{name}}` with a dotted name and no spaces inside the braces. Any other `{{` is text.
 */
import type { Ref, RefKind, ReferenceItem } from '@/lib/types/references';

export interface StepCheck {
  text: string;
  /** Set by the save: a rule the service runs, or a sentence the model judges. */
  by?: 'rule' | 'model' | null;
}

export interface IfNot {
  action: 'retry' | 'goto' | 'exit';
  /** 1-based, for `goto`. */
  step?: number | null;
  /** An exit name, for `exit`. */
  exit?: string | null;
  /** For `retry`. */
  retries?: number;
}

export interface StepValue {
  do: string;
  use?: Ref | null;
  check?: StepCheck | null;
  ifNot?: IfNot | null;
}

/** A heading the builder cannot rename or remove, and the text under it. `key` is the stored field, e.g. `brief.purpose`. */
export interface FieldBlock {
  kind: 'field';
  key: string;
  label: string;
  locked: true;
  text: string;
  placeholder?: string;
}

export interface ListBlock {
  kind: 'list';
  key: string;
  label: string;
  items: string[];
  placeholder?: string;
}

export interface StepsBlock {
  kind: 'steps';
  steps: StepValue[];
  placeholder?: string;
}

export type Block = FieldBlock | ListBlock | StepsBlock;

export interface DocumentValue {
  blocks: Block[];
}

export type Segment = { t: 'text'; text: string } | { t: 'ref'; kind: RefKind; id: string } | { t: 'var'; name: string };

/** One node of the editor's tree, in the shape its JSON takes. */
export interface DocNode {
  type: string;
  attrs?: Record<string, unknown>;
  content?: DocNode[];
  text?: string;
}

const TOKEN = /(?<![\w@])@(tool|knowledge|skill|agent|workflow):([A-Za-z0-9](?:[A-Za-z0-9_.-]{0,126}[A-Za-z0-9_])?)|\{\{([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\}\}/g;
/** Text that, written straight after a reference, would be read as more of its id. */
const EXTENDS_ID = /^[.-]*[A-Za-z0-9_]/;

export const refToken = (r: Ref) => `@${r.kind}:${r.id}`;

/** Stored text as the runs the editor draws: plain text, reference chips and variable chips. */
export function parseText(text: string): Segment[] {
  const out: Segment[] = [];
  let at = 0;
  for (const m of text.matchAll(TOKEN)) {
    if (m.index > at) out.push({ t: 'text', text: text.slice(at, m.index) });
    out.push(m[3] ? { t: 'var', name: m[3] } : { t: 'ref', kind: m[1] as RefKind, id: m[2] });
    at = m.index + m[0].length;
  }
  if (at < text.length) out.push({ t: 'text', text: text.slice(at) });
  return out;
}

/**
 * The stored text of those runs. A space is added where a reference would otherwise not read back as the same one:
 * before it when it follows a word, and after it when the next text would be taken as part of its id.
 */
export function serializeSegments(segments: Segment[]): string {
  let out = '';
  let afterRef = false;
  for (const s of segments) {
    if (s.t === 'text') {
      if (afterRef && EXTENDS_ID.test(s.text)) out += ' ';
      out += s.text;
      afterRef = false;
    } else if (s.t === 'var') {
      out += `{{${s.name}}}`;
      afterRef = false;
    } else {
      if (/[\w@]$/.test(out)) out += ' ';
      out += refToken(s);
      afterRef = true;
    }
  }
  return out;
}

const inline = (text: string): DocNode[] =>
  parseText(text).map((s) =>
    s.t === 'text' ? { type: 'text', text: s.text } : s.t === 'ref' ? { type: 'reference', attrs: { kind: s.kind, id: s.id } } : { type: 'variable', attrs: { name: s.name } },
  );

const textOf = (node: DocNode | undefined): string =>
  serializeSegments(
    (node?.content ?? []).map((n): Segment => {
      if (n.type === 'reference') return { t: 'ref', kind: n.attrs!.kind as RefKind, id: n.attrs!.id as string };
      if (n.type === 'variable') return { t: 'var', name: n.attrs!.name as string };
      return { t: 'text', text: n.text ?? '' };
    }),
  );

const textNode = (type: string, text: string, attrs?: Record<string, unknown>): DocNode => {
  const content = inline(text);
  return { type, ...(attrs ? { attrs } : {}), ...(content.length ? { content } : {}) };
};

function stepNode(s: StepValue): DocNode {
  const content: DocNode[] = [textNode('line', s.do)];
  if (s.check) content.push(textNode('check', s.check.text, { by: s.check.by ?? null }));
  if (s.ifNot) content.push({ type: 'ifNot', attrs: { value: s.ifNot } });
  return { type: 'step', attrs: { use: s.use ?? null }, content };
}

/** The editor's tree for a document. An empty list or an empty set of steps gets one blank line to type on. */
export function toEditorDoc(value: DocumentValue): DocNode {
  return {
    type: 'doc',
    content: value.blocks.map((b): DocNode => {
      if (b.kind === 'field') return { type: 'field', attrs: { key: b.key, label: b.label, placeholder: b.placeholder ?? null }, content: b.text.split('\n').map((p) => textNode('paragraph', p)) };
      if (b.kind === 'list') return { type: 'list', attrs: { key: b.key, label: b.label, placeholder: b.placeholder ?? null }, content: (b.items.length ? b.items : ['']).map((i) => textNode('item', i)) };
      return { type: 'steps', attrs: { placeholder: b.placeholder ?? null }, content: (b.steps.length ? b.steps : [{ do: '' }]).map(stepNode) };
    }),
  };
}

function stepValue(node: DocNode): StepValue {
  const parts = node.content ?? [];
  const check = parts.find((p) => p.type === 'check');
  const ifNot = parts.find((p) => p.type === 'ifNot');
  const use = node.attrs?.use as Ref | null | undefined;
  const by = check?.attrs?.by as StepCheck['by'];
  return {
    do: textOf(parts.find((p) => p.type === 'line')),
    ...(use ? { use } : {}),
    ...(check ? { check: { text: textOf(check), ...(by ? { by } : {}) } } : {}),
    ...(ifNot ? { ifNot: ifNot.attrs!.value as IfNot } : {}),
  };
}

const blank = (s: StepValue) => !s.do && !s.use && !s.check && !s.ifNot;

/**
 * The document the editor's tree holds. Blank list lines are left out, and steps that are one blank line are no
 * steps; a blank step among others is kept, since "go to step 3" counts it.
 */
export function fromEditorDoc(doc: DocNode): DocumentValue {
  return {
    blocks: (doc.content ?? []).map((n): Block => {
      const placeholder = n.attrs?.placeholder ? { placeholder: n.attrs.placeholder as string } : {};
      if (n.type === 'field') return { kind: 'field', key: n.attrs!.key as string, label: n.attrs!.label as string, locked: true, text: (n.content ?? []).map(textOf).join('\n'), ...placeholder };
      if (n.type === 'list') return { kind: 'list', key: n.attrs!.key as string, label: n.attrs!.label as string, items: (n.content ?? []).map(textOf).filter((t) => t.trim()), ...placeholder };
      const steps = (n.content ?? []).map(stepValue);
      return { kind: 'steps', steps: steps.length === 1 && blank(steps[0]) ? [] : steps, ...placeholder };
    }),
  };
}

const sameRef = (a: Ref, b: Ref) => a.kind === b.kind && a.id === b.id;

/** Every reference the document names, once each: the ids a page asks the names of. */
export function referencesIn(value: DocumentValue): Ref[] {
  const texts: string[] = [];
  const found: Ref[] = [];
  for (const b of value.blocks) {
    if (b.kind === 'field') texts.push(b.text);
    else if (b.kind === 'list') texts.push(...b.items);
    else
      for (const s of b.steps) {
        if (s.use) found.push(s.use);
        texts.push(s.do, s.check?.text ?? '');
      }
  }
  for (const t of texts) for (const s of parseText(t)) if (s.t === 'ref') found.push({ kind: s.kind, id: s.id });
  return found.filter((r, i) => found.findIndex((x) => sameRef(x, r)) === i);
}

export interface Chip {
  /** `loading` until the names have been asked for; `missing` when the answer does not hold this reference. */
  state: 'loading' | 'ok' | 'missing';
  label: string;
}

/**
 * What a reference chip shows. The document stores only the kind and id, so a renamed item shows its current name,
 * and one the answer leaves out (removed, or no longer visible to this person) shows as Missing.
 */
export function chipFor(ref: Ref, resolved: readonly ReferenceItem[] | undefined): Chip {
  if (!resolved) return { state: 'loading', label: ref.id };
  const item = resolved.find((i) => sameRef(i, ref));
  return item ? { state: 'ok', label: item.label } : { state: 'missing', label: `Missing: ${ref.id}` };
}

/** The references in the document that `resolved` does not hold; empty while the names are still loading. */
export const missingReferences = (value: DocumentValue, resolved: readonly ReferenceItem[] | undefined): Ref[] =>
  referencesIn(value).filter((r) => chipFor(r, resolved).state === 'missing');
