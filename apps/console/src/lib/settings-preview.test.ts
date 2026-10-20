// The settings tree mock, by failure mode: a setting from the review left without a home, a home that points at no page
// in the tree, and a Find box that cannot reach a setting by the number the review used.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { DIALOGS, findSettings, PREVIEW_ROOT, S_MAP, SECTIONS } from './settings-preview.ts';

test('every setting S01 to S43 has exactly one home', () => {
  const want = Array.from({ length: 43 }, (_, i) => `S${String(i + 1).padStart(2, '0')}`);
  assert.deepEqual(S_MAP.map((m) => m.s), want);
});

test('a home inside the mock names a page of the tree; one that stays on its object links to a live page', () => {
  const pages = new Set([...SECTIONS.map((s) => s.href), `${PREVIEW_ROOT}/account`]);
  for (const m of S_MAP) {
    const path = m.href.split('#')[0];
    if (m.href.startsWith(PREVIEW_ROOT)) assert.ok(pages.has(path), `${m.s} points at ${m.href}, which is not a page of the tree`);
    else assert.ok(m.move === 'stays on the object' || m.move === 'new home', `${m.s} links to a live page but is marked ${m.move}`);
  }
});

test('Find reaches a setting by its number, its name and its role', () => {
  assert.equal(findSettings('S15')[0]?.label, 'Egress hosts');
  assert.ok(findSettings('egress').some((h) => h.label === 'Egress hosts'));
  assert.ok(findSettings('security admin').length > 5);
  assert.deepEqual(findSettings('  '), []);
});

test('every dialog names a page of the tree as its mother page', () => {
  const pages = new Set(SECTIONS.map((s) => s.href));
  for (const d of DIALOGS) assert.ok(pages.has(d.mother.split('#')[0]), `${d.dialog}: ${d.mother}`);
});
