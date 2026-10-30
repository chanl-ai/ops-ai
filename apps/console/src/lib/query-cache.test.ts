import assert from 'node:assert/strict';
import { test } from 'node:test';

import { QueryClient } from '@tanstack/react-query';

import { persistQueryClientSave, type PersistedClient, type Persister } from '@tanstack/react-query-persist-client';

import { cacheBuster, cacheOn, openSavedQueries, restoreSaved, shouldSave } from './query-cache.ts';

const T = { team: 'team_ops' };
const done = (queryKey: unknown[], data: unknown = { ok: true }) => ({ queryKey, state: { status: 'success', data } });

test('NEXT_PUBLIC_OPS_CACHE=off gives no saved cache at all; unset or anything else keeps it on', () => {
  const client = new QueryClient();
  const open = (setting: string | undefined) => openSavedQueries({ client, user: 'u_james', team: 'team_ops', buster: 'v1', setting });
  assert.equal(open('off'), null);
  assert.equal(open(' OFF '), null);
  assert.equal(cacheOn('off'), false);
  assert.notEqual(open(undefined), null);
  assert.notEqual(open('on'), null);
  assert.equal(openSavedQueries({ client, user: null, team: 'team_ops', buster: 'v1', setting: undefined }), null);
});

test("only the current team's screen reads are saved", () => {
  assert.equal(shouldSave(done(['workflows', { page: 1 }, T]), 'team_ops'), true);
  assert.equal(shouldSave(done(['workflows', { page: 1 }, T]), 'team_risk'), false);
  assert.equal(shouldSave(done(['workflows', { page: 1 }]), 'team_ops'), false);
  assert.equal(shouldSave({ queryKey: ['workflows', T], state: { status: 'error', data: undefined } }, 'team_ops'), false);
});

test('session reads, Human Tasks, file preview links and unfinished runs are never saved', () => {
  for (const key of [['me', T], ['me', 'permissions', T], ['teams', T], ['sign-in-policy', T], ['reviews', 'one', 'r1', T], ['files', 'preview-link', 'f1', T]]) {
    assert.equal(shouldSave(done(key), 'team_ops'), false, JSON.stringify(key));
  }
  assert.equal(shouldSave(done(['engine', 'run', 'r1', T], { status: 'running' }), 'team_ops'), false);
  assert.equal(shouldSave(done(['cases', 'run-state', 'r1', T], {}), 'team_ops'), false);
  assert.equal(shouldSave(done(['eval-run', 'e1', T], { status: 'running' }), 'team_ops'), false);
  assert.equal(shouldSave(done(['engine', 'run', 'r1', T], { status: 'succeeded' }), 'team_ops'), true);
  assert.equal(shouldSave(done(['engine', 'runs', {}, T]), 'team_ops'), true);
});

test('a build with no version still has a buster', () => {
  assert.equal(cacheBuster('v2026-10-29.1', 'abc'), 'v2026-10-29.1');
  assert.equal(cacheBuster(undefined, undefined), 'unversioned');
});

test('a read a write marked out of date is not saved', () => {
  const q = { queryKey: ['agents', { page: 1 }, T], state: { status: 'success', data: { ok: true }, isInvalidated: true } };
  assert.equal(shouldSave(q, 'team_ops'), false);
  assert.equal(shouldSave({ ...q, state: { ...q.state, isInvalidated: false } }, 'team_ops'), true);
});

test('a copy saved a moment ago is shown after a reload but fetched again, never kept as fresh', async () => {
  let saved: PersistedClient | undefined;
  const persister: Persister = { persistClient: async (c) => void (saved = c), restoreClient: async () => saved, removeClient: async () => void (saved = undefined) };
  const before = new QueryClient();
  before.setQueryData(['agents', T], { answer: 'old' });
  await persistQueryClientSave({ queryClient: before, persister, buster: 'v1' });
  const reloaded = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000 } } });
  await restoreSaved(reloaded, persister, 'v1');
  const state = reloaded.getQueryState(['agents', T]);
  assert.deepEqual(state?.data, { answer: 'old' });
  assert.equal(state?.isInvalidated, true);
});
