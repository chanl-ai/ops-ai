import assert from 'node:assert/strict';
import { test } from 'node:test';

import { servicesDown } from './unreachable.ts';

const read = (over: Record<string, unknown> = {}) => ({ observers: 1, status: 'success', error: null, failures: 0, failureReason: null, side: false, ...over });
const down = { status: 503 };

test('the page-wide banner shows for a page read the services did not answer, never for a side read', () => {
  assert.equal(servicesDown([read(), read({ status: 'error', error: down })]), true);
  // The model list behind the New agent dialog failing leaves a working Agents list without a banner.
  assert.equal(servicesDown([read(), read({ status: 'error', error: down, side: true })]), false);
  assert.equal(servicesDown([read({ failures: 1, failureReason: down, side: true })]), false);
  // A read nobody shows, or an answer such as 404, is no outage.
  assert.equal(servicesDown([read({ observers: 0, status: 'error', error: down }), read({ status: 'error', error: { status: 404 } })]), false);
});
