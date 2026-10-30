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
    { ...entry('plugins', '2026-10-30'), switch: 'NEXT_PUBLIC_OPS_PLUGINS' },
    { ...entry('typo', '2026-10-30'), switch: 'NEXT_PUBLIC_OPS_PLUGINZ' },
    entry('everyone', '2026-10-30'),
  ]);
  assert.deepEqual(parseChangelog(source, { NEXT_PUBLIC_OPS_PLUGINS: false }).map((e) => e.id), ['everyone']);
  assert.deepEqual(parseChangelog(source, { NEXT_PUBLIC_OPS_PLUGINS: true }).map((e) => e.id).sort(), ['everyone', 'plugins']);
  // The console's own switches, read from its environment: with none set, as on a release that has not turned them on.
  assert.deepEqual(parseChangelog(source).map((e) => e.id), ['everyone']);
});
