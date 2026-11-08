import assert from 'node:assert/strict';
import { test } from 'node:test';

import { wasNotRun } from './tool-calls.ts';

// A call the reply's limits stopped before it ran did nothing; listing it as an error reads as a broken system.
test('a call stopped by the reply limit reads as not run; a real failure does not', () => {
  assert.equal(wasNotRun({ status: 'failed', output: { error: 'Not run: the reply reached the most tool calls this agent may make.' } }), true);
  assert.equal(wasNotRun({ status: 'failed', output: { error: 'Salesforce refused the query: unexpected token.' } }), false);
  assert.equal(wasNotRun({ status: 'success', output: { rows: [] } }), false);
});
