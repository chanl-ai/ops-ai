/**
 * The instruction document's editor schema. The tree mirrors the stored fields one to one (document-model.ts): a
 * locked heading with its text, a list, or numbered steps, with reference and variable chips inside text. There are
 * no marks, because the stored text has no formatting.
 */
import { type Editor, Extension, Node, type Range } from '@tiptap/core';
import { UndoRedo } from '@tiptap/extensions';
import { Fragment, type Node as PmNode, type ResolvedPos, Slice } from '@tiptap/pm/model';
import { Plugin, PluginKey, Selection, TextSelection } from '@tiptap/pm/state';
import { Mapping } from '@tiptap/pm/transform';
import { Decoration, DecorationSet } from '@tiptap/pm/view';
import { ReactNodeViewRenderer } from '@tiptap/react';
import { Suggestion, type SuggestionProps, findSuggestionMatch } from '@tiptap/suggestion';

import type { Ref } from '@/lib/types/references';

import { type DocNode, parseText, pickSetsUse, refToken, refsInNode, runsIndex, splitOwner } from './document-model';
import { BlockView, CheckView, IfNotView, ReferenceView, StepView, VariableView } from './node-views';

export type Trigger = '@' | '{{' | '/';

/** A menu row's action: it replaces the typed trigger and query (`range`) with what was picked. */
export type MenuPick = (editor: Editor, range: Range) => void;

/** How the typed triggers reach the menu the component draws. */
export interface MenuBridge {
  show(trigger: Trigger, props: { query: string; rect: (() => DOMRect | null) | null; pick: (run: MenuPick) => void }): void;
  hide(trigger: Trigger): void;
  /** True when the menu took the key (arrows, Enter, Tab). */
  key(event: KeyboardEvent): boolean;
}

const attr = (name: string) => ({ [name]: { default: null } });

const Doc = Node.create({ name: 'doc', topNode: true, content: '(field|list|steps)+' });
const Text = Node.create({ name: 'text', group: 'inline' });
const Paragraph = Node.create({ name: 'paragraph', content: 'inline*', parseHTML: () => [{ tag: 'p' }], renderHTML: () => ['p', 0] });
const Item = Node.create({
  name: 'item',
  content: 'inline*',
  renderHTML: () => ['div', { 'data-item': '', class: 'ml-5 list-item list-disc pl-1 marker:text-muted-foreground' }, 0],
});
const Line = Node.create({ name: 'line', content: 'inline*', renderHTML: () => ['div', { 'data-line': '' }, 0] });

const Field = Node.create({
  name: 'field',
  content: 'paragraph+',
  isolating: true,
  defining: true,
  addAttributes: () => ({ ...attr('key'), ...attr('label'), ...attr('placeholder'), ...attr('optional') }),
  renderHTML: () => ['section', 0],
  addNodeView: () => ReactNodeViewRenderer(BlockView),
});
const List = Field.extend({ name: 'list', content: 'item+' });
const Steps = Node.create({
  name: 'steps',
  content: 'step+',
  isolating: true,
  addAttributes: () => attr('placeholder'),
  renderHTML: () => ['div', { 'data-steps': '', class: 'flex flex-col gap-1 [counter-reset:step]' }, 0],
});
const Step = Node.create({
  name: 'step',
  content: 'line check? ifNot?',
  addAttributes: () => ({ ...attr('use'), locked: { default: false } }),
  renderHTML: () => ['div', 0],
  addNodeView: () => ReactNodeViewRenderer(StepView),
});
const Check = Node.create({ name: 'check', content: 'inline*', addAttributes: () => attr('by'), renderHTML: () => ['div', 0], addNodeView: () => ReactNodeViewRenderer(CheckView) });
const IfNotNode = Node.create({
  name: 'ifNot',
  atom: true,
  selectable: true,
  addAttributes: () => attr('value'),
  renderHTML: () => ['div'],
  // The controls inside take their own keys and clicks.
  addNodeView: () => ReactNodeViewRenderer(IfNotView, { stopEvent: () => true }),
});

