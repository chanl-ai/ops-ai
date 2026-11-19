import assert from 'node:assert/strict';
import { test } from 'node:test';

import { safeHref } from './safe-href.ts';

test('a script or data address is never kept as a link', () => {
  for (const bad of ['javascript:void(0)', ' JavaScript:void(0)', 'data:text/html,x', '//evil.example/x', 'vbscript:x']) {
    assert.equal(safeHref(bad), undefined, bad);
  }
  assert.equal(safeHref('/data/files?file=f1'), '/data/files?file=f1');
  assert.equal(safeHref('https://bank.example/a'), 'https://bank.example/a');
  assert.equal(safeHref('mailto:a@bank.example'), 'mailto:a@bank.example');
});

test('a framed preview loads web addresses only', () => {
  assert.equal(safeHref('mailto:a@bank.example', { web: true }), undefined);
  assert.equal(safeHref('/data/files', { web: true }), undefined);
  assert.equal(safeHref('https://bank.example', { web: true }), 'https://bank.example');
});
