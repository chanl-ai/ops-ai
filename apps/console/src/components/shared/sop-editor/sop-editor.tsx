'use client';

import * as React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { TriangleAlert } from 'lucide-react';
import { indentLess, indentMore, insertNewlineAndIndent, history, historyKeymap, defaultKeymap } from '@codemirror/commands';
import { indentUnit } from '@codemirror/language';
import { EditorState, Prec, RangeSetBuilder, StateEffect, StateField, type Extension } from '@codemirror/state';
import { Decoration, type DecorationSet, EditorView, highlightActiveLine, hoverTooltip, keymap, lineNumbers, placeholder as placeholderText, showTooltip, type Tooltip, ViewPlugin, type ViewUpdate, WidgetType } from '@codemirror/view';

import { CaretMenu, type MenuRow, type MenuSection } from '@/components/shared/caret-menu';
import { chipFor, parseText, refToken } from '@/components/shared/instruction-document/document-model';
import { KIND_ICON, KIND_LABEL } from '@/components/shared/reference-kinds';
import { HOW_SAYS } from './how';
import { badgeVariants } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { referenceGroupsFor, referenceOptionsFor, useGroupedOptionSearch, useOptionSearch } from '@/hooks/options-queries';
import type { Ref, ReferenceContext, ReferenceItem, RefKind } from '@/lib/types/references';
import type { SkillTextReading } from '@/lib/types/skills';

const UNIT = '    ';
/** Offered after `if ` once what the tool above returns is listed: conditions the agent decides from the conversation. */
const OWN_WORDS = ['they want a refund', 'they sound upset', 'they ask for a person', 'they have already tried this'];

export interface SopEditorHandle {
  /** Puts the caret at the start of a line (from 1) and scrolls it into view. */
  focusLine(line: number): void;
  /** Types `text` at the caret, as a person would, so `@` and `if ` open their menus. */
  insert(text: string): void;
}

export interface SopEditorProps {
  value: string;
  onChange: (text: string) => void;
  readOnly?: boolean;
  /** The service's reading of `readingFor`: line kinds, how each condition is decided, hints, and what each tool returns. */
  reading?: SkillTextReading;
  readingFor?: string;
  /** The current names of what the text mentions; undefined while loading. One left out is drawn as missing. */
  labels?: readonly ReferenceItem[];
  /** Whose mentions the `@` list searches: the skill or agent being edited. */
  context: ReferenceContext;
  placeholder?: string;
  controls?: React.Ref<SopEditorHandle>;
  ariaLabel?: string;
}

interface Drawn {
  reading?: SkillTextReading;
  /** The reading belongs to the text as it is now: its line marks still line up. */
  current: boolean;
  labels?: readonly ReferenceItem[];
}

const setDrawn = StateEffect.define<Drawn>();
const drawnField = StateField.define<Drawn>({
  create: () => ({ current: false }),
  update: (v, tr) => {
    for (const e of tr.effects) if (e.is(setDrawn)) return e.value;
    return tr.docChanged ? { ...v, current: false } : v;
  },
});

const ICONS = new Map<RefKind | 'missing', string>();
function iconHtml(kind: RefKind | 'missing'): string {
  if (!ICONS.has(kind)) {
    const Icon = kind === 'missing' ? TriangleAlert : KIND_ICON[kind];
    ICONS.set(kind, renderToStaticMarkup(<Icon className="size-3" aria-hidden />));
  }
  return ICONS.get(kind)!;
}

