import assert from 'node:assert/strict';
import { test } from 'node:test';

import { fieldGuide, isEmptyInput, sampleFromSchema } from './run-input-schema.ts';

const schema = {
  type: 'object',
  required: ['customerEmail'],
  properties: {
    customerEmail: { type: 'string', format: 'email', title: 'Customer email', examples: ['ada@example.test'] },
    channel: { type: 'string', title: 'Channel', examples: ['Card'] },
    amount: { type: 'number', title: 'Amount', default: 25 },
    cardType: { type: 'string', title: 'Card type', oneOf: [{ const: 'debit', title: 'Debit card' }, { const: 'credit', title: 'Credit card' }] },
  },
};

test('sample uses examples, then default, then a choice', () => {
  assert.deepEqual(sampleFromSchema(schema), {
    customerEmail: 'ada@example.test',
    channel: 'Card',
    amount: 25,
    cardType: 'debit',
  });
});

test('field guide names type and example for the JSON tab', () => {
  const guide = fieldGuide(schema);
  assert.deepEqual(guide[0], { key: 'customerEmail', label: 'Customer email', type: 'email', example: 'ada@example.test' });
  assert.equal(guide[1].type, 'string');
  assert.equal(guide[2].example, '25');
  assert.equal(guide[3].type, 'choice');
  assert.equal(guide[3].example, 'debit');
});

test('empty input is {} or blanks', () => {
  assert.equal(isEmptyInput({}), true);
  assert.equal(isEmptyInput({ customerEmail: '' }), true);
  assert.equal(isEmptyInput({ customerEmail: 'ada@example.test' }), false);
});
