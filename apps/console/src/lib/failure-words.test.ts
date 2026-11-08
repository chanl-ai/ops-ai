import assert from 'node:assert/strict';
import { test } from 'node:test';

import { actsAs, failureWords } from './failure-words.ts';

test('a failed call reads in words by its code, else its own message, never the bare code', () => {
  assert.equal(failureWords('CONNECTION_NOT_LINKED'), 'Waited for the person’s own sign-in');
  // An app the team has off reads apart from one the install does not have, which only an operator installs.
  assert.equal(failureWords('APP_OFF_FOR_TEAM'), 'The app is turned off for this team');
  assert.equal(failureWords('PLUGIN_DISABLED'), 'The app is not installed here');
  assert.equal(failureWords('SOMETHING_NEW', 'crm.bank.test answered 502'), 'crm.bank.test answered 502');
  assert.equal(failureWords('SOMETHING_NEW'), 'The call failed');
});

test('a sign-in request says whether the tool reads or changes something as the person', () => {
  assert.equal(actsAs({ app: 'Salesforce', access: 'read' }), 'This tool reads Salesforce as you');
  assert.equal(actsAs({ app: 'Salesforce', access: 'write' }), 'This tool makes the change in Salesforce in your name');
});
