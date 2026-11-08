import assert from 'node:assert/strict';
import { test } from 'node:test';

import { hasEveryWord } from './search-words.ts';

// The Cases page showed nothing for "documents application" although the server found three: the table filtered its
// page again on the subject as one phrase.
const LOAN = ['Loan application: Nguyen Family Pharmacy, waiting on documents: a signed guarantee', 'Nguyen Family Pharmacy'];

test('several words match when each is in the record', () => {
  assert.equal(hasEveryWord(LOAN, 'application documents'), true);
});

test('words match in any order and any case, across subject and customer', () => {
  assert.equal(hasEveryWord(LOAN, 'PHARMACY documents'), true);
});

test('one word matches as before, and a word the record lacks does not', () => {
  assert.equal(hasEveryWord(LOAN, 'nguyen'), true);
  assert.equal(hasEveryWord(LOAN, 'application mortgage'), false);
});
