'use client';

import * as React from 'react';
import type { Editor } from '@tiptap/core';
import { useEditorState } from '@tiptap/react';
import { Toolbar as ToolbarPrimitive } from 'radix-ui';
import { Bold, BookOpen, ChevronDown, GitBranch, Heading2, IndentDecrease, IndentIncrease, List, ListOrdered, Sparkles, Wrench } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { toggleVariants } from '@/components/ui/toggle';
import { cn } from '@/lib/utils';

import { type InsertableKind } from './reference-picker-dialog';

export type View = 'formatted' | 'markdown';

/** Indent turns a plain line into a list item first, so the key and the button work from any line. */
export const indent = (e: Editor) => (e.can().sinkListItem('listItem') ? e.chain().focus().sinkListItem('listItem').run() : e.chain().focus().toggleBulletList().run());
export const outdent = (e: Editor) => e.chain().focus().liftListItem('listItem').run();

/** Two paths under their conditions, as nested bullets. */
export const IF_PATH = {
  type: 'bulletList',
  content: [
    { type: 'listItem', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'if …:' }] }, { type: 'bulletList', content: [{ type: 'listItem', content: [{ type: 'paragraph' }] }] }] },
    { type: 'listItem', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'otherwise:' }] }, { type: 'bulletList', content: [{ type: 'listItem', content: [{ type: 'paragraph' }] }] }] },
  ],
};
export const insertPath = (e: Editor) => e.chain().focus().insertContent(IF_PATH).run();

const INSERTS: { kind: InsertableKind; label: string; icon: typeof Wrench }[] = [
  { kind: 'tool', label: 'Tool', icon: Wrench },
  { kind: 'knowledge', label: 'Knowledge', icon: BookOpen },
  { kind: 'skill', label: 'Skill', icon: Sparkles },
];

const item = cn(toggleVariants({ variant: 'outline', size: 'sm' }));

/**
 * The button bar above the editor: formatting toggles, indent and outdent, labelled inserts, and the Formatted or
 * Markdown view. A Radix toolbar, so Tab enters it once and the arrow keys move along it. Below 640px the same actions
 * are one menu.
 */