/** A mention as one atomic badge: the console's Badge, by its class names, since a widget is plain DOM. */
class MentionWidget extends WidgetType {
  constructor(
    readonly ref: Ref,
    readonly label: string,
    readonly state: 'loading' | 'ok' | 'missing',
  ) {
    super();
  }
  eq(other: MentionWidget) {
    return other.label === this.label && other.state === this.state && refToken(other.ref) === refToken(this.ref);
  }
  toDOM() {
    const el = document.createElement('span');
    const missing = this.state === 'missing';
    el.className = cn(badgeVariants({ variant: missing ? 'outline' : 'secondary' }), 'mx-0.5 align-baseline font-normal', missing && 'border-destructive text-destructive line-through', this.state === 'loading' && 'text-muted-foreground');
    el.innerHTML = iconHtml(missing ? 'missing' : this.ref.kind);
    el.append(document.createTextNode(missing ? this.ref.id : this.label));
    el.dataset.testid = missing ? 'sop-mention-missing' : 'sop-mention';
    // A wrapped line's hanging indent is inherited by inline blocks; a badge draws from its own left edge.
    el.style.textIndent = '0';
    el.title = `${missing ? `${this.ref.id} no longer exists` : this.label}. Click it, or press Alt+Enter beside it, to replace or remove it.`;
    // The title shows only on hover; a screen reader and a touch reader get the same words from the label.
    el.setAttribute('aria-label', el.title);
    el.setAttribute('role', 'button');
    el.style.cursor = 'pointer';
    return el;
  }
  ignoreEvent() {
    return false;
  }
}

class HowWidget extends WidgetType {
  constructor(readonly how: 'checked' | 'agent') {
    super();
  }
  eq(other: HowWidget) {
    return other.how === this.how;
  }
  toDOM() {
    const el = document.createElement('span');
    el.className = 'ml-2 select-none text-xs text-muted-foreground';
    el.textContent = this.how === 'checked' ? 'checked' : 'agent decides';
    el.dataset.testid = 'sop-condition-how';
    el.title = HOW_SAYS[this.how];
    el.setAttribute('aria-label', `${el.textContent}: ${HOW_SAYS[this.how]}`);
    return el;
  }
}

const GUIDE = Decoration.mark({ class: 'sop-guide' });
const indentOf = (text: string) => text.length - text.trimStart().length;
const levels = (text: string) => Math.floor(text.slice(0, indentOf(text)).replace(/\t/g, UNIT).length / UNIT.length);
const KEYWORD = { if: /^if\b/i, else: /^(?:else|otherwise)\b/i, stop: /^stop\b/ } as const;
/** The reader's own syntax for a line that opens a path, used until its reading of the text arrives. */
const OPENS = /^\s*(?:if\s.+|else|otherwise)\s*:\s*$/i;
const MENTION_AT = /^@(?:tool|knowledge|skill|agent|workflow):[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,126}[A-Za-z0-9_])?/;

/** Mentions, guides, keywords, condition labels and hint underlines, drawn from the text and the service's reading. */
function decorate(state: EditorState): { all: DecorationSet; atomic: DecorationSet } {
  const drawn = state.field(drawnField);
  const marks = drawn.current && drawn.reading ? new Map(drawn.reading.lines.map((l) => [l.line, l])) : new Map();
  // Hints get the wavy line; a removed mention is already drawn red on its badge.
  const hinted = new Set(drawn.current && drawn.reading ? drawn.reading.hints.map((h) => h.line) : []);
  const all = new RangeSetBuilder<Decoration>();
  const atomic = new RangeSetBuilder<Decoration>();
  for (let n = 1; n <= state.doc.lines; n++) {
    const line = state.doc.line(n);
    const mark = marks.get(n);
    // The reader is the one owner of indent: its depth counts pasted spaces as the save does.
    const depth = mark?.depth ?? levels(line.text);
    // A wrapped line keeps its indent: the guides take 1.5rem a step, and the wrap hangs under the text.
    if (depth > 0) all.add(line.from, line.from, Decoration.line({ attributes: { style: `padding-left:calc(${depth} * 1.5rem + 0.25rem);text-indent:calc(${depth} * -1.5rem)` } }));
    const lead = indentOf(line.text);
    const body = line.text.slice(lead);
    const kw = mark && (mark.kind === 'if' || mark.kind === 'else' || mark.kind === 'stop') ? body.match(KEYWORD[mark.kind as keyof typeof KEYWORD]) : null;
    const pieces: { from: number; to: number; deco: Decoration; atomic?: boolean }[] = [];
    // One guide per indent step, drawn on the leading whitespace itself, so it lines up in any font.
    const each = depth ? Math.max(1, Math.floor(lead / depth)) : 0;
    for (let k = 0, at = 0; k < depth && at < lead; k++) {
      const size = k === depth - 1 ? lead - at : Math.min(each, lead - at);
      pieces.push({ from: line.from + at, to: line.from + at + size, deco: GUIDE });
      at += size;
    }
    if (kw) pieces.push({ from: line.from + lead, to: line.from + lead + kw[0].length, deco: Decoration.mark({ class: 'sop-keyword' }) });
    if (hinted.has(n) && body.trim()) pieces.push({ from: line.from + lead, to: line.to, deco: Decoration.mark({ class: 'sop-hint' }) });
    let at = line.from;
    for (const seg of parseText(line.text)) {
      const size = seg.t === 'text' ? seg.text.length : seg.t === 'var' ? seg.name.length + 4 : refToken(seg).length;
      if (seg.t === 'ref') {
        const chip = chipFor(seg, drawn.labels);
        pieces.push({ from: at, to: at + size, deco: Decoration.replace({ widget: new MentionWidget(seg, chip.label, chip.state) }), atomic: true });
      }
      at += size;
    }
    // A decoration set is built in document order: marks, then replacements, sorted by where they start.
    pieces.sort((a, b) => a.from - b.from || Number(!!a.atomic) - Number(!!b.atomic));
    for (const p of pieces) {
      all.add(p.from, p.to, p.deco);
      if (p.atomic) atomic.add(p.from, p.to, p.deco);
    }
    if (mark?.kind === 'if' && mark.how) all.add(line.to, line.to, Decoration.widget({ widget: new HowWidget(mark.how), side: 1 }));
  }
  return { all: all.finish(), atomic: atomic.finish() };
}