const Reference = Node.create({
  name: 'reference',
  group: 'inline',
  inline: true,
  atom: true,
  addAttributes: () => ({ ...attr('kind'), ...attr('id') }),
  // Copied text carries the stored token, so a paste into another document names the same item.
  renderText: ({ node }) => refToken({ kind: node.attrs.kind, id: node.attrs.id }),
  parseHTML: () => [{ tag: 'span[data-reference]', getAttrs: (el) => ({ kind: el.getAttribute('data-kind'), id: el.getAttribute('data-id') }) }],
  renderHTML: ({ node }) => ['span', { 'data-reference': '', 'data-kind': node.attrs.kind, 'data-id': node.attrs.id }, refToken({ kind: node.attrs.kind, id: node.attrs.id })],
  // The chip's "runs" mark comes from a decoration (Runs), which moves without the node changing.
  addNodeView: () => ReactNodeViewRenderer(ReferenceView, { as: 'span', update: ({ oldNode, newNode, updateProps }) => (newNode.type === oldNode.type ? (updateProps(), true) : false) }),
});
const Variable = Node.create({
  name: 'variable',
  group: 'inline',
  inline: true,
  atom: true,
  addAttributes: () => attr('name'),
  renderText: ({ node }) => `{{${node.attrs.name}}}`,
  parseHTML: () => [{ tag: 'span[data-variable]', getAttrs: (el) => ({ name: el.getAttribute('data-variable') }) }],
  renderHTML: ({ node }) => ['span', { 'data-variable': node.attrs.name }, `{{${node.attrs.name}}}`],
  addNodeView: () => ReactNodeViewRenderer(VariableView, { as: 'span' }),
});

const stepDepth = ($pos: ResolvedPos) => {
  for (let d = $pos.depth; d > 0; d--) if ($pos.node(d).type.name === 'step') return d;
  return 0;
};

/** A new blank step after the one the caret is in, or after the last step when it is in none. */
export function addStep(editor: Editor): boolean {
  const { state, view } = editor;
  const { step, line } = state.schema.nodes;
  let after: number | null = null;
  const d = stepDepth(state.selection.$from);
  if (d) after = state.selection.$from.after(d);
  else
    state.doc.descendants((node, pos) => {
      if (node.type.name === 'steps') after = pos + node.nodeSize - 1;
      return false;
    });
  if (after === null) return false;
  const tr = state.tr.insert(after, step.create(null, line.create()));
  view.dispatch(tr.setSelection(TextSelection.create(tr.doc, after + 2)).scrollIntoView());
  view.focus();
  return true;
}

/** Adds the Check line to the caret's step, or moves the caret into the one it has. */
export function addCheck(editor: Editor): boolean {
  const { state, view } = editor;
  const d = stepDepth(state.selection.$from);
  if (!d) return false;
  const node = state.selection.$from.node(d);
  const at = state.selection.$from.start(d) + node.child(0).nodeSize;
  const tr = node.childCount > 1 && node.child(1).type.name === 'check' ? state.tr : state.tr.insert(at, state.schema.nodes.check.create());
  const check = tr.doc.nodeAt(at)!;
  view.dispatch(tr.setSelection(TextSelection.create(tr.doc, at + 1 + check.content.size)).scrollIntoView());
  return true;
}

/** Adds the If not line to the caret's step when it has none. */
export function addIfNot(editor: Editor): boolean {
  const { state, view } = editor;
  const d = stepDepth(state.selection.$from);
  if (!d) return false;
  const node = state.selection.$from.node(d);
  if (node.lastChild?.type.name === 'ifNot') return true;
  view.dispatch(state.tr.insert(state.selection.$from.end(d), state.schema.nodes.ifNot.create({ value: { action: 'retry', retries: 1 } })));
  return true;
}