export function RichTextToolbar({ editor, disabled, view, onView, onInsert }: { editor: Editor | null; disabled: boolean; view: View; onView: (v: View) => void; onInsert: (kind: InsertableKind | 'path') => void }) {
  const on = useEditorState({
    editor,
    selector: ({ editor: e }) => ({ bold: !!e?.isActive('bold'), heading: !!e?.isActive('heading'), bullets: !!e?.isActive('bulletList'), numbers: !!e?.isActive('orderedList'), canOutdent: !!e?.can().liftListItem('listItem') }),
  });
  const off = disabled || !editor || view === 'markdown';
  const run = (fn: (e: Editor) => unknown) => () => editor && fn(editor);
  const state = on ?? { bold: false, heading: false, bullets: false, numbers: false, canOutdent: false };
  const toggles: { key: string; label: string; icon: typeof Bold; active: boolean; run: () => void }[] = [
    { key: 'bold', label: 'Bold', icon: Bold, active: state.bold, run: run((e) => e.chain().focus().toggleBold().run()) },
    { key: 'heading', label: 'Heading', icon: Heading2, active: state.heading, run: run((e) => e.chain().focus().toggleHeading({ level: 2 }).run()) },
    { key: 'bullets', label: 'Bulleted list', icon: List, active: state.bullets, run: run((e) => e.chain().focus().toggleBulletList().run()) },
    { key: 'numbers', label: 'Numbered list', icon: ListOrdered, active: state.numbers, run: run((e) => e.chain().focus().toggleOrderedList().run()) },
  ];
  return (
    <>
      <ToolbarPrimitive.Root aria-label="Text formatting and inserts" className="hidden flex-wrap items-center gap-1 border-b px-2 py-1.5 sm:flex" data-testid="rte-toolbar">
        {toggles.map((t) => (
          <ToolbarPrimitive.Button key={t.key} aria-label={t.label} aria-pressed={t.active} title={t.label} disabled={off} onClick={t.run} data-state={t.active ? 'on' : 'off'} className={item} data-testid={`rte-${t.key}`} onMouseDown={(e) => e.preventDefault()}>
            <t.icon aria-hidden />
          </ToolbarPrimitive.Button>
        ))}
        <ToolbarPrimitive.Button aria-label="Outdent" title="Outdent (Shift+Tab)" disabled={off || !state.canOutdent} onClick={run(outdent)} className={item} data-testid="rte-outdent" onMouseDown={(e) => e.preventDefault()}>
          <IndentDecrease aria-hidden />
        </ToolbarPrimitive.Button>
        <ToolbarPrimitive.Button aria-label="Indent" title="Indent (Tab)" disabled={off} onClick={run(indent)} className={item} data-testid="rte-indent" onMouseDown={(e) => e.preventDefault()}>
          <IndentIncrease aria-hidden />
        </ToolbarPrimitive.Button>
        <ToolbarPrimitive.Separator className="mx-1 h-5 w-px bg-border" />
        {INSERTS.map((i) => (
          <ToolbarPrimitive.Button key={i.kind} disabled={off} onClick={() => onInsert(i.kind)} className={item} data-testid={`rte-insert-${i.kind}`}>
            <i.icon aria-hidden /> {i.label}
          </ToolbarPrimitive.Button>
        ))}
        <ToolbarPrimitive.Button disabled={off} onClick={() => onInsert('path')} className={item} data-testid="rte-insert-path">
          <GitBranch aria-hidden /> If / else
        </ToolbarPrimitive.Button>
        <ToolbarPrimitive.ToggleGroup type="single" value={view} onValueChange={(v) => v && onView(v as View)} aria-label="View" className="ml-auto flex items-center gap-1">
          <ToolbarPrimitive.ToggleItem value="formatted" className={item} data-testid="rte-view-formatted">
            Formatted
          </ToolbarPrimitive.ToggleItem>
          <ToolbarPrimitive.ToggleItem value="markdown" className={item} data-testid="rte-view-markdown">
            Markdown
          </ToolbarPrimitive.ToggleItem>
        </ToolbarPrimitive.ToggleGroup>
      </ToolbarPrimitive.Root>
      <div className="flex border-b px-2 py-1.5 sm:hidden" data-testid="rte-toolbar-menu">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" aria-label="Text formatting and inserts" data-testid="rte-menu">
              Format <ChevronDown className="size-3.5" aria-hidden />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" collisionPadding={12} className="max-h-[min(24rem,70vh)] overflow-y-auto">
            <DropdownMenuLabel>Format</DropdownMenuLabel>
            {toggles.map((t) => (
              <DropdownMenuItem key={t.key} disabled={off} onSelect={t.run}>
                <t.icon aria-hidden /> {t.label}
                {t.active && <span className="ml-auto text-xs text-muted-foreground">On</span>}
              </DropdownMenuItem>
            ))}
            <DropdownMenuItem disabled={off || !state.canOutdent} onSelect={run(outdent)}>
              <IndentDecrease aria-hidden /> Outdent
            </DropdownMenuItem>
            <DropdownMenuItem disabled={off} onSelect={run(indent)}>
              <IndentIncrease aria-hidden /> Indent
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>Insert</DropdownMenuLabel>
            {INSERTS.map((i) => (
              <DropdownMenuItem key={i.kind} disabled={off} onSelect={() => onInsert(i.kind)} data-testid={`rte-menu-insert-${i.kind}`}>
                <i.icon aria-hidden /> {i.label}
              </DropdownMenuItem>
            ))}
            <DropdownMenuItem disabled={off} onSelect={() => onInsert('path')} data-testid="rte-menu-insert-path">
              <GitBranch aria-hidden /> If / else
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>View</DropdownMenuLabel>
            <DropdownMenuRadioGroup value={view} onValueChange={(v) => onView(v as View)}>
              <DropdownMenuRadioItem value="formatted" data-testid="rte-menu-view-formatted">
                Formatted
              </DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="markdown" data-testid="rte-menu-view-markdown">
                Markdown
              </DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </>
  );
}
