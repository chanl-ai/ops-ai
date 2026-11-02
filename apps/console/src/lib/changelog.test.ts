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

test('an entry for a feature behind a release switch shows only while that switch is on, and an unknown switch hides it', () => {
  const source = JSON.stringify([
    { ...entry('beta', '2026-10-30'), switch: 'NEXT_PUBLIC_OPS_EXAMPLE' },
    { ...entry('typo', '2026-10-30'), switch: 'NEXT_PUBLIC_OPS_EXAMPLZ' },
    entry('everyone', '2026-10-30'),
  ]);
  assert.deepEqual(parseChangelog(source, { NEXT_PUBLIC_OPS_EXAMPLE: false }).map((e) => e.id), ['everyone']);
  assert.deepEqual(parseChangelog(source, { NEXT_PUBLIC_OPS_EXAMPLE: true }).map((e) => e.id).sort(), ['beta', 'everyone']);
  // The console's own list, which is empty: a shipped feature has no switch, so an entry naming one never shows.
  assert.deepEqual(parseChangelog(source).map((e) => e.id), ['everyone']);
});
