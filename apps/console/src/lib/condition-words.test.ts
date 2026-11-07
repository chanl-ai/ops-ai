import assert from 'node:assert/strict';
import { test } from 'node:test';

import { conditionInWords } from './condition-words.ts';

test('a gate rule reads as words, numbers and quantities kept', () => {
  assert.equal(conditionInWords('amount > 50,000 AND payee.age < 72h'), 'amount is over 50,000 and payee age is under 72h');
  assert.equal(conditionInWords('agent.confidence < 0.75'), 'agent confidence is under 0.75');
  assert.equal(conditionInWords('payee.country IN high_risk_list'), 'payee country is in high risk list');
  assert.equal(conditionInWords('screening.pep OR nameMatch < 0.90'), 'screening pep or name match is under 0.90');
  assert.equal(conditionInWords('requestsOverride'), 'requests override');
});
