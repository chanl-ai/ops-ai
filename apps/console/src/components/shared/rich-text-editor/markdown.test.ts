// The editor's text is Markdown with @kind:id mentions; what it writes after an edit must read back as the same text.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { MarkdownManager } from '@tiptap/markdown';
import { StarterKit } from '@tiptap/starter-kit';

import { ReferenceNode, keepPlainText, opaqueBlockAt } from './markdown.ts';

const manager = new MarkdownManager({ extensions: [StarterKit, ReferenceNode] });
keepPlainText(manager);
const roundTrip = (text: string) => manager.serialize(manager.parse(text));

test('a skill written with headings, bold, lists, if paths and mentions is written back unchanged', () => {
  const text = ['# Refund a charge', '', 'Look up the order with @tool:order_lookup and cite @knowledge:refund-policy.', '', '- if the order is under 30 days old:', '  - refund in full', '- otherwise:', '  - offer store credit', '', 'Never promise a date. Use **bold** for amounts, like 5 < 7 & order_id.'].join('\n');
  assert.equal(roundTrip(text), text);
});

test('a mention reads as one node with its kind and id, not as text', () => {
  const doc = manager.parse('Use @skill:hardship_triage now.');
  const node = doc.content?.[0].content?.find((n) => n.type === 'mention');
  assert.deepEqual(node?.attrs, { kind: 'skill', id: 'hardship_triage' });
});

test('literal markers that are not formatting stay as written', () => {
  const text = 'Call 1 * 2 and keep *** 123 **** as it is.';
  assert.equal(roundTrip(text), text.replace(/\*/g, '\\*'));
});

test('a word that ends right before @tool:x is text, as the service reads it, and a mention after a space is a node', () => {
  const kinds = (text: string) => (manager.parse(text).content?.[0].content ?? []).map((n) => n.type);
  assert.deepEqual(kinds('mail ann@tool:order_lookup now'), ['text']);
  assert.deepEqual(kinds('call @tool:order_lookup now'), ['text', 'mention', 'text']);
});

// A task item is held with the whole list around it, wherever it sits and however it is numbered.
test('a list with a task item anywhere in it is held whole', () => {
  for (const list of ['- plain\n- [ ] later', '- plain\n  - [x] nested', '1. [ ] numbered\n2. plain', '- a\n\n- [ ] after a blank line']) assert.equal(opaqueBlockAt(`${list}\n\nNext paragraph.`), list, list);
});

test('a list with no task item, and an image inside code, are not held', () => {
  assert.equal(opaqueBlockAt('- a\n- b [x] c'), undefined);
  assert.equal(opaqueBlockAt('```\n![x](y)\n```'), undefined);
});

test('an image in a heading is held', () => {
  assert.equal(opaqueBlockAt('# Logo ![x](https://example.com/x.png)'), '# Logo ![x](https://example.com/x.png)');
});
