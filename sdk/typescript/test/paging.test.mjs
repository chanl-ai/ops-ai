// everyPage by failure mode: a list that stops early, ends on the wrong page, breaks on no rows, or asks for a page
// size the API would answer at its maximum.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { PAGE_MAX, everyPage } from '../dist/transport.js';

const pages = (rowsPerPage) => {
  const asked = [];
  const fetchPage = async (query) => {
    asked.push(query);
    const page = Number(query.page ?? 1);
    return { data: rowsPerPage[page - 1] ?? [], pagination: { page, hasNext: page < rowsPerPage.length } };
  };
  return { fetchPage, asked };
};

const rows = [
  { name: 'three pages', rowsPerPage: [['a'], ['b'], ['c']], query: {}, want: ['a', 'b', 'c'], requests: 3 },
  { name: 'last page has no next', rowsPerPage: [['a', 'b'], ['c']], query: {}, want: ['a', 'b', 'c'], requests: 2 },
  { name: 'empty list', rowsPerPage: [[]], query: {}, want: [], requests: 1 },
  { name: 'size above the maximum', rowsPerPage: [['a'], ['b']], query: { pageSize: 200 }, want: ['a', 'b'], requests: 2 },
  { name: 'smaller size and a filter kept', rowsPerPage: [['a'], ['b']], query: { pageSize: 10, search: 'x' }, want: ['a', 'b'], requests: 2 },
];

for (const row of rows) {
  test(`everyPage: ${row.name}`, async () => {
    const { fetchPage, asked } = pages(row.rowsPerPage);
    assert.deepEqual(await everyPage(fetchPage, row.query), row.want);
    assert.equal(asked.length, row.requests);
    assert.ok(asked.every((q) => q.pageSize <= PAGE_MAX));
    assert.equal(asked[0].pageSize, Math.min(row.query.pageSize ?? PAGE_MAX, PAGE_MAX));
    assert.ok(asked.every((q) => q.search === row.query.search));
  });
}
