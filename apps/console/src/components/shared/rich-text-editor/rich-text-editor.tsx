'use client';

import * as React from 'react';
import type { Editor, Range } from '@tiptap/core';
import { EditorContent, useEditor } from '@tiptap/react';
import { GitBranch, Heading2, List, ListOrdered, Minus, Quote } from 'lucide-react';

import { Textarea } from '@/components/ui/textarea';

import { CaretMenu, type MenuRow, type MenuSection } from '@/components/shared/caret-menu';
import { KIND_ICON } from '@/components/shared/reference-kinds';
import { useReferenceSearch } from '@/hooks/references-queries';
import type { Ref, ReferenceContext, ReferenceGroup, ReferenceItem } from '@/lib/types/references';
import { cn } from '@/lib/utils';

import { type MenuBridge, type Trigger, richTextExtensions } from './extensions';
import { mentionToken, mentionsIn } from '@/lib/mentions';
import { keepPlainText } from './markdown';
import { ReferencePickerDialog, type InsertableKind } from './reference-picker-dialog';
import { type MarkdownIO, blockAtLine, spliceEdit } from './splice';
import { IF_PATH, RichTextToolbar, type View, insertPath } from './toolbar';
import { MentionLabels } from './mention-view';

type Pick = (editor: Editor, range: Range) => void;
interface OpenMenu {
  trigger: Trigger;
  query: string;
  rect: (() => DOMRect | null) | null;
  run: (pick: Pick) => void;
}

export interface RichTextEditorHandle {
  /** Types `text` at the caret, so `@` opens its menu. */
  insert(text: string): void;
  /** Puts the caret in the nth block (from 1) and scrolls it into view. */
  focusLine(line: number): void;
}

export interface RichTextEditorProps {
  /** Markdown with `@kind:id` mentions. Handed back unchanged until the person edits. */
  value: string;
  onChange: (text: string) => void;
  readOnly?: boolean;
  /** Whose mentions the `@` list searches: the skill or agent being edited. */
  context: ReferenceContext;
  /** The current names of what the text mentions; undefined while loading. A mention it leaves out is drawn as Missing. */
  labels?: readonly ReferenceItem[];
  /** The mentions `labels` does not hold, whenever that set changes; a save waits until it is empty. */
  onMissingChange?: (refs: Ref[]) => void;
  placeholder?: string;
  ariaLabel: string;
  controls?: React.Ref<RichTextEditorHandle>;
}

const SLASH_ROWS: { key: string; label: string; icon: typeof List; trailing: string; run: Pick }[] = [
  { key: 'path', label: 'If / otherwise', icon: GitBranch, trailing: 'Two paths, indented under their condition', run: (e, r) => e.chain().focus().deleteRange(r).insertContent(IF_PATH).run() },
  { key: 'heading', label: 'Heading', icon: Heading2, trailing: 'A section title', run: (e, r) => e.chain().focus().deleteRange(r).setHeading({ level: 2 }).run() },
  { key: 'bullets', label: 'Bulleted list', icon: List, trailing: 'Tab indents an item', run: (e, r) => e.chain().focus().deleteRange(r).toggleBulletList().run() },
  { key: 'numbers', label: 'Numbered list', icon: ListOrdered, trailing: 'Steps in order', run: (e, r) => e.chain().focus().deleteRange(r).toggleOrderedList().run() },
  { key: 'quote', label: 'Note', icon: Quote, trailing: 'A quoted aside', run: (e, r) => e.chain().focus().deleteRange(r).toggleBlockquote().run() },
  { key: 'rule', label: 'Divider', icon: Minus, trailing: 'A line between parts', run: (e, r) => e.chain().focus().deleteRange(r).setHorizontalRule().run() },
];

const EDITOR_CLASS = cn(
  'min-h-48 px-4 py-3 text-sm leading-6 outline-hidden',
  '[&_p]:my-1.5 [&_h1]:mt-4 [&_h1]:mb-2 [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:mt-4 [&_h2]:mb-1.5 [&_h2]:text-base [&_h2]:font-semibold [&_h3]:mt-3 [&_h3]:mb-1 [&_h3]:font-semibold',
  '[&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-6 [&_ol]:my-1 [&_ol]:list-decimal [&_ol]:pl-6 [&_li_p]:my-0.5 [&_li>ul]:my-0.5 [&_li>ol]:my-0.5',
  '[&_blockquote]:my-2 [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground [&_hr]:my-3 [&_hr]:border-border',
  '[&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:font-mono [&_code]:text-xs [&_pre]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:bg-muted [&_pre]:p-3',
  '[&_a]:text-primary [&_a]:underline [&_.is-editor-empty:first-child]:before:pointer-events-none [&_.is-editor-empty:first-child]:before:float-left [&_.is-editor-empty:first-child]:before:h-0 [&_.is-editor-empty:first-child]:before:text-muted-foreground [&_.is-editor-empty:first-child]:before:content-[attr(data-placeholder)]',
);

