'use client';

import * as React from 'react';
import type { Editor } from '@tiptap/core';
import { Selection, TextSelection } from '@tiptap/pm/state';
import { EditorContent, useEditor } from '@tiptap/react';
import { Braces, CircleCheck, CornerDownRight, ListOrdered, Plus } from 'lucide-react';

import { Button } from '@/components/ui/button';
import type { PublishBlocker, Ref, RefKind, ReferenceGroup, ReferenceItem, ReferenceSearch } from '@/lib/types/references';

import { type DocNode, type DocumentValue, fromEditorDoc, missingReferences, refsInNode, runsIndex, toEditorDoc } from './document-model';
import { LOADS_DOCUMENT, type MenuBridge, type MenuPick, type Trigger, addCheck, addIfNot, addStep, canMarkRuns, instructionExtensions, pickReference, setStepLocked, setStepRuns } from './extensions';
import { DocumentContext, type DocumentContextValue, FixRows, type InvalidField, KIND_ICON } from './node-views';
import { CaretMenu, type MenuRow as CaretRow, type MenuSection as CaretSection } from '@/components/shared/caret-menu';

type MenuRow = CaretRow<MenuPick>;
type MenuSection = CaretSection<MenuPick>;

export interface VariableGroup {
  label: string;
  items: { name: string; sample?: string }[];
}

export interface InstructionDocumentHandle {
  /** Moves the caret to a heading's text or a step, as a publish problem's "Go to it" does. */
  focus(at: { field: string; step?: number }): void;
}

export interface InstructionDocumentProps {
  /** The stored fields as blocks; text holds `@kind:id` and `{{name}}` tokens. Never the editor's own format. */
  value: DocumentValue;
  /** Fires on every edit with the whole document; the page debounces its save. */
  onChange: (next: DocumentValue) => void;
  /** What the `@` menu lists for the typed text, grouped by the server. */
  searchReferences: (query: string, kind?: RefKind) => Promise<ReferenceSearch>;
  /** Called with a picked item the agent does not hold, and by "Add it back". Left out, a pick only writes the chip. */
  onInsertReference?: (ref: Ref) => Promise<void> | void;
  /** The current names of the document's references. Undefined while loading; a reference it leaves out draws as Missing. */
  resolved?: ReferenceItem[];
  /** Publish problems; each missing reference gets a fix row under the heading or step it names. */
  missing?: PublishBlocker[];
  /** The document's references that `resolved` does not hold, whenever that set changes. */
  onMissingChange?: (refs: Ref[]) => void;
  invalid?: InvalidField[];
  /** Lines the publish check noticed and does not block on, shown under the heading or step they name. */
  warnings?: InvalidField[];
  /** What `{{` offers. Left out, `{{` is plain text. */
  variables?: VariableGroup[];
  readOnly?: boolean;
  /** `add-step` shows Add a step under a document that has steps. */
  footer?: 'add-step';
  /** The card's own footer row (counts, actions); shown read-only too, and in place of the hint. */
  footerSlot?: React.ReactNode;
  /** Shows the hint line in the footer row of an editable document with no footer of its own; off, there is no footer row. */
  showHint?: boolean;
  /** The card's one header row, above the first heading (the brief's model, uses and actions); the page lays it out. */
  headerSlot?: React.ReactNode;
  hint?: string;
  /** What the document is, for a screen reader: "Dispute desk instructions". */
  label: string;
  controls?: React.Ref<InstructionDocumentHandle>;
}

const normal = (value: DocumentValue) => JSON.stringify(fromEditorDoc(toEditorDoc(value)));

const EDITOR_CLASS =
  'flex flex-col gap-4 p-4 text-sm leading-6 outline-hidden [&_.is-empty]:before:pointer-events-none [&_.is-empty]:before:float-left [&_.is-empty]:before:-mr-[100%] [&_.is-empty]:before:w-full [&_.is-empty]:after:block [&_.is-empty]:after:clear-both [&_.is-empty]:after:content-[""] [&_.is-empty]:before:text-muted-foreground [&_.is-empty]:before:content-[attr(data-placeholder)]';

interface OpenMenu {
  trigger: Trigger;
  query: string;
  rect: (() => DOMRect | null) | null;
  pick: (run: MenuPick) => void;
}