const drawing = ViewPlugin.fromClass(
  class {
    sets: { all: DecorationSet; atomic: DecorationSet };
    constructor(view: EditorView) {
      this.sets = decorate(view.state);
    }
    update(u: ViewUpdate) {
      if (u.docChanged || u.transactions.some((t) => t.effects.some((e) => e.is(setDrawn)))) this.sets = decorate(u.state);
    }
  },
  { decorations: (p) => p.sets.all, provide: (p) => EditorView.atomicRanges.of((view) => view.plugin(p)?.sets.atomic ?? Decoration.none) },
);

/** The card on a hinted line: what the agent will do with it. Styled as the console's HoverCard. */
function hintCard(state: EditorState, pos: number): Tooltip | null {
  const drawn = state.field(drawnField);
  if (!drawn.current || !drawn.reading) return null;
  const line = state.doc.lineAt(pos);
  const notes = [...drawn.reading.errors, ...drawn.reading.hints].filter((h) => h.line === line.number);
  if (!notes.length) return null;
  return {
    pos: line.from + indentOf(line.text),
    end: line.to,
    above: true,
    create: () => {
      const dom = document.createElement('div');
      dom.className = 'z-50 w-80 max-w-[calc(100vw-2rem)] rounded-md border bg-popover p-3 text-sm text-popover-foreground shadow-md';
      dom.dataset.testid = 'sop-hint-card';
      for (const n of notes) {
        const p = document.createElement('p');
        p.textContent = n.message;
        p.className = 'leading-snug [&+p]:mt-2';
        dom.append(p);
      }
      return { dom };
    },
  };
}

const hints = hoverTooltip((view, pos) => hintCard(view.state, pos));

/** A tap or click on a hinted line pins its card open: a phone has no hover. It closes on the next edit or a tap elsewhere. */
const pinHint = StateEffect.define<number | null>();
const pinnedHint = StateField.define<Tooltip | null>({
  create: () => null,
  update: (v, tr) => {
    for (const e of tr.effects) if (e.is(pinHint)) return e.value === null ? null : hintCard(tr.state, e.value);
    return tr.docChanged ? null : v;
  },
  provide: (f) => showTooltip.from(f),
});

