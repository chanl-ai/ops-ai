import assert from 'node:assert/strict';
import { test } from 'node:test';

import { middleShorten } from './middle-shorten.ts';

test('a long word id keeps whole words at both ends instead of cutting mid-word', () => {
  assert.equal(middleShorten('gr_no_investment_advice', 12, 6), 'gr_no_…advice');
  assert.equal(middleShorten('mbx_complaints_inbox_greenmail', 12, 6), 'mbx_complaints_…greenmail');
});

test('an id with no word breaks is cut at the counts, and one the ellipsis would not shorten stays whole', () => {
  assert.equal(middleShorten('9f3a8c2d41d0e5b7a6c3', 6, 4), '9f3a8c…a6c3');
  assert.equal(middleShorten('mbx_complaints_greenmail', 12, 6), 'mbx_complaints_greenmail');
  assert.equal(middleShorten('short_id', 12, 6), 'short_id');
});