const BLOCK_ROWS: { key: string; label: string; icon: typeof Plus; trailing: string; run: (editor: Editor) => boolean }[] = [
  { key: 'step', label: 'Step', icon: ListOrdered, trailing: 'A new numbered step', run: addStep },
  { key: 'check', label: 'Check', icon: CircleCheck, trailing: 'What must be true before the next step', run: addCheck },
  { key: 'if-not', label: 'If not', icon: CornerDownRight, trailing: 'What happens when the check does not pass', run: addIfNot },
];

const MENU_COPY: Record<Trigger, { label: string; empty: (q: string) => string }> = {
  '@': { label: 'Insert a reference', empty: (q) => (q ? `Nothing called “${q}” in this team. A builder can add it in Apps.` : 'This team has no tools, knowledge or skills yet. A builder can add them in Apps.') },
  '{{': { label: 'Insert a variable', empty: (q) => `No variable called “${q}”.` },
  '/': { label: 'Add to this step', empty: (q) => `Nothing called “${q}”. Type / for Step, Check or If not.` },
};

/**
 * One instruction document: locked headings, lists and numbered steps as a single text, with tools, knowledge,
 * skills, agents and workflows as chips. `@` opens the grouped picker under the caret, `{{` the variables, `/` adds a
 * step, a check or an if-not line. The agent page and the skill page draw the same component with different blocks.
 */
