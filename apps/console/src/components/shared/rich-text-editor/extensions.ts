/**
 * The rich text editor's schema: Tiptap's starter kit (paragraphs, headings, lists, bold, italic, code, history), a
 * placeholder, a Markdown reader and writer, a mention node for `@kind:id` references and a slash menu. The stored text
 * is Markdown with `@kind:id` tokens; the editor never has a format of its own.
 */
import { Extension, type Editor, type Range } from '@tiptap/core';
import { Markdown } from '@tiptap/markdown';
import { Placeholder } from '@tiptap/extensions';
import { StarterKit } from '@tiptap/starter-kit';
import { PluginKey } from '@tiptap/pm/state';
import { ReactNodeViewRenderer } from '@tiptap/react';
import { Suggestion, type SuggestionKeyDownProps, type SuggestionProps } from '@tiptap/suggestion';

import { MarkdownBlock, ReferenceNode } from './markdown';
import { MentionView } from './mention-view';

export type Trigger = '@' | '/';

/** What the editor tells the page about the open menu; the page draws it with CaretMenu. */
export interface MenuBridge {
  show: (trigger: Trigger, props: { query: string; rect: (() => DOMRect | null) | null; run: (pick: (editor: Editor, range: Range) => void) => void }) => void;
  hide: (trigger: Trigger) => void;
  /** True when the menu used the key. */
  key: (event: KeyboardEvent) => boolean;
}

/** One suggestion plugin that forwards to the bridge; Mention and the slash menu are both this. */
export function suggestionFor(trigger: Trigger, bridge: () => MenuBridge | null) {
  return {
    char: trigger,
    // Mention's own command writes `id`/`label`; the pick closures in the page insert the node, so nothing runs here.
    command: () => undefined,
    items: () => [],
    render: () => {
      const show = (p: SuggestionProps) => bridge()?.show(trigger, { query: p.query, rect: p.clientRect ?? null, run: (pick) => pick(p.editor, p.range) });
      return {
        onStart: show,
        onUpdate: show,
        onExit: () => bridge()?.hide(trigger),
        onKeyDown: ({ event }: SuggestionKeyDownProps) => bridge()?.key(event) ?? false,
      };
    },
  };
}

/** `@kind:id` as an inline node with a badge, written back as the same token. */
export const ReferenceMention = (bridge: () => MenuBridge | null) =>
  ReferenceNode.extend({
    addNodeView() {
      return ReactNodeViewRenderer(MentionView, { as: 'span', className: 'inline' });
    },
  }).configure({ suggestion: { ...suggestionFor('@', bridge), pluginKey: new PluginKey('mentionSuggestion') } });

/** `/` at the start of a word opens the slash menu; what it offers is the page's. */
export const SlashMenu = (bridge: () => MenuBridge | null) =>
  Extension.create({
    name: 'slashMenu',
    addProseMirrorPlugins() {
      return [Suggestion({ editor: this.editor, pluginKey: new PluginKey('slashSuggestion'), ...suggestionFor('/', bridge) })];
    },
  });

export const richTextExtensions = (bridge: () => MenuBridge | null, placeholder: string) => [
  StarterKit.configure({ link: { openOnClick: false } }),
  Placeholder.configure({ placeholder }),
  Markdown,
  MarkdownBlock,
  ReferenceMention(bridge),
  SlashMenu(bridge),
];
