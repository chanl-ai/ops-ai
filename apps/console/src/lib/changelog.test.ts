import assert from 'node:assert/strict';
import { test } from 'node:test';

import { hasUnseen, parseChangelog } from './changelog.ts';

const entry = (id: string, date: string) => ({ id, date, title: id, description: 'A change.', tag: 'new' });

test('a second entry the same day shows the dot after the first was seen', () => {
  const entries = parseChangelog(JSON.stringify([entry('a', '2026-10-22'), entry('b', '2026-10-22')]));
  assert.equal(hasUnseen(entries, ['a']), true);
  assert.equal(hasUnseen(entries, ['a', 'b']), false);
});

test('no entries means no dot, and a malformed source shows nothing rather than failing', () => {
  assert.equal(hasUnseen(parseChangelog('[]'), []), false);
  assert.deepEqual(parseChangelog('not json'), []);
});

test('entries read newest first', () => {
  assert.deepEqual(parseChangelog(JSON.stringify([entry('old', '2026-10-01'), entry('new', '2026-10-22')])).map((e) => e.id), ['new', 'old']);
});
