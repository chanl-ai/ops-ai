// The alert on a read no reply answered says how its retries went, from how many times the model was asked.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { notReadSaid } from './not-read-said.ts';

test('the reason says how the retries went', () => {
  assert.equal(notReadSaid('cut_off', 2), 'The model’s reply stopped at its length limit, and the one retry stopped too. No field was saved.');
  assert.match(notReadSaid('empty', 3), /all 2 retries stopped too/);
  assert.match(notReadSaid('cut_off', 1), /no retry was made/);
  assert.match(notReadSaid('declined', 1), /no retry was made/);
});

test('a read saved before the count was kept says nothing about retries', () => {
  assert.equal(notReadSaid('cut_off', null), 'The model’s reply stopped at its length limit. No field was saved.');
});