const theme = EditorView.theme({
  '&': { fontSize: '0.875rem', backgroundColor: 'transparent' },
  '&.cm-focused': { outline: 'none' },
  '.cm-content': { fontFamily: 'inherit', lineHeight: '1.75rem', padding: '0.5rem 0', caretColor: 'var(--foreground)' },
  '.cm-line': { padding: '0 0.75rem 0 0.25rem' },
  '.cm-gutters': { backgroundColor: 'transparent', border: 'none', color: 'var(--muted-foreground)', fontSize: '0.75rem' },
  '.cm-lineNumbers .cm-gutterElement': { padding: '0 0.75rem 0 0.5rem', minWidth: '2.25rem', lineHeight: '1.75rem' },
  '.cm-activeLine': { backgroundColor: 'color-mix(in oklab, var(--muted) 60%, transparent)' },
  '.cm-activeLineGutter': { backgroundColor: 'transparent' },
  '.cm-placeholder': { color: 'var(--muted-foreground)', fontStyle: 'italic', whiteSpace: 'pre-wrap' },
  '.cm-scroller': { fontFamily: 'inherit' },
  '.sop-guide': { boxShadow: 'inset 1px 0 0 var(--border)', display: 'inline-block', minWidth: '1.5rem', whiteSpace: 'pre', textIndent: '0' },
  '.sop-keyword': { color: 'var(--primary)', fontWeight: '600', fontFamily: 'var(--font-mono, ui-monospace, monospace)' },
  '.sop-hint': { textDecoration: 'underline wavy', textDecorationColor: 'var(--chart-4, #d97706)', textUnderlineOffset: '4px' },
  '.cm-tooltip': { border: 'none', backgroundColor: 'transparent' },
});

/** Enter at the end of a line that opens a path (`if …:`, `else:`) opens the indented block under it; after any other
 * line ending in a colon (“Note:”) it starts a plain line at the same indent. */
function enter(view: EditorView): boolean {
  const { state } = view;
  const range = state.selection.main;
  if (!range.empty) return false;
  const line = state.doc.lineAt(range.head);
  const before = line.text.slice(0, range.head - line.from);
  const drawn = state.field(drawnField);
  const kind = drawn.current ? drawn.reading?.lines.find((l) => l.line === line.number)?.kind : undefined;
  const opens = kind ? kind === 'if' || kind === 'else' : OPENS.test(before);
  if (!opens || !before.trimEnd().endsWith(':')) return insertNewlineAndIndent(view);
  const insert = `\n${before.slice(0, indentOf(before))}${UNIT}`;
  view.dispatch({ changes: { from: range.head, insert }, selection: { anchor: range.head + insert.length }, scrollIntoView: true, userEvent: 'input' });
  return true;
}

type Menu = { kind: 'mention' | 'if'; from: number; to: number; query: string };

/** What the caret is typing into: an `@` mention, or a condition after a freshly typed `if ` (`armed`, the line it was
 * typed on): moving onto a sentence that starts with “if” opens nothing. */
function menuAt(state: EditorState, armed: number | null): Menu | null {
  const range = state.selection.main;
  if (!range.empty) return null;
  const line = state.doc.lineAt(range.head);
  const before = line.text.slice(0, range.head - line.from);
  const at = before.match(/(?<![\p{L}\p{N}_@])@([\p{L}\p{N}_ -]{0,40})$/u);
  if (at && !at[1].includes(':')) return { kind: 'mention', from: range.head - at[0].length, to: range.head, query: at[1].trim() };
  const cond = before.match(/^(\s*if\s+)([^:]*)$/i);
  if (cond && armed === line.number) return { kind: 'if', from: line.from + cond[1].length, to: range.head, query: cond[2] };
  return null;
}

/**
 * A skill written as plain text, like a prompt, on CodeMirror 6. `@` mentions draw as badges and are deleted whole;
 * an indented `if …:` block is a path; the service's reading (`reading`) adds the checked or agent-decides label to
 * each condition and a wavy underline with a hover card to each hint. Nothing here reads the text's structure: the
 * service's reader is the one owner of that, and this draws what it said.
 */
