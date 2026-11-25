import assert from 'node:assert/strict';
import { test } from 'node:test';

import { QueryClient, QueryObserver } from '@tanstack/react-query';

import { watchServicesDown } from './services-down.ts';

const tick = () => new Promise<void>((r) => setTimeout(r, 0));

// The cache tells its subscribers synchronously when a query is added, and a page adds queries while it renders.
// A subscriber that updates the banner in that call updates one component while another renders, which React
// reports ("Cannot update a component ... while rendering ...") and which can loop.
test('the banner is told nothing while a page renders, and once when the services really go down or come back', async () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const cache = qc.getQueryCache();
  const seen: boolean[] = [];
  const stop = watchServicesDown(cache, (d) => seen.push(d));

  // A page renders: it adds three queries, none of them failed.
  for (const k of ['a', 'b', 'c']) cache.build(qc, { queryKey: [k] });
  assert.deepEqual(seen, [], 'nothing is pushed to the banner inside the render');
  await tick();
  assert.deepEqual(seen, [], 'adding queries does not change the answer, so nothing is pushed afterwards either');

  // A read on screen fails with no answer from the services.
  const obs = new QueryObserver(qc, { queryKey: ['down'], retry: false, queryFn: () => Promise.reject(Object.assign(new Error('fetch failed'), { status: undefined })) });
  const unsub = obs.subscribe(() => {});
  await tick();
  await tick();
  assert.deepEqual(seen, [true], 'one push when it goes down');

  unsub();
  await tick();
  assert.deepEqual(seen, [true, false], 'one push when nothing on screen shows the failed read any more');
  stop();
});
