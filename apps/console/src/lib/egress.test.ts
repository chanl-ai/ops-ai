import assert from 'node:assert/strict';
import { test } from 'node:test';

import { hostOf } from './egress.ts';

test('the host a request goes to is read from an absolute URL, and a partial or parameter host gives none', () => {
  assert.equal(hostOf('https://Deposits.API.example.internal/v1/accounts/{accountId}'), 'deposits.api.example.internal');
  assert.equal(hostOf('https://api.bank.example:8443/x'), 'api.bank.example');
  assert.equal(hostOf('https://api.bank.example'), 'api.bank.example');
  assert.equal(hostOf('https://{host}/v1'), null);
  assert.equal(hostOf('/v1/accounts'), null);
  assert.equal(hostOf('https://api.ba'), 'api.ba');
  assert.equal(hostOf(''), null);
});
