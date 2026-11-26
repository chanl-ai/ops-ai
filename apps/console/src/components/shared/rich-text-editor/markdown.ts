/**
 * How the editor reads and writes the stored text, kept apart from React so a test can run it headless. The stored text
 * is Markdown with `@kind:id` tokens, so `@` mentions get their own token and the library's escaping is narrowed to what
 * would change the text on the next read.
 */
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
