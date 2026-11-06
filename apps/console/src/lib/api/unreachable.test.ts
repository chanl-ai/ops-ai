import assert from 'node:assert/strict';
import { test } from 'node:test';

import { FAILED_READ_HOLD_MS, isUnreachable, retryRead, retryReadOnMount, servicesDown } from './unreachable.ts';

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

const dependencyDown = { status: 503, code: 'models_unavailable' };

test('a part a service says is down is asked once: no retry, no banner', () => {
  assert.equal(retryRead(0, dependencyDown), false);
  assert.equal(isUnreachable(dependencyDown), false);
  assert.equal(servicesDown([read({ status: 'error', error: dependencyDown })]), false);
  // A service that did not answer at all is still an outage, retried and bannered.
  assert.equal(retryRead(3, down), true);
  assert.equal(retryRead(4, down), false);
  assert.equal(isUnreachable({ status: 502 }), true);
});

test('a read that just failed is shared by the parts that mount after it, and asked again after the hold', () => {
  const now = 1_000_000;
  assert.equal(retryReadOnMount({ status: 'error', errorUpdatedAt: now - 1_000 }, now), false);
  assert.equal(retryReadOnMount({ status: 'error', errorUpdatedAt: now - FAILED_READ_HOLD_MS - 1 }, now), true);
  assert.equal(retryReadOnMount({ status: 'success', errorUpdatedAt: 0 }, now), true);
});
