import assert from 'node:assert/strict';
import { test } from 'node:test';

import { readingOrder } from './table-columns.ts';

test('a record table reads by its name first and keeps its ids behind the View menu', () => {
  const rows = [{ Id: '5003000000D8cuJAAR', CaseNumber: '00044818', Subject: 'Card declined abroad', AccountId: '001300000000ACMEAA', owner: '005Hp00000AbCdEFGH' }];
  const { order, hidden } = readingOrder(Object.keys(rows[0]), rows);
  assert.deepEqual(order, ['Subject', 'CaseNumber', 'Id', 'AccountId', 'owner']);
  assert.deepEqual(hidden, ['Id', 'AccountId', 'owner']);
});

test('a number like a case number or an amount is never taken for an id', () => {
  const rows = [{ CaseNumber: '00044818', amount: 2140.55, status: 'Open' }];
  assert.deepEqual(readingOrder(Object.keys(rows[0]), rows).hidden, []);
});

test('a table of ids alone keeps them showing', () => {
  const rows = [{ Id: '5003000000D8cuJAAR' }];
  assert.deepEqual(readingOrder(['Id'], rows), { order: ['Id'], hidden: [] });
});