export function InstructionDocument({ value, onChange, searchReferences, onInsertReference, resolved, missing = [], onMissingChange, invalid = [], warnings = [], variables, readOnly = false, footer, footerSlot, headerSlot, showHint = true, hint = 'Type @ to add a tool, knowledge or skill', label, controls }: InstructionDocumentProps) {
  const bridge = React.useRef<MenuBridge | null>(null);
  const [extensions] = React.useState(() => instructionExtensions(() => bridge.current));
  // What the page last saw, so a value it hands back unchanged does not reload the document and move the caret.
  const seen = React.useRef(normal(value));
  const latest = React.useRef({ onChange, onInsertReference, searchReferences });
  latest.current = { onChange, onInsertReference, searchReferences };

  const editor = useEditor({
    immediatelyRender: false,
    shouldRerenderOnTransaction: false,
    extensions,
    content: toEditorDoc(value),
    editable: !readOnly,
    editorProps: { attributes: { role: 'textbox', 'aria-multiline': 'true', 'aria-label': label, 'aria-haspopup': 'listbox', class: EDITOR_CLASS } },
    onUpdate: ({ editor: e }) => {
      const next = fromEditorDoc(e.getJSON() as DocNode);
      const text = JSON.stringify(next);
      if (text === seen.current) return;
      seen.current = text;
      latest.current.onChange(next);
    },
  });

  React.useEffect(() => {
    if (!editor) return;
    const text = normal(value);
    if (text === seen.current) return;
    seen.current = text;
    // A value the page changed itself (a save that came back with more filled in, another version) replaces the
    // document. The caret keeps its place where the new document still has one there.
    // After this render: the document's parts are React components, and drawing them inside an effect is refused.
    queueMicrotask(() => {
      if (editor.isDestroyed) return;
      const { from, to } = editor.state.selection;
      editor.chain().setMeta(LOADS_DOCUMENT, true).setMeta('addToHistory', false).setContent(toEditorDoc(value), { emitUpdate: false }).run();
      const size = editor.state.doc.content.size;
      if (editor.isFocused && to <= size) editor.view.dispatch(editor.state.tr.setSelection(TextSelection.between(editor.state.doc.resolve(from), editor.state.doc.resolve(to))));
    });
  }, [editor, value]);

  React.useEffect(() => {
    editor?.setEditable(!readOnly, false);
  }, [editor, readOnly]);

  // Items picked here are named at once; the page's `resolved` catches up when it asks again.
  const [picked, setPicked] = React.useState<ReferenceItem[]>([]);
  const known = React.useMemo(() => resolved && [...resolved, ...picked], [resolved, picked]);
  const gone = React.useRef('[]');
  React.useEffect(() => {
    const refs = missingReferences(value, known);
    const text = JSON.stringify(refs);
    if (text === gone.current) return;
    gone.current = text;
    onMissingChange?.(refs);
  }, [value, known, onMissingChange]);

  // ---------- the @, {{ and / menus ----------
  const [open, setOpen] = React.useState<OpenMenu | null>(null);
  const [active, setActive] = React.useState('');
  const [found, setFound] = React.useState<{ status: 'loading' | 'ready' | 'error'; groups: ReferenceGroup[] }>({ status: 'loading', groups: [] });
  const menuId = React.useId();
  const searching = open?.trigger === '@';
  const query = open?.query ?? '';

  React.useEffect(() => {
    if (!searching) return;
    let stale = false;
    // One request per pause in typing; the answer for text the builder has since changed is dropped.
    const timer = setTimeout(() => {
      latest.current.searchReferences(query).then(
        (r) => !stale && setFound({ status: 'ready', groups: r.groups }),
        () => !stale && setFound({ status: 'error', groups: [] }),
      );
    }, 150);
    return () => {
      stale = true;
      clearTimeout(timer);
    };
  }, [searching, query]);
  React.useEffect(() => {
    if (!searching) setFound({ status: 'loading', groups: [] });
  }, [searching]);

  const sections = React.useMemo<MenuSection[]>(() => {
    if (!open) return [];
    const q = open.query.toLowerCase();
    if (open.trigger === '@')
      return found.groups.map((g) => ({
        label: g.label,
        rows: g.items.map((item): MenuRow => ({
          key: `${item.kind}:${item.id}`,
          label: item.label,
          icon: KIND_ICON[item.kind],
          trailing: item.hint,
          disabled: item.disabled,
          note: item.adds,
          pick: (e, range) => {
            const ref = { kind: item.kind, id: item.id };
            setPicked((p) => [...p, item]);
            pickReference(e, range, ref);
            if (item.held === false) void latest.current.onInsertReference?.(ref);
          },
        })),
      }));
    if (open.trigger === '{{')
      return (variables ?? [])
        .map((g) => ({
          label: g.label,
          rows: g.items
            .filter((v) => v.name.toLowerCase().includes(q))
            .map((v): MenuRow => ({ key: v.name, label: v.name, icon: Braces, trailing: v.sample, note: 'Values are sent beside the text, not written into it.', pick: (e, range) => void e.chain().focus().insertContentAt(range, { type: 'variable', attrs: { name: v.name } }).run() })),
        }))
        .filter((g) => g.rows.length);
    const rows = BLOCK_ROWS.filter((b) => b.label.toLowerCase().includes(q)).map(
      (b): MenuRow => ({
        key: b.key,
        label: b.label,
        icon: b.icon,
        trailing: b.trailing,
        pick: (e, range) => {
          e.chain().focus().deleteRange(range).run();
          b.run(e);
        },
      }),
    );
    return rows.length ? [{ label: 'Add', rows }] : [];
  }, [open, found.groups, variables]);

  const status = searching ? found.status : 'ready';
  const rows = React.useMemo(() => sections.flatMap((s) => s.rows).filter((r) => !r.disabled), [sections]);
  React.useEffect(() => {
    if (!rows.some((r) => r.key === active)) setActive(rows[0]?.key ?? '');
  }, [rows, active]);

  const menu = React.useRef({ open, rows, active, status });
  menu.current = { open, rows, active, status };
  // `{{` is plain text where no variables are offered.
  const offers = (trigger: Trigger) => trigger !== '{{' || !!variables;
  bridge.current = {
    show: (trigger, p) => offers(trigger) && setOpen({ trigger, ...p }),
    hide: (trigger) => setOpen((o) => (o?.trigger === trigger ? null : o)),
    key: (event) => {
      const m = menu.current;
      if (!m.open) return false;
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        if (!m.rows.length) return true;
        const at = m.rows.findIndex((r) => r.key === m.active);
        setActive(m.rows[(at + (event.key === 'ArrowDown' ? 1 : m.rows.length - 1)) % m.rows.length].key);
        return true;
      }
      if (event.key === 'Enter' || event.key === 'Tab') {
        const row = m.rows.find((r) => r.key === m.active);
        if (row) m.open.pick(row.pick);
        // While the search is out, Enter waits for it instead of breaking the line.
        return !!row || m.status === 'loading';
      }
      return false;
    },
  };

  React.useEffect(() => {
    const dom = editor?.view.dom;
    if (!dom) return;
    dom.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (!open) {
      dom.removeAttribute('aria-controls');
      dom.removeAttribute('aria-activedescendant');
      return;
    }
    // cmdk gives the list and its rows their ids, and marks the highlighted row after it renders.
    const frame = requestAnimationFrame(() => {
      const list = document.getElementById(menuId)?.querySelector('[cmdk-list]');
      const row = list?.querySelector('[cmdk-item][data-selected="true"]');
      if (list?.id) dom.setAttribute('aria-controls', list.id);
      if (row?.id) dom.setAttribute('aria-activedescendant', row.id);
      else dom.removeAttribute('aria-activedescendant');
    });
    return () => {
      cancelAnimationFrame(frame);
    };
  }, [editor, open, active, menuId, status, sections]);

  // ---------- what the document's parts can do ----------
  const chooseAnother = React.useCallback(
    (ref: Ref) => {
      if (!editor) return;
      let done = false;
      editor.state.doc.descendants((node, pos) => {
        if (done) return false;
        const { state } = editor;
        if (node.type.name === 'reference' && node.attrs.kind === ref.kind && node.attrs.id === ref.id) {
          const before = state.doc.resolve(pos).nodeBefore;
          const spaced = !before || (before.isText && /[\s(]$/.test(before.text ?? ''));
          editor.chain().focus().insertContentAt({ from: pos, to: pos + 1 }, spaced ? '@' : ' @').run();
          done = true;
        } else if (node.type.name === 'step' && node.attrs.use?.kind === ref.kind && node.attrs.use?.id === ref.id && runsIndex(node.attrs.use, refsInNode(node.firstChild)) < 0) {
          // Only a tool kept in front: one named in the sentence is found as that reference, which comes next.
          editor.view.dispatch(state.tr.setNodeAttribute(pos, 'use', null));
          editor.chain().focus().insertContentAt(pos + 2, '@').run();
          done = true;
        }
        return !done;
      });
    },
    [editor],
  );
  const context = React.useMemo<DocumentContextValue>(
    () => ({
      resolved: known,
      missing,
      invalid,
      warnings,
      readOnly,
      chooseAnother,
      canMarkRuns: (pos) => !!editor && canMarkRuns(editor, pos),
      markRuns: (pos, ref) => editor && setStepRuns(editor, pos, ref),
      setLocked: (pos, on) => editor && setStepLocked(editor, pos, on),
      addBack: onInsertReference ? (ref) => void latest.current.onInsertReference?.(ref) : undefined,
    }),
    // `onInsertReference` only decides whether Add it back is offered.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [known, missing, invalid, warnings, readOnly, chooseAnother, editor, !onInsertReference],
  );

  React.useImperativeHandle(
    controls,
    () => ({
      focus: ({ field, step }) => {
        if (!editor) return;
        let target: number | null = null;
        editor.state.doc.forEach((block, offset) => {
          if (target !== null) return;
          if (field === 'steps' && block.type.name === 'steps') {
            let at = offset + 1;
            block.forEach((s, _o, index) => {
              if (index + 1 === (step ?? 1)) target = at + 1;
              at += s.nodeSize;
            });
          } else if (block.attrs.key === field) target = offset + 1;
        });
        if (target === null) return;
        editor.view.dispatch(editor.state.tr.setSelection(Selection.near(editor.state.doc.resolve(target))).scrollIntoView());
        editor.view.focus();
      },
    }),
    [editor],
  );

  const unplaced = missing.filter((b) => b.kind === 'missing_reference' && !b.position);
  return (
    <DocumentContext.Provider value={context}>
      <div className="rounded-lg border bg-card" data-testid="instruction-document">
        {headerSlot && <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-4 py-2">{headerSlot}</div>}
        <EditorContent editor={editor} />
        {unplaced.length > 0 && (
          <div className="flex flex-col gap-2 px-4 pb-4">
            <FixRows blockers={unplaced} />
          </div>
        )}
        {(footerSlot || (!readOnly && (footer === 'add-step' || showHint))) && (
          <div className="flex flex-wrap items-center gap-2 border-t px-4 py-2">
            {footerSlot ?? <p className="text-xs text-muted-foreground">{hint}</p>}
            {!footerSlot && <span className="flex-1" />}
            {!readOnly && footer === 'add-step' && (
              <Button type="button" variant="ghost" size="sm" onClick={() => editor && addStep(editor)}>
                <Plus />
                Add a step
              </Button>
            )}
          </div>
        )}
      </div>
      {open?.rect && <CaretMenu rect={open.rect} label={MENU_COPY[open.trigger].label} status={status} sections={sections} active={active} onActive={setActive} onPick={(row) => open.pick(row.pick)} onDismiss={() => setOpen(null)} empty={MENU_COPY[open.trigger].empty(open.query)} error="Couldn’t search. Your text is safe; check your connection and try again." id={menuId} />}
    </DocumentContext.Provider>
  );
}
