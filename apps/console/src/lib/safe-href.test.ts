import assert from 'node:assert/strict';
import { test } from 'node:test';

import { consolePath, safeHref } from './safe-href.ts';

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

test('a card field links only to a path in the console', () => {
  assert.equal(consolePath('/cases/c1'), '/cases/c1');
  for (const other of ['https://bank.example/a', '//evil.example/x', '/\\evil.example/x', '/\t/evil.example', 'javascript:void(0)', undefined]) {
    assert.equal(consolePath(other), undefined, String(other));
  }
});
