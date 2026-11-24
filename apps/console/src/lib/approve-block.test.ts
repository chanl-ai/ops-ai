// What holds Approve on a document read, by failure mode: a read no reply answered offered for approval on a step that
// cannot take typed values (the server refuses it with not_editable), Approve enabled while a required field is empty,
// and a refusal shown in words other than the server's.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { DocumentRead } from './types/domain.ts';

import { approveBlock, portHolds } from './approve-block.ts';

const notRead = { value: null, extractedValue: null, confidence: 0, needsReview: true, citation: null };
const read = (over: Partial<DocumentRead> = {}): DocumentRead => ({
  fileId: 'fil_88213',
  fileName: 'NWF-88213.pdf',
  floor: 0.8,
  schema: [
    { key: 'invoice', label: 'Invoice number', type: 'text', required: true },
    { key: 'total', label: 'Total', type: 'money', required: true },
    { key: 'po', label: 'PO number', type: 'text', required: false },
  ],
  records: [{ values: { invoice: null, total: null, po: null }, fields: { invoice: notRead, total: notRead, po: notRead } }],
  editable: true,
  corrected: null,
  notRead: 'cut_off',
  approveRefused: null,
  ...over,
});

test('a read the step cannot take typed values for is held with the server’s reason', () => {
  const message = 'This version of Extract a file cannot take typed values, so this task can only be rejected.';
  assert.equal(approveBlock(read({ editable: false, approveRefused: { code: 'not_editable', message } }), {}, {}), message);
});

test('Approve waits for every required field of a read with no answer, and an optional one does not hold it', () => {
  assert.equal(approveBlock(read(), {}, {}), 'type 2 required fields first');
  assert.equal(approveBlock(read(), {}, { 0: { invoice: 'NWF-88213', total: ' ' } }), 'type 1 required field first');
  assert.equal(approveBlock(read(), {}, { 0: { invoice: 'NWF-88213', total: '1940' } }), undefined);
});

test('an answered read with an empty required field is the model’s answer and holds nothing', () => {
  assert.equal(approveBlock(read({ notRead: null }), {}, {}), undefined);
});

test('a third port waits only on a task that can only be rejected, never on key fields it does not require', () => {
  const keyed = read({ notRead: null, schema: [{ key: 'invoice', label: 'Invoice number', type: 'text', required: true, keyField: true }] });
  const ports = [{ port: 'approve' }, { port: 'return' }, { port: 'reject' }];
  assert.deepEqual(portHolds(keyed, {}, {}, ports), { approve: 'confirm 1 key field first', return: undefined });
  const refused = read({ editable: false, approveRefused: { code: 'not_editable', message: 'x' } });
  assert.deepEqual(portHolds(refused, {}, {}, ports), { approve: 'only Reject is possible', return: 'only Reject is possible' });
});
