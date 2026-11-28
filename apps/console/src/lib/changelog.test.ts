import assert from 'node:assert/strict';
import { test } from 'node:test';

import { groupByRelease, hasUnseen, parseChangelog } from './changelog.ts';

const entry = (id: string, date: string, version = '', tag = 'new') => ({ id, version, date, title: id, description: 'A change.', tag });

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

test('the upcoming release comes first, then versions newest first (numerically), then the folded history', () => {
  const source = JSON.stringify([
    entry('h', '2026-10-01', 'earlier'),
    entry('a', '2026-11-19', '1.0.0'),
    entry('c', '2026-11-25', '1.10.0'),
    entry('b', '2026-11-25', '1.2.0'),
    entry('u', '2026-11-26'),
  ]);
  assert.deepEqual(parseChangelog(source).map((e) => e.id), ['u', 'c', 'b', 'a', 'h']);
});

test('a release shows its new and improved entries as rows and its fixes apart', () => {
  const groups = groupByRelease(
    parseChangelog(JSON.stringify([entry('f1', '2026-11-25', '1.1.0', 'fix'), entry('n', '2026-11-25', '1.1.0'), entry('f2', '2026-11-25', '1.1.0', 'fix'), entry('i', '2026-11-25', '1.1.0', 'improved'), entry('u', '2026-11-26')])),
  );
  assert.deepEqual(groups.map((g) => [g.version, g.changes.map((e) => e.id), g.fixes.length]), [
    ['', ['u'], 0],
    ['1.1.0', ['n', 'i'], 2],
  ]);
});