function enter(editor: Editor): boolean {
  if (!editor.state.selection.empty) editor.commands.deleteSelection();
  const { state, view } = editor;
  const { $from } = state.selection;
  const name = $from.parent.type.name;
  if (name === 'paragraph' || name === 'item') {
    view.dispatch(state.tr.split($from.pos).scrollIntoView());
    return true;
  }
  if (name === 'line' && $from.parentOffset < $from.parent.content.size) {
    const { step, line } = state.schema.nodes;
    // The text after the caret becomes the next step. `use` (and `locked` with it) goes to the half that holds the
    // reference marked "runs", so the tool is not left on a step whose sentence no longer names it.
    const d = stepDepth($from);
    const stepAt = $from.before(d);
    const { use, locked } = $from.node(d).attrs;
    const owner = splitOwner(use, refsInNode($from.parent.cut(0, $from.parentOffset)), refsInNode($from.parent.cut($from.parentOffset)));
    const second = owner === 'second' ? { use, locked } : { use: null, locked: false };
    const tr = state.tr.split($from.pos, 2, [{ type: step, attrs: second }, { type: line }]);
    if (owner === 'second') tr.setNodeMarkup(stepAt, undefined, { ...$from.node(d).attrs, use: null, locked: false });
    view.dispatch(tr.scrollIntoView());
    return true;
  }
  return name === 'line' || name === 'check' ? addStep(editor) : false;
}

/** The end of the last line of text in the step that starts at `pos`: its check when it has one, else its own line. */
function endOfStepText(doc: PmNode, pos: number): number {
  const step = doc.nodeAt(pos)!;
  let at = pos + 1;
  let end = at + 1;
  step.forEach((child) => {
    if (child.isTextblock) end = at + 1 + child.content.size;
    at += child.nodeSize;
  });
  return end;
}

function backspace(editor: Editor): boolean {
  const { state, view } = editor;
  const { $from, empty } = state.selection;
  if (!empty || $from.parentOffset > 0) return false;
  const name = $from.parent.type.name;
  // The first line under a heading has nothing before it to join.
  if (name === 'paragraph' || name === 'item') return $from.index(-1) === 0;
  if (name === 'check') {
    if ($from.parent.content.size) return true;
    const tr = state.tr.delete($from.before(), $from.after());
    view.dispatch(tr.setSelection(Selection.near(tr.doc.resolve($from.before()), -1)));
    return true;
  }
  if (name !== 'line') return false;
  const index = $from.index(-2);
  if (index === 0) return true;
  const step = $from.node(-1);
  const before = $from.before(-1);
  const prev = $from.node(-2).child(index - 1);
  let tr = state.tr;
  // The caret goes to the end of the previous step's text, never onto its if-not line, which typing would replace.
  const prevEnd = endOfStepText(state.doc, before - prev.nodeSize);
  if (prev.childCount === 1 && !step.attrs.use) tr = tr.join(before, 2);
  else if (step.childCount === 1 && !step.attrs.use && !$from.parent.content.size) tr = tr.delete(before, $from.after(-1)).setSelection(TextSelection.create(tr.doc, prevEnd));
  else tr = tr.setSelection(TextSelection.create(state.doc, prevEnd));
  view.dispatch(tr.scrollIntoView());
  return true;
}

/**
 * Takes the caret from the page before a key is judged. The editor hears of a caret move a moment after it happens, so
 * a key pressed straight after an arrow key would be judged at the old place and then carried out by the browser at
 * the new one.
 */
function syncCaret(editor: Editor): void {
  const { view, state } = editor;
  const sel = view.dom.ownerDocument.getSelection();
  if (!sel?.isCollapsed || !sel.anchorNode || !view.dom.contains(sel.anchorNode)) return;
  let pos: number;
  try {
    pos = view.posAtDOM(sel.anchorNode, sel.anchorOffset);
  } catch {
    return;
  }
  if (!state.selection.empty || pos === state.selection.from) return;
  const $pos = state.doc.resolve(pos);
  if ($pos.parent.inlineContent) view.dispatch(state.tr.setSelection(TextSelection.create(state.doc, pos)));
}

/**
 * True when the caret is at the start (-1) or end (1) of a line whose neighbour on that side cannot be joined to it:
 * a step's line or check, or the first or last line under a heading. The key is then spent and nothing changes.
 */
function atEdge(editor: Editor, side: -1 | 1): boolean {
  const { $from, empty } = editor.state.selection;
  if (!empty || !$from.depth) return false;
  if (side < 0 ? $from.parentOffset > 0 : $from.parentOffset < $from.parent.content.size) return false;
  const name = $from.parent.type.name;
  if (name === 'line' || name === 'check') return true;
  return side < 0 ? $from.index(-1) === 0 : $from.index(-1) === $from.node(-1).childCount - 1;
}

