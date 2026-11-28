import assert from 'node:assert/strict';
import { test } from 'node:test';

import { baseHeader, factLine } from './fact-line.ts';

const line = (h: { lead: string | null; facts: string }) => `${h.lead ?? ''}${h.facts}`.trim();

test('a base header with no description starts with its facts, not a dot', () => {
  assert.equal(line(baseHeader({ description: '', collections: [], synced: 'never' })), 'All collections · synced never');
  assert.equal(line(baseHeader({ description: 'Claims rules', collections: ['Motor'], synced: '2h ago' })), 'Claims rules · Collections: Motor · synced 2h ago');
});

test('an image caption with no description shows only its size', () => {
  assert.equal(factLine(['', '1280 × 720']), '1280 × 720');
});
