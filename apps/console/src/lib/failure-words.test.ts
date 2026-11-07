import assert from 'node:assert/strict';
import { test } from 'node:test';

import { actsAs, failureWords } from './failure-words.ts';

test('a failed call reads in words by its code, else its own message, never the bare code', () => {
  assert.equal(failureWords('CONNECTION_NOT_LINKED'), 'Waited for the person’s own sign-in');
  assert.equal(failureWords('SOMETHING_NEW', 'crm.bank.test answered 502'), 'crm.bank.test answered 502');
  assert.equal(failureWords('SOMETHING_NEW'), 'The call failed');
});

test('a sign-in request says whether the tool reads or changes something as the person', () => {
  assert.equal(actsAs({ app: 'Salesforce', access: 'read' }), 'This tool reads Salesforce as you');
  assert.equal(actsAs({ app: 'Salesforce', access: 'write' }), 'This tool makes the change in Salesforce in your name');
});
