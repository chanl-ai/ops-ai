/**
 * How the editor reads and writes the stored text, kept apart from React so a test can run it headless. The stored text
 * is Markdown with `@kind:id` tokens, so `@` mentions get their own token and the library's escaping is narrowed to what
 * would change the text on the next read.
 */
import { Node } from '@tiptap/core';
import Mention from '@tiptap/extension-mention';

import type { Ref } from '@/lib/types/references';

export const MENTION_AT = /^@(tool|knowledge|skill|agent|workflow):([A-Za-z0-9](?:[A-Za-z0-9_.-]{0,126}[A-Za-z0-9_])?)/;
export const mentionToken = (r: Ref) => `@${r.kind}:${r.id}`;

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
    start: (src: string) => src.search(/@(?:tool|knowledge|skill|agent|workflow):/),
    tokenize: (src: string) => {
      const m = MENTION_AT.exec(src);
      return m ? { type: 'mention', raw: m[0], kind: m[1], id: m[2] } : undefined;
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
export function opaqueBlockAt(src: string): string | undefined {
  const block = /^(?:[^\n]*\S[^\n]*(?:\n|$))+/.exec(src)?.[0].replace(/\n+$/, '');
  if (!block) return undefined;
  const lines = block.split('\n');
  const heading = /^ {0,3}(#{1,6}\s|```|~~~|>)/.test(block);
  const isTable = lines.length > 1 && lines[0].includes('|') && TABLE_RULE.test(lines[1]);
  const isDef = /^ {0,3}\[[^\]\n]+\]:\s*\S/.test(block);
  const isTask = /^\s*[-*+]\s+\[[ xX]\]\s/.test(block);
  const hasImage = !heading && /!\[[^\]\n]*\]\([^)\n]*\)/.test(block);
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
