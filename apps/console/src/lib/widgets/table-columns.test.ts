import assert from 'node:assert/strict';
import { test } from 'node:test';

import { columnLabel, dateCell, isEmptyColumn, isIsoDate, readingOrder, shownLabel } from './table-columns.ts';

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

test('raw keys read as words, whatever their case', () => {
  assert.deepEqual(['subject', 'knowledgeBase', 'due_date', 'CaseNumber', 'accountId', 'SLA'].map(columnLabel), ['Subject', 'Knowledge base', 'Due date', 'Case number', 'Account ID', 'SLA']);
  assert.equal(shownLabel('due', 'Due by'), 'Due by');
  assert.equal(shownLabel('due', 'due'), 'Due');
});

test('a column with nothing in any row is dropped; one with a value in a row stays', () => {
  const rows = [{ page: '—', subject: 'Card declined', note: null }, { page: null, subject: 'Late fee', note: 'asked twice' }];
  assert.deepEqual(['page', 'subject', 'note'].filter((k) => !isEmptyColumn(k, rows)), ['subject', 'note']);
});

test('API dates read as dates, and other text is left alone', () => {
  assert.equal(dateCell('2026-10-01'), new Date('2026-10-01T12:00:00').toLocaleDateString('en-CA', { day: 'numeric', month: 'short', year: 'numeric' }));
  assert.ok(isIsoDate('2026-11-07T04:51:38.116341Z') && isIsoDate('2026-10-01') && !isIsoDate('00044818') && !isIsoDate('Oct 1'));
});
