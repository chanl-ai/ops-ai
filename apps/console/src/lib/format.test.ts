import assert from 'node:assert/strict';
import { test } from 'node:test';

import { money, relativeTime } from './format.ts';

// A Human Task whose step read no account has an amount but no currency; naming one would be invented.
test('money shows a bare amount when the currency is unknown', () => {
  assert.equal(money(3250, null), '3,250.00');
});

// "$12,400" reads as US dollars to half the people who see it; the code says which.
test('money names the currency by its ISO code', () => {
  assert.equal(money(12400, 'CAD'), '12,400.00 CAD');
  assert.equal(money(950.5, 'USD'), '950.50 USD');
});

test('a time ahead reads as ahead, never "just now"; one behind reads as behind', () => {
  const now = Date.parse('2026-10-19T12:00:00Z');
  assert.equal(relativeTime('2026-10-19T12:30:00Z', now), 'in 30m');
  assert.equal(relativeTime('2026-10-19T15:00:00Z', now), 'in 3h');
  assert.equal(relativeTime('2026-10-19T11:30:00Z', now), '30m ago');
  assert.equal(relativeTime('2026-10-19T11:59:40Z', now), 'just now');
  // Ninety days ahead is a date, as a grant's end reads.
  assert.equal(relativeTime('2027-01-17T12:00:00Z', now), 'Jan 17');
});