const shape = (doc: PmNode) => {
  const parts: string[] = [];
  doc.forEach((n) => parts.push(`${n.type.name}:${n.attrs.key ?? ''}`));
  return parts.join('|');
};

/** Set on the transaction that loads a new document, which may have other headings. */
export const LOADS_DOCUMENT = 'instructionDocumentLoad';

const Structure = Extension.create({
  name: 'instructionStructure',
  // Ahead of the editor's stock keys, whose Enter, Backspace and select-all assume one flat run of paragraphs.
  priority: 1000,
  addKeyboardShortcuts() {
    return {
      Enter: () => (syncCaret(this.editor), enter(this.editor)),
      // Every key that deletes backwards from the start of a line, or forwards from its end, is answered here. Left to
      // the browser, such a key merges the two lines in the page itself and the step's check or if-not line is lost.
      ...Object.fromEntries(['Backspace', 'Mod-Backspace', 'Alt-Backspace', 'Shift-Backspace', 'Ctrl-h'].map((key) => [key, () => (syncCaret(this.editor), backspace(this.editor) || atEdge(this.editor, -1))])),
      ...Object.fromEntries(['Delete', 'Mod-Delete', 'Alt-Delete', 'Ctrl-d', 'Ctrl-k'].map((key) => [key, () => (syncCaret(this.editor), atEdge(this.editor, 1))])),
      // Select all takes the text under the caret's heading: the headings themselves cannot be selected away.
      'Mod-a': () => {
        const { state, view } = this.editor;
        const { $from } = state.selection;
        if (!$from.depth) return true;
        view.dispatch(state.tr.setSelection(TextSelection.between(state.doc.resolve($from.start(1)), state.doc.resolve($from.end(1)))));
        return true;
      },
    };
  },
  addProseMirrorPlugins() {
    const schema = this.editor.schema;
    const node = (n: DocNode) => schema.nodeFromJSON(n);
    const inline = (line: string) => parseText(line).map((s) => node(s.t === 'text' ? { type: 'text', text: s.text } : s.t === 'ref' ? { type: 'reference', attrs: { kind: s.kind, id: s.id } } : { type: 'variable', attrs: { name: s.name } }));
    return [
      new Plugin({
        key: new PluginKey('instructionStructure'),
        // Headings are locked: an edit that adds, removes or reorders a top-level block is refused.
        filterTransaction: (tr, state) => !tr.docChanged || tr.getMeta(LOADS_DOCUMENT) || shape(tr.doc) === shape(state.doc),
        // "If not: go to step 3" names a step by number. When steps are added, split or removed above it, the number
        // follows the step it named. Undo and redo carry their own renumbering, and a loaded document is as stored.
        appendTransaction: (trs, oldState, newState) => {
          if (!trs.some((t) => t.docChanged) || trs.some((t) => t.getMeta(LOADS_DOCUMENT) || t.getMeta('history$'))) return null;
          const mapping = new Mapping();
          for (const t of trs) mapping.appendMapping(t.mapping);
          const moved = new Map<number, number>();
          oldState.doc.forEach((block, offset) => {
            if (block.type.name !== 'steps') return;
            let at = offset + 1;
            block.forEach((step, _o, index) => {
              const to = mapping.mapResult(at, 1);
              const $to = newState.doc.resolve(to.pos);
              if (!to.deletedAfter && $to.parent.type.name === 'steps' && $to.index() !== index) moved.set(index + 1, $to.index() + 1);
              at += step.nodeSize;
            });
          });
          if (!moved.size) return null;
          const tr = newState.tr;
          newState.doc.descendants((n, pos) => {
            const value = n.type.name === 'ifNot' ? (n.attrs.value as { action: string; step?: number | null }) : null;
            if (value?.action === 'goto' && value.step && moved.has(value.step)) tr.setNodeAttribute(pos, 'value', { ...value, step: moved.get(value.step) });
            return n.type.name !== 'step' || n.childCount > 1;
          });
          return tr.docChanged ? tr : null;
        },
        props: {
          // Pasted text keeps its references and variables as chips. Under a heading each line is its own paragraph;
          // a step or a list line is one line, so line breaks become spaces there.
          clipboardTextParser: (pasted, $context) => {
            const lines = pasted.replace(/\r/g, '').split('\n');
            if ($context.parent.type.name !== 'paragraph' || lines.length === 1) return new Slice(Fragment.from(inline(lines.join(' '))), 0, 0);
            return new Slice(Fragment.from(lines.map((l) => schema.nodes.paragraph.create(null, inline(l)))), 1, 1);
          },
        },
      }),
    ];
  },
});