/**
 * One text editor for the skill and agent screens. Markdown shows as formatting (headings, lists, bold, notes), `@`
 * opens tools, knowledge and skills searched on the server and written as badges, `/` adds a block, and Tab indents a
 * list item for an if or otherwise path. The text stays the source: what is stored is Markdown with `@kind:id`, and a
 * value the person has not edited is handed back as it came. Free text is always valid; only a mention the team no
 * longer holds is reported, through `onMissingChange`.
 */
export function RichTextEditor({ value, onChange, readOnly = false, context, labels, onMissingChange, placeholder = 'Write the steps. Type @ for a tool, knowledge or skill, / for more.', ariaLabel, controls }: RichTextEditorProps) {
  const bridge = React.useRef<MenuBridge | null>(null);
  const [extensions] = React.useState(() => richTextExtensions(() => bridge.current, placeholder));
  const search = useReferenceSearch(context);
  // The last text this editor put out; a value that equals it is the page echoing back and must not reload the document.
  const emitted = React.useRef(value);
  const latest = React.useRef({ onChange, search, onMissingChange });
  latest.current = { onChange, search, onMissingChange };

  const editor = useEditor({
    immediatelyRender: false,
    shouldRerenderOnTransaction: false,
    extensions,
    content: value,
    contentType: 'markdown',
    editable: !readOnly,
    editorProps: { attributes: { role: 'textbox', 'aria-multiline': 'true', 'aria-label': ariaLabel, 'aria-haspopup': 'listbox', 'data-testid': 'rich-text', class: EDITOR_CLASS } },
    onCreate: ({ editor: e }) => keepPlainText(e.markdown),
    onUpdate: ({ editor: e }) => {
      // Only the blocks this edit touched are written again; the rest of the stored text keeps its bytes.
      const text = spliceEdit(e.markdown as unknown as MarkdownIO, e.schema, emitted.current, e.getJSON());
      emitted.current = text;
      latest.current.onChange(text);
    },
  });

  React.useEffect(() => {
    if (!editor || value === emitted.current) return;
    emitted.current = value;
    editor.commands.setContent(value, { contentType: 'markdown', emitUpdate: false });
  }, [editor, value]);
  React.useEffect(() => {
    editor?.setEditable(!readOnly, false);
  }, [editor, readOnly]);

  // Mentions the names do not hold, reported once per change of that set. They are read from the stored text, as the
  // service reads it, so one inside a table, a task list, an image line or code counts too and `word@tool:x` does not.
  // While the names are unread, every mention counts as unchecked, so a save never goes out on a guess. A first report
  // is always made, and an empty one when the editor goes away, so a page holding the last answer never keeps a stale one.
  const gone = React.useRef<string | null>(null);
  React.useEffect(() => {
    const refs = mentionsIn(value).filter((r) => !labels?.some((l) => l.kind === r.kind && l.id === r.id));
    const text = JSON.stringify(refs);
    if (text === gone.current) return;
    gone.current = text;
    latest.current.onMissingChange?.(refs);
  }, [labels, value]);
  React.useEffect(
    () => () => {
      gone.current = null;
      latest.current.onMissingChange?.([]);
    },
    [],
  );

  // ---------- the button bar: view and insert dialogs ----------
  const [view, setView] = React.useState<View>('formatted');
  const [picking, setPicking] = React.useState<InsertableKind | null>(null);
  const insert = (what: InsertableKind | 'path') => {
    if (!editor) return;
    if (what === 'path') insertPath(editor);
    else setPicking(what);
  };
  const place = (item: { kind: Ref['kind']; id: string }) => editor?.chain().focus().insertContent([{ type: 'mention', attrs: { kind: item.kind, id: item.id } }, { type: 'text', text: ' ' }]).run();

  // ---------- the @ and / menus ----------
  const [open, setOpen] = React.useState<OpenMenu | null>(null);
  const [active, setActive] = React.useState('');
  const [found, setFound] = React.useState<{ status: 'loading' | 'ready' | 'error'; groups: ReferenceGroup[] }>({ status: 'loading', groups: [] });
  const menuId = React.useId();
  const searching = open?.trigger === '@';
  const query = open?.query ?? '';
  React.useEffect(() => {
    if (!searching) return;
    let stale = false;
    // One request per pause in typing; the answer for text that has since changed is dropped.
    const timer = setTimeout(() => {
      latest.current.search(query).then(
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

  const sections = React.useMemo<MenuSection<Pick>[]>(() => {
    if (!open) return [];
    if (open.trigger === '@')
      return found.groups.map((g) => ({
        label: g.label,
        rows: g.items.map(
          (item): MenuRow<Pick> => ({
            key: mentionToken(item),
            label: item.label,
            icon: KIND_ICON[item.kind],
            trailing: item.hint,
            disabled: item.disabled,
            pick: (e, range) => e.chain().focus().insertContentAt(range, [{ type: 'mention', attrs: { kind: item.kind, id: item.id } }, { type: 'text', text: ' ' }]).run(),
          }),
        ),
      }));
    const q = open.query.toLowerCase();
    const rows = SLASH_ROWS.filter((r) => r.label.toLowerCase().startsWith(q)).map((r): MenuRow<Pick> => ({ key: r.key, label: r.label, icon: r.icon, trailing: r.trailing, pick: r.run }));
    return rows.length ? [{ label: 'Add', rows }] : [];
  }, [open, found.groups]);

  const status = searching ? found.status : 'ready';
  const rows = React.useMemo(() => sections.flatMap((s) => s.rows).filter((r) => !r.disabled), [sections]);
  React.useEffect(() => {
    if (!rows.some((r) => r.key === active)) setActive(rows[0]?.key ?? '');
  }, [rows, active]);

  const menu = React.useRef({ open, rows, active, status });
  menu.current = { open, rows, active, status };
  bridge.current = {
    show: (trigger, p) => setOpen({ trigger, ...p }),
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
        if (row) m.open.run(row.pick);
        // While the search is out, Enter waits for it instead of breaking the line.
        return !!row || m.status === 'loading';
      }
      return false;
    },
  };

  // The text keeps the caret while the menu is open, so a screen reader is pointed at the list and its highlighted row.
  React.useEffect(() => {
    const dom = editor?.view.dom;
    if (!dom) return;
    dom.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (!open) {
      dom.removeAttribute('aria-controls');
      dom.removeAttribute('aria-activedescendant');
      return;
    }
    const frame = requestAnimationFrame(() => {
      const list = document.getElementById(menuId)?.querySelector('[cmdk-list]');
      const row = list?.querySelector('[cmdk-item][data-selected="true"]');
      if (list?.id) dom.setAttribute('aria-controls', list.id);
      if (row?.id) dom.setAttribute('aria-activedescendant', row.id);
      else dom.removeAttribute('aria-activedescendant');
    });
    return () => cancelAnimationFrame(frame);
  }, [editor, open, active, menuId, status, sections]);

  React.useImperativeHandle(
    controls,
    () => ({
      insert: (text) => {
        if (!editor) return;
        editor.chain().focus('end').insertContent(text, { contentType: 'markdown' }).run();
      },
      // The block that holds that line of the saved text; the text is Markdown, so a line is not a position in the editor.
      focusLine: (line) => {
        if (!editor) return;
        const index = blockAtLine(editor.markdown as unknown as MarkdownIO, editor.schema, emitted.current, line);
        let at = 1;
        editor.state.doc.forEach((_, offset, i) => {
          if (i === index) at = offset + 1;
        });
        setView('formatted');
        editor.chain().focus().setTextSelection(at).scrollIntoView().run();
      },
    }),
    [editor],
  );

  return (
    <MentionLabels.Provider value={labels}>
      <RichTextToolbar editor={editor} disabled={readOnly} view={view} onView={setView} onInsert={insert} />
      {view === 'formatted' ? (
        <EditorContent editor={editor} />
      ) : (
        // The saved text as it is stored, mentions as @kind:id; what is typed here is the text, read again on the way back.
        <Textarea value={value} onChange={(e) => onChange(e.target.value)} readOnly={readOnly} aria-label={`${ariaLabel}, Markdown`} className="min-h-48 rounded-none border-0 font-mono text-xs leading-relaxed shadow-none focus-visible:ring-0" data-testid="rte-markdown" />
      )}
      {picking && <ReferencePickerDialog kind={picking} context={context} open onOpenChange={(o) => !o && setPicking(null)} onPick={place} />}
      {open && editor && view === 'formatted' && (
        <CaretMenu
          rect={() => open.rect?.() ?? null}
          label={open.trigger === '@' ? 'Insert a mention' : 'Add to the text'}
          status={status}
          sections={sections}
          active={active}
          onActive={setActive}
          onPick={(row) => open.run(row.pick)}
          onDismiss={() => setOpen(null)}
          empty={open.trigger === '@' ? (query ? `Nothing called “${query}” in this team.` : 'This team has no tools, knowledge or skills yet.') : `Nothing called “${query}”.`}
          error="Couldn’t search just now. Keep typing to try again."
          id={menuId}
        />
      )}
    </MentionLabels.Provider>
  );
}