export function SopEditor({ value, onChange, readOnly = false, reading, readingFor, labels, context, placeholder, controls, ariaLabel = 'Skill text' }: SopEditorProps) {
  const host = React.useRef<HTMLDivElement>(null);
  const view = React.useRef<EditorView | null>(null);
  const latest = React.useRef({ onChange, reading });
  latest.current = { onChange, reading };
  const [menu, setMenu] = React.useState<Menu | null>(null);
  // The `@` list narrowed to one kind (“More tools…”), paged as it scrolls; null shows every kind's first rows.
  const [scope, setScope] = React.useState<RefKind | null>(null);
  const [active, setActive] = React.useState('');
  const menuId = React.useId();
  const menuRef = React.useRef<{ menu: Menu | null; rows: MenuRow[]; active: string; pick: (row: MenuRow) => void }>({ menu: null, rows: [], active: '', pick: () => {} });
  // The line an `if ` was just typed on: the condition list opens only there.
  const armed = React.useRef<number | null>(null);
  // Esc, then Tab within two seconds, leaves the editor; Tab otherwise indents.
  const escaped = React.useRef(0);
  // The condition list's highlight counts only once an arrow key moved it: the list's own first-row highlight does not.
  const chose = React.useRef(false);
  // A clicked badge's menu: change what it mentions, or take it out.
  const [badge, setBadge] = React.useState<{ from: number; to: number } | null>(null);
  const [badgeActive, setBadgeActive] = React.useState('replace');
  const badgeRef = React.useRef<{ open: boolean; active: string; pick: (key: string) => void }>({ open: false, active: 'replace', pick: () => {} });

  React.useEffect(() => {
    if (!host.current) return;
    const keys: Extension = Prec.highest(
      keymap.of([
        { key: 'ArrowDown', run: () => moveBadge() || move(1) },
        { key: 'ArrowUp', run: () => moveBadge() || move(-1) },
        { key: 'Enter', run: () => pickBadge() || pickActive() },
        { key: 'Tab', run: () => pickActive() },
        // The keyboard's way to a badge's menu (a click opens it too): Alt+Enter with the caret beside a mention.
        { key: 'Alt-Enter', run: (v) => openBadgeAtCaret(v) },
        { key: 'Shift-F10', run: (v) => openBadgeAtCaret(v) },
        {
          key: 'Escape',
          run: () => {
            if (badgeRef.current.open) return (setBadge(null), true);
            if (menuRef.current.menu) return (setMenu(null), (armed.current = null), true);
            escaped.current = Date.now();
            return false;
          },
        },
      ]),
    );
    const move = (by: number) => {
      const { menu: m, rows, active: a } = menuRef.current;
      if (!m || !rows.length) return false;
      const i = rows.findIndex((r) => r.key === a);
      chose.current = true;
      setActive(rows[i < 0 ? (by > 0 ? 0 : rows.length - 1) : (i + by + rows.length) % rows.length].key);
      return true;
    };
    const moveBadge = () => {
      if (!badgeRef.current.open) return false;
      setBadgeActive((a) => (a === 'replace' ? 'remove' : 'replace'));
      return true;
    };
    const pickBadge = () => {
      if (!badgeRef.current.open) return false;
      badgeRef.current.pick(badgeRef.current.active);
      return true;
    };
    const openBadgeAtCaret = (v: EditorView) => {
      const head = v.state.selection.main.head;
      const line = v.state.doc.lineAt(head);
      for (const m of line.text.matchAll(new RegExp(MENTION_AT.source.slice(1), 'g'))) {
        const from = line.from + (m.index ?? 0);
        const to = from + m[0].length;
        if (head >= from && head <= to + 1) return (setBadgeActive('replace'), setBadge({ from, to }), true);
      }
      return false;
    };
    const leaving = () => Date.now() - escaped.current < 2000;
    const pickActive = () => {
      const { menu: m, rows, active: a, pick } = menuRef.current;
      const row = m && rows.find((r) => r.key === a);
      // Enter or Tab at the end of a sentence starting “if” is a new line or an indent, unless a row was arrowed to.
      if (!row || (m.kind === 'if' && !chose.current)) return false;
      pick(row);
      return true;
    };
    const v = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: value,
        extensions: [
          keys,
          lineNumbers(),
          highlightActiveLine(),
          history(),
          indentUnit.of(UNIT),
          EditorState.tabSize.of(4),
          keymap.of([{ key: 'Enter', run: enter }, { key: 'Tab', run: (v) => !leaving() && indentMore(v), shift: (v) => !leaving() && indentLess(v) }, ...defaultKeymap, ...historyKeymap]),
          EditorView.lineWrapping,
          EditorState.readOnly.of(readOnly),
          EditorView.editable.of(!readOnly),
          EditorView.contentAttributes.of({ 'aria-label': ariaLabel, 'aria-multiline': 'true', 'data-testid': 'sop-editor-content' }),
          drawnField,
          drawing,
          hints,
          pinnedHint,
          EditorView.domEventHandlers({
            click: (e, v) => {
              const el = (e.target as HTMLElement).closest('[data-testid="sop-mention"],[data-testid="sop-mention-missing"]');
              if (el && !readOnly) {
                const from = v.posAtDOM(el);
                const token = v.state.doc.sliceString(from, from + 140).match(MENTION_AT);
                if (token) return (setBadgeActive('replace'), setBadge({ from, to: from + token[0].length }), true);
              }
              const pos = v.posAtCoords({ x: e.clientX, y: e.clientY });
              v.dispatch({ effects: pinHint.of(pos === null ? null : pos) });
              return false;
            },
          }),
          theme,
          ...(placeholder ? [placeholderText(placeholder)] : []),
          EditorView.updateListener.of((u) => {
            if (u.docChanged) latest.current.onChange(u.state.doc.toString());
            const head = u.state.selection.main.head;
            const here = u.state.doc.lineAt(head);
            if (u.transactions.some((t) => t.isUserEvent('input.type')) && /^\s*if $/i.test(here.text.slice(0, head - here.from))) armed.current = here.number;
            else if (armed.current !== null && armed.current !== here.number) armed.current = null;
            if (u.docChanged || u.selectionSet) {
              const next = u.view.hasFocus || u.docChanged ? menuAt(u.state, armed.current) : null;
              setMenu((m) => {
                if (next && m && next.kind === m.kind && next.from === m.from && next.query === m.query) return m;
                if (!next || !m || next.kind !== m.kind || next.from !== m.from) chose.current = false;
                return next;
              });
            }
          }),
        ],
      }),
    });
    view.current = v;
    return () => {
      v.destroy();
      view.current = null;
    };
    // The editor is made once; the text from outside is pushed in by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readOnly]);

  // A value set from outside (a discard, a reload) replaces the text; the editor's own typing already matches it.
  React.useEffect(() => {
    const v = view.current;
    if (v && v.state.doc.toString() !== value) v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: value } });
  }, [value]);

  React.useEffect(() => {
    const v = view.current;
    if (!v) return;
    v.dispatch({ effects: setDrawn.of({ reading, labels, current: !!reading && readingFor === v.state.doc.toString() }) });
  }, [reading, readingFor, labels]);

  React.useImperativeHandle(controls, () => ({
    focusLine: (n) => {
      const v = view.current;
      if (!v) return;
      const line = v.state.doc.line(Math.min(Math.max(n, 1), v.state.doc.lines));
      const at = line.from + indentOf(line.text);
      // Centred, so on a phone the line is not left under the keyboard or the bottom edge.
      v.dispatch({ selection: { anchor: at }, effects: [EditorView.scrollIntoView(at, { y: 'center' }), pinHint.of(at)] });
      v.focus();
      v.dom.closest('[data-testid="sop-editor"]')?.scrollIntoView({ block: 'nearest' });
    },
    insert: (text) => {
      const v = view.current;
      if (!v) return;
      const at = v.state.selection.main.head;
      v.dispatch({ changes: { from: at, insert: text }, selection: { anchor: at + text.length }, userEvent: 'input.type' });
      v.focus();
    },
  }));

  // The @ list: the first rows of every kind, or every row of one kind page by page; both searched on the server.
  const mentionQuery = menu?.kind === 'mention' ? menu.query : null;
  React.useEffect(() => {
    if (mentionQuery === null) setScope(null);
  }, [mentionQuery]);
  const groupsSource = React.useMemo(() => referenceGroupsFor(context), [context]);
  const scopedSource = React.useMemo(() => referenceOptionsFor(context, scope ?? 'tool'), [context, scope]);
  const grouped = useGroupedOptionSearch(groupsSource, mentionQuery ?? '', mentionQuery !== null && scope === null && !readOnly);
  const scoped = useOptionSearch(scopedSource, mentionQuery ?? '', mentionQuery !== null && scope !== null && !readOnly);
  const found = scope === null ? grouped : scoped;
  const foundStatus: 'loading' | 'ready' | 'error' = found.isError ? 'error' : found.data === undefined ? 'loading' : 'ready';
  const loadMore = React.useCallback(() => {
    if (scope !== null && scoped.hasNextPage && !scoped.isFetchingNextPage) void scoped.fetchNextPage();
  }, [scope, scoped]);

  const replace = React.useCallback((m: Menu, insert: string) => {
    const v = view.current;
    if (!v) return;
    v.dispatch({ changes: { from: m.from, to: m.to, insert }, selection: { anchor: m.from + insert.length }, userEvent: 'input.complete' });
    setMenu(null);
    armed.current = null;
    chose.current = false;
    v.focus();
  }, []);

  const sections = React.useMemo<MenuSection[]>(() => {
    if (!menu) return [];
    if (menu.kind === 'mention') {
      const row = (o: { id: string; label: string; hint?: string | null; disabled?: string | null }) => ({ key: o.id, label: o.label, icon: KIND_ICON[o.id.split(':')[0] as RefKind], trailing: o.hint, disabled: o.disabled, pick: () => {} });
      if (scope !== null) {
        const rows = (scoped.data?.pages ?? []).flatMap((p) => p.data).map(row);
        return [{ label: KIND_LABEL[scope], rows: [{ key: 'back', label: 'Every kind', trailing: 'back', pick: () => {} }, ...rows] }];
      }
      return (grouped.data ?? []).map((g) => ({
        label: g.label,
        rows: [...g.page.data.map(row), ...(g.page.nextCursor ? [{ key: `more:${g.group}`, label: `More ${g.label.toLowerCase()}…`, trailing: 'see all', pick: () => {} }] : [])],
      }));
    }
    // After `if `: what the tool above returns, checked exactly, then words the agent decides.
    const v = view.current;
    const r = latest.current.reading;
    let tool: string | null = null;
    if (v && r) {
      const here = v.state.doc.lineAt(menu.from).number;
      for (let n = here - 1; n >= 1 && !tool; n--) tool = r.lines.find((l) => l.line === n)?.tool ?? null;
    }
    const q = menu.query.trim().toLowerCase();
    const fits = (p: string) => !q || p.toLowerCase().includes(q);
    const name = tool ? (labels?.find((i) => `@${i.kind}:${i.id}` === tool)?.label ?? tool.split(':')[1]) : null;
    const out: MenuSection[] = [];
    const returned = (tool && r?.phrases[tool]) || [];
    const fromTool = returned.filter(fits).map((p) => ({ key: `checked:${p}`, label: p, trailing: 'checked', pick: () => {} }));
    if (fromTool[0]) out.push({ label: `From ${name}, checked`, rows: fromTool });
    const own = OWN_WORDS.filter(fits);
    if (q && !returned.includes(q)) own.unshift(menu.query.trim());
    if (own.length) out.push({ label: 'In your own words, the agent decides', rows: own.map((p) => ({ key: `agent:${p}`, label: p, trailing: 'agent decides', pick: () => {} })) });
    return out;
  }, [menu, grouped.data, scoped.data, scope, labels]);
  const rows = React.useMemo(() => sections.flatMap((s) => s.rows.filter((r) => !r.disabled)), [sections]);
  // The `@` list highlights its first row; the condition list highlights none until an arrow key does, so Enter at the
  // end of a sentence starting “if” is a new line, never a path made from the typed words.
  const firstActive = menu?.kind === 'mention';
  React.useEffect(() => {
    if (rows.some((r) => r.key === active)) return;
    setActive(firstActive && rows.length ? (rows.find((r) => r.key !== 'back') ?? rows[0]).key : '');
  }, [rows, active, firstActive]);

  const pick = React.useCallback(
    (row: MenuRow) => {
      if (!menu) return;
      if (menu.kind === 'mention') {
        // “More tools…” narrows the list to that kind and “Every kind” widens it again; the caret stays where it was.
        if (row.key === 'back') return (setScope(null), setActive(''));
        if (row.key.startsWith('more:')) return (setScope(row.key.slice(5) as RefKind), setActive(''));
        const [kind, ...rest] = row.key.split(':');
        return replace(menu, `${refToken({ kind: kind as RefKind, id: rest.join(':') })} `);
      }
      const phrase = row.label.replace(/\s*…$/, '');
      // A phrase that still needs a value (“status is …”) leaves the caret after it, without the colon.
      replace(menu, row.label.endsWith('…') ? `${phrase} ` : `${phrase}:`);
    },
    [menu, replace],
  );
  menuRef.current = { menu, rows, active, pick };

  const badgeRows: MenuSection[] = [
    {
      label: 'This mention',
      rows: [
        { key: 'replace', label: 'Replace…', trailing: 'pick another', pick: () => {} },
        { key: 'remove', label: 'Remove', pick: () => {} },
      ],
    },
  ];
  const onBadge = (row: { key: string }) => {
    const v = view.current;
    if (!v || !badge) return;
    const space = v.state.doc.sliceString(badge.to, badge.to + 1) === ' ' ? 1 : 0;
    const insert = row.key === 'replace' ? '@' : '';
    // Typed as `@`, so the mention list opens on the badge's place.
    v.dispatch({ changes: { from: badge.from, to: badge.to + (row.key === 'remove' ? space : 0), insert }, selection: { anchor: badge.from + insert.length }, userEvent: row.key === 'replace' ? 'input.type' : 'delete' });
    setBadge(null);
    v.focus();
  };

  badgeRef.current = { open: !!badge && !menu, active: badgeActive, pick: (key) => onBadge({ key }) };

  const status = menu?.kind === 'if' ? 'ready' : foundStatus;
  return (
    <div className="relative" data-testid="sop-editor">
      <div ref={host} className="min-h-40" />
      {badge && !menu && (
        <CaretMenu
          rect={() => {
            const c = view.current?.coordsAtPos(badge.from);
            return c ? new DOMRect(c.left, c.top, 1, c.bottom - c.top) : null;
          }}
          label="Change this mention"
          status="ready"
          sections={badgeRows}
          active={badgeActive}
          onActive={setBadgeActive}
          onPick={onBadge}
          onDismiss={() => setBadge(null)}
          empty=""
          error=""
          id={`${menuId}-badge`}
        />
      )}
      {menu && !readOnly && (status !== 'ready' || sections.length > 0 || menu.kind === 'mention') && (
        <CaretMenu
          rect={() => {
            const c = view.current?.coordsAtPos(menu.from);
            return c ? new DOMRect(c.left, c.top, 1, c.bottom - c.top) : null;
          }}
          label={menu.kind === 'mention' ? 'Mention a tool, knowledge, a skill or an agent' : 'Write a condition'}
          status={status}
          sections={sections}
          active={active}
          onActive={setActive}
          onPick={pick}
          onDismiss={() => setMenu(null)}
          empty={menu.query ? `Nothing called “${menu.query}”. Keep typing, or leave it as plain text.` : 'This team has no tools, knowledge or skills yet. A builder can add them in Apps.'}
          error="Couldn’t load the list. What you typed is kept; try again in a moment."
          id={menuId}
          onEnd={menu.kind === 'mention' ? loadMore : undefined}
          loadingMore={menu.kind === 'mention' && scope !== null && scoped.isFetchingNextPage}
        />
      )}
    </div>
  );
}
