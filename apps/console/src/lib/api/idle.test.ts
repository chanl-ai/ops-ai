// The chat stream's idle guard, by failure mode: a stream that goes quiet without closing leaves "Thinking" up
// forever (UX knowledge-5); a stream that keeps sending is cut off by the guard.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { IdleTimeout, withIdleTimeout } from './idle.ts';

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function* events(gaps: number[], hangAfter = false): AsyncIterable<number> {
  for (const [i, gap] of gaps.entries()) {
    await sleep(gap);
    yield i;
  }
  if (hangAfter) await new Promise(() => undefined);
}

test('a stream that goes quiet past the limit ends with IdleTimeout', async () => {
  const seen: number[] = [];
  await assert.rejects(async () => {
    for await (const ev of withIdleTimeout(events([5, 5], true), 50)) seen.push(ev);
  }, IdleTimeout);
  assert.deepEqual(seen, [0, 1]);
});

test('a stream that keeps sending within the limit is not cut off', async () => {
  const seen: number[] = [];
  for await (const ev of withIdleTimeout(events([20, 20, 20, 20]), 50)) seen.push(ev);
  assert.deepEqual(seen, [0, 1, 2, 3]);
});
