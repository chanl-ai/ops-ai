// Every reader of stored text finds the same mentions: the save gate, the editor's Markdown reader and the document editor.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { parseText } from '../components/shared/instruction-document/document-model.ts';
import { mentionsIn, unheldMentions } from './mentions.ts';

const TEXT = ['Use @tool:a_b, then @knowledge:kb-1.', '| t | u |', '|---|---|', '| @skill:in_a_table | x |', '', '- [ ] ask @agent:ag_1', '', '`@workflow:in_code`', '', 'mail ann@tool:not_one and é@tool:nor_this and @tool:a_b again'].join('\n');

test('mentions in a table, a task list and code count, a word before @ does not, and each is listed once', () => {
  assert.deepEqual(
    mentionsIn(TEXT).map((r) => `${r.kind}:${r.id}`),
    ['tool:a_b', 'knowledge:kb-1', 'skill:in_a_table', 'agent:ag_1', 'workflow:in_code'],
  );
});

test('the document editor reads the same mentions from the same text', () => {
  const seen = new Set(parseText(TEXT).flatMap((s) => (s.t === 'ref' ? [`${s.kind}:${s.id}`] : [])));
  assert.deepEqual([...seen].sort(), mentionsIn(TEXT).map((r) => `${r.kind}:${r.id}`).sort());
});

test('mentions the names do not hold: all while they load, none when they could not load, the unknown ones when loaded', () => {
  const text = 'Use @tool:a and @tool:b.';
  const labels = [{ kind: 'tool', id: 'a' }] as never;
  assert.deepEqual(unheldMentions(text, undefined, false).map((r) => r.id), ['a', 'b']);
  assert.deepEqual(unheldMentions(text, undefined, true), []);
  assert.deepEqual(unheldMentions(text, labels, false).map((r) => r.id), ['b']);
});
