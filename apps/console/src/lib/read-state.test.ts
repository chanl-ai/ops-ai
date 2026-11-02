import assert from 'node:assert/strict';
import { test } from 'node:test';

import { readBadge, waitReason } from './read-state.ts';
import type { Extraction } from './types/extractions.ts';

const field = (confidence: number | null, extra: Record<string, unknown> = {}) => ({ value: 'x', extractedValue: 'x', confidence, needsReview: true, citation: null, ...extra });

const read = (over: Partial<Extraction>): Extraction => ({ id: 'ext_1', fileId: 'f_1', status: 'done', outcome: 'review', floor: 0.8, ...over });

test('a field under the floor is named with its confidence and the floor', () => {
  const r = read({ needsReview: ['notice_no'], fields: { notice_no: field(0.72) } });
  assert.equal(waitReason(r), 'notice_no was read with 72% confidence, under the 80% floor');
});

test('a rejected field names the rule, and a missing one says it was not found', () => {
  const r = read({ needsReview: ['ssn', 'due'], fields: { ssn: field(0, { value: null, rejected: 'masked' }), due: field(null, { value: null }) } });
  assert.equal(waitReason(r), 'ssn broke a rule (masked); due was not found');
});

test('a read nothing marked for a check has no reason to wait', () => {
  assert.equal(waitReason(read({ outcome: 'ok', needsReview: [], fields: { a: { ...field(0.96), needsReview: false } } })), null);
  assert.equal(waitReason(null), null);
});

test('a type Detect could not tell says so', () => {
  assert.equal(waitReason(read({ outcome: 'review', needsReview: ['documentType'], fields: {} })), 'the file matched none of the team’s document types');
});

test('the header names the newest read when nothing was saved on the file', () => {
  assert.equal(readBadge(null, read({ outcome: 'ok', proposal: { name: 'Tax levy notice', fields: [] } })), 'Fields proposed · not saved as a type');
  assert.equal(readBadge(null, read({ outcome: 'ok', text: 'NOTICE', pages: [] })), 'Read as full text');
  assert.equal(readBadge(null, null), null);
  // A read saved on the file is shown as Read as shows it.
  assert.equal(readBadge({ typeId: 't', version: 1, path: 'model', fieldsToCheck: 0, extractionId: 'e', readAt: '' }, read({})), null);
});