const inStep = (editor: Editor) => stepDepth(editor.state.selection.$from) > 0;

const Menus = Extension.create<{ bridge: () => MenuBridge | null }>({
  name: 'instructionMenus',
  // An open menu takes Enter and the arrows before the document's own keys do.
  priority: 1100,
  addOptions: () => ({ bridge: () => null }),
  addProseMirrorPlugins() {
    const { editor, options } = this;
    const menu = (trigger: Trigger, allowedPrefixes: string[] | null, allow: () => boolean = () => true) => {
      const show = (p: SuggestionProps<never, MenuPick>) => {
        options.bridge()?.show(trigger, { query: p.query, rect: p.clientRect ?? null, pick: p.command });
      };
      return Suggestion<never, MenuPick>({
        editor,
        char: trigger,
        pluginKey: new PluginKey(`instructionMenu${trigger}`),
        allowedPrefixes,
        allow: () => editor.isEditable && allow(),
        command: ({ editor: e, range, props }) => props(e, range),
        // The search is what was typed up to the caret. The stock match runs to the end of the word, which would
        // take in text already standing after the caret and replace it on a pick.
        findSuggestionMatch: (config) => {
          const match = findSuggestionMatch(config);
          if (!match) return match;
          const to = config.$position.pos;
          const typed = config.$position.doc.textBetween(match.range.from, to, '\0', '\0');
          return { range: { from: match.range.from, to }, query: typed.slice(trigger.length), text: typed };
        },
        render: () => ({ onStart: show, onUpdate: show, onExit: () => options.bridge()?.hide(trigger), onKeyDown: ({ event }) => options.bridge()?.key(event) ?? false }),
      });
    };
    return [menu('@', [' ', '(']), menu('{{', null), menu('/', [' '], () => inStep(editor))];
  },
});

/**
 * Writes a picked reference where it was typed. The first tool, skill, agent or workflow picked in a step's sentence
 * also becomes what the step runs (`use`); the same token stays in the sentence, so the stored text reads as written.
 */
export function pickReference(editor: Editor, range: Range, ref: Ref) {
  const { state } = editor;
  const $at = state.doc.resolve(range.from);
  const d = stepDepth($at);
  const sets = d > 0 && pickSetsUse(ref, { in: $at.parent.type.name, use: $at.node(d).attrs.use });
  // A space follows the chip unless punctuation or a space already does.
  const after = state.doc.resolve(range.to).nodeAfter?.text?.[0];
  const chip = { type: 'reference', attrs: ref };
  const chain = editor.chain().focus().insertContentAt(range, !after || /\w/.test(after) ? [chip, { type: 'text', text: ' ' }] : chip);
  // The step starts before the typed text, so inserting there does not move it.
  if (sets) chain.command(({ tr }) => (tr.setNodeAttribute($at.before(d), 'use', ref), true));
  chain.run();
}

/** True for a reference standing in a step's sentence, which the builder can mark as what the step runs. */
export function canMarkRuns(editor: Editor, pos: number): boolean {
  const $at = editor.state.doc.resolve(pos);
  return $at.parent.type.name === 'line' && stepDepth($at) > 0;
}

/** Makes the reference at `pos` what its step runs, or with null stops the step running anything. */
export function setStepRuns(editor: Editor, pos: number, ref: Ref | null) {
  const $at = editor.state.doc.resolve(pos);
  const d = stepDepth($at);
  if (!d) return;
  const tr = editor.state.tr.setNodeAttribute($at.before(d), 'use', ref);
  // A lock belongs to the tool it was set on.
  editor.view.dispatch(tr.setNodeAttribute($at.before(d), 'locked', false));
}

