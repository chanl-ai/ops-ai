// The editor's text is Markdown with @kind:id mentions; what it writes after an edit must read back as the same text.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { MarkdownManager } from '@tiptap/markdown';
import { StarterKit } from '@tiptap/starter-kit';

import { ReferenceNode, keepPlainText } from './markdown.ts';

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
