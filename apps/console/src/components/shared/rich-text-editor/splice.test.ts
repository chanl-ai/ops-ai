// An edit must change only the edited block of the stored text; every other line keeps its exact bytes.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { getSchema } from '@tiptap/core';
import { MarkdownManager } from '@tiptap/markdown';
import { StarterKit } from '@tiptap/starter-kit';

import { ReferenceNode, keepPlainText } from './markdown.ts';
import { spliceEdit } from './splice.ts';

const extensions = [StarterKit, ReferenceNode];
const manager = new MarkdownManager({ extensions });
keepPlainText(manager);
const schema = getSchema(extensions);

const SRC = ['# Refund *** 123 ****', '', 'Keep _x_ and order_id as written, and <tag> too.', '', '* if the order is new:', '    * refund in full', '* otherwise:', '    * offer credit', '', 'Last line @tool:order_lookup.', '', '```', 'a_b * c <d>', '', 'e', '```', ''].join('\n');

/** The document as the editor would hold it after `edit` changed it. */
const edited = (edit: (doc: { content: any[] }) => void) => {
  const doc = manager.parse(SRC) as { content: any[] };
  edit(doc);
  return doc;
};
const textOf = (block: any): any => block.content.find((n: any) => n.type === 'text');

test('editing one line leaves every other line byte-identical', () => {
  const doc = edited((d) => {
    textOf(d.content[1]).text = 'Keep _x_ and order_id as written, and <tag> too, then stop.';
  });
  const out = spliceEdit(manager as never, schema, SRC, doc);
  // The edited paragraph is written by the library (here it escapes `_x_`), so compare every other line.
  const lines = (s: string) => s.split('\n');
  const [a, b] = [lines(out), lines(SRC)];
  assert.equal(a.length, b.length);
  a.forEach((line, i) => {
    if (i !== 2) assert.equal(line, b[i]);
  });
});

test('an unedited document comes back as the same text', () => {
  assert.equal(spliceEdit(manager as never, schema, SRC, manager.parse(SRC)), SRC);
});

test('an edit inside a nested bullet rewrites only that list', () => {
  const doc = edited((d) => {
    const list = d.content.find((n) => n.type === 'bulletList');
    textOf(list.content[0].content[1].content[0].content[0]).text = 'refund in full today';
  });
  const out = spliceEdit(manager as never, schema, SRC, doc);
  assert.ok(out.startsWith(SRC.slice(0, SRC.indexOf('* if the order'))), 'blocks before the list are untouched');
  assert.ok(out.endsWith(SRC.slice(SRC.indexOf('Last line'))), 'blocks after the list are untouched');
  assert.ok(out.includes('refund in full today'));
});