/** Locks the step's tool to this step, or releases it. */
export function setStepLocked(editor: Editor, pos: number, locked: boolean) {
  const d = stepDepth(editor.state.doc.resolve(pos));
  if (d) editor.view.dispatch(editor.state.tr.setNodeAttribute(editor.state.doc.resolve(pos).before(d), 'locked', locked));
}

const sameRef = (a: Ref | null | undefined, b: Ref) => !!a && a.kind === b.kind && a.id === b.id;

/**
 * What a step runs when it is also named in the step's sentence: that reference carries the "runs" mark instead of a
 * chip in front. Deleting it from the sentence stops the step running it; a step whose tool was never in its sentence
 * (saved by the SDK, the CLI or an earlier editor) keeps its chip in front.
 */
const Runs = Extension.create({
  name: 'instructionRuns',
  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: new PluginKey('instructionRuns'),
        props: {
          decorations: (state) => {
            const found: Decoration[] = [];
            state.doc.descendants((step, pos) => {
              if (step.type.name !== 'step') return true;
              const line = step.firstChild;
              const at = runsIndex(step.attrs.use, refsInNode(line));
              if (!line || at < 0) return false;
              let n = 0;
              line.descendants((child, offset) => {
                if (child.type.name !== 'reference' || !sameRef(step.attrs.use, child.attrs as Ref) || n++ !== 0) return;
                // The step opens at `pos`, its line one further, and the line's own text one further again.
                found.push(Decoration.node(pos + 2 + offset, pos + 2 + offset + child.nodeSize, {}, { runs: true, locked: !!step.attrs.locked }));
              });
              return false;
            });
            return DecorationSet.create(state.doc, found);
          },
        },
        appendTransaction: (trs, oldState, newState) => {
          if (!trs.some((t) => t.docChanged) || trs.some((t) => t.getMeta(LOADS_DOCUMENT))) return null;
          const mapping = new Mapping();
          for (const t of trs) mapping.appendMapping(t.mapping);
          const tr = newState.tr;
          oldState.doc.descendants((step, pos) => {
            if (step.type.name !== 'step') return true;
            const use = step.attrs.use as Ref | null;
            if (runsIndex(use, refsInNode(step.firstChild)) < 0) return false;
            const to = mapping.mapResult(pos, 1);
            const now = to.deleted ? null : newState.doc.nodeAt(to.pos);
            if (now?.type.name === 'step' && sameRef(now.attrs.use, use!) && runsIndex(use, refsInNode(now.firstChild)) < 0) {
              tr.setNodeAttribute(to.pos, 'use', null);
              tr.setNodeAttribute(to.pos, 'locked', false);
            }
            return false;
          });
          return tr.docChanged ? tr : null;
        },
      }),
    ];
  },
});

/** A heading, list or set of steps with nothing written under it says what goes there, on its one blank line. */
const Placeholders = Extension.create({
  name: 'instructionPlaceholders',
  addProseMirrorPlugins() {
    const editor = this.editor;
    return [
      new Plugin({
        key: new PluginKey('instructionPlaceholders'),
        props: {
          decorations: (state) => {
            if (!editor.isEditable) return null;
            const found: Decoration[] = [];
            state.doc.forEach((block, offset) => {
              if (!block.attrs.placeholder || block.childCount !== 1) return;
              const first = block.firstChild!;
              // Under steps the blank line is inside the one step, which must have nothing else in it.
              const line = first.type.name === 'step' ? (first.childCount === 1 && !first.attrs.use ? first.firstChild! : null) : first;
              if (!line || line.content.size) return;
              const at = offset + 1 + (first.type.name === 'step' ? 1 : 0);
              found.push(Decoration.node(at, at + line.nodeSize, { class: 'is-empty', 'data-placeholder': block.attrs.placeholder }));
            });
            return DecorationSet.create(state.doc, found);
          },
        },
      }),
    ];
  },
});

export const instructionExtensions = (bridge: () => MenuBridge | null) => [
  Doc,
  Text,
  Paragraph,
  Field,
  List,
  Item,
  Steps,
  Step,
  Line,
  Check,
  IfNotNode,
  Reference,
  Variable,
  UndoRedo,
  Structure,
  Menus.configure({ bridge }),
  Placeholders,
  Runs,
];
