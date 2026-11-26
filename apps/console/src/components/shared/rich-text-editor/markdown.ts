/**
 * How the editor reads and writes the stored text, kept apart from React so a test can run it headless. The stored text
 * is Markdown with `@kind:id` tokens, so `@` mentions get their own token and the library's escaping is narrowed to what
 * would change the text on the next read.
 */
import { Node } from '@tiptap/core';
import Mention from '@tiptap/extension-mention';

import { MENTION_SOURCE, NOT_AFTER_WORD, mentionAt, mentionToken } from '../../../lib/mentions.ts';
import type { Ref } from '@/lib/types/references';

const MENTION_START = new RegExp(`${NOT_AFTER_WORD}${MENTION_SOURCE}`, 'u');

/** The mention node's data and Markdown spelling; the editor adds the badge view and the `@` menu on top. */
export const ReferenceNode = Mention.extend({
  name: 'mention',
  addAttributes() {
    return { kind: { default: 'tool' }, id: { default: '' } };
  },
  parseHTML() {
    return [{ tag: 'span[data-reference]', getAttrs: (el) => ({ kind: (el as HTMLElement).dataset.kind, id: (el as HTMLElement).dataset.id }) }];
  },
  renderHTML({ node }) {
    return ['span', { 'data-reference': '', 'data-kind': node.attrs.kind, 'data-id': node.attrs.id }, mentionToken(node.attrs as Ref)];
  },
  renderText: ({ node }) => mentionToken(node.attrs as Ref),
  markdownTokenizer: {
    name: 'mention',
    level: 'inline',
    start: (src: string) => src.search(MENTION_START),
    // The text before it is the previous token's: `word@tool:x` is a word, as the service reads it.
    tokenize: (src: string, tokens?: { raw?: string }[]) => {
      const m = mentionAt(src, tokens?.at(-1)?.raw ?? '');
      return m ? { type: 'mention', raw: m.raw, kind: m.kind, id: m.id } : undefined;
    },
  },
  parseMarkdown: (token, h) => h.createNode('mention', { kind: token.kind, id: token.id }),
  renderMarkdown: (node) => mentionToken(node.attrs as Ref),
});

/**
 * Markdown the editor has no node for (a table, an image, a link definition, a task list) is held as one block of its
 * own text and written back exactly as it was read, so opening and saving never drops or flattens it. It is edited in
 * the Markdown view.
 */
const TABLE_RULE = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const LIST_ITEM = /^ *(?:[-*+]|\d{1,9}[.)])\s/;
const TASK_ITEM = /^ *(?:[-*+]|\d{1,9}[.)])\s+\[[ xX]\]\s/m;
const NON_BLANK_RUN = /^(?:[^\n]*\S[^\n]*(?:\n|$))+/;

/**
 * The text of the block that starts `src`: its lines up to a blank line. A list goes on past blank lines for as long as
 * the next line is another item or is indented under one, because a task item anywhere in a list holds the whole list.
 */
function blockText(src: string): string | undefined {
  const first = NON_BLANK_RUN.exec(src)?.[0];
  if (!first) return undefined;
  let block = first;
  if (LIST_ITEM.test(first)) {
    for (;;) {
      const gap = /^\n+/.exec(src.slice(block.length))?.[0];
      const more = gap ? NON_BLANK_RUN.exec(src.slice(block.length + gap.length))?.[0] : undefined;
      if (!gap || !more || !(LIST_ITEM.test(more) || /^ {2,}\S/.test(more))) break;
      block += gap + more;
    }
  }
  return block.replace(/\n+$/, '');
}

export function opaqueBlockAt(src: string): string | undefined {
  const block = blockText(src);
  if (!block) return undefined;
  const lines = block.split('\n');
  // Code keeps its characters as text, so an image written inside it is not an image.
  const fenced = /^ {0,3}(```|~~~)/.test(block);
  const isTable = lines.length > 1 && lines[0].includes('|') && TABLE_RULE.test(lines[1]);
  const isDef = /^ {0,3}\[[^\]\n]+\]:\s*\S/.test(block);
  const isTask = LIST_ITEM.test(block) && TASK_ITEM.test(block);
  const hasImage = !fenced && /!\[[^\]\n]*\]\([^)\n]*\)/.test(block);
  return isTable || isDef || isTask || hasImage ? block : undefined;
}

export const MarkdownBlock = Node.create({
  name: 'markdownBlock',
  group: 'block',
  atom: true,
  addAttributes() {
    return { raw: { default: '' } };
  },
  parseHTML() {
    return [{ tag: 'pre[data-markdown-block]', getAttrs: (el) => ({ raw: (el as HTMLElement).textContent ?? '' }) }];
  },
  renderHTML({ node }) {
    return ['pre', { 'data-markdown-block': '', class: 'whitespace-pre-wrap' }, node.attrs.raw];
  },
  renderText: ({ node }) => node.attrs.raw,
  markdownTokenizer: {
    name: 'markdownBlock',
    level: 'block',
    // Never cuts a paragraph short: only a block that begins with it is held.
    start: () => -1,
    tokenize: (src: string) => {
      const raw = opaqueBlockAt(src);
      return raw ? { type: 'markdownBlock', raw, text: raw } : undefined;
    },
  },
  parseMarkdown: (token, h) => h.createNode('markdownBlock', { raw: token.raw }),
  renderMarkdown: (node) => String(node.attrs?.raw ?? ''),
});

interface Writer {
  codeTypes: Set<string>;
  encodeTextForMarkdown: (text: string, node: { marks?: (string | { type: string })[] }, parent?: { type?: string } | null) => string;
  escapeMarkdownSyntax: (text: string) => string;
}

/**
 * The library writes `snake_case` as `snake\_case` and `<` as `&lt;`, which would put backslashes and entities into
 * text a person wrote plainly. Only a backslash, a backtick, `*`, and a `_` at the edge of a word would be read as
 * formatting next time, so only those are escaped, and nothing is turned into an entity. Code keeps its characters.
 */
export function keepPlainText(manager: object | undefined): void {
  const w = manager as Writer | undefined;
  if (!w) return;
  w.escapeMarkdownSyntax = (text) => text.replace(/[\\`*]|(?<![A-Za-z0-9])_|_(?![A-Za-z0-9])/g, '\\$&');
  w.encodeTextForMarkdown = (text, node, parent) => {
    const inCode = (parent?.type != null && w.codeTypes.has(parent.type)) || (node.marks ?? []).some((m) => w.codeTypes.has(typeof m === 'string' ? m : m.type));
    return inCode ? text : w.escapeMarkdownSyntax(text);
  };
}
