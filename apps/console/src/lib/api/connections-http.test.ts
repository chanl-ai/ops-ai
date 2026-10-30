// Each connections call reaches a route tools-service serves: a wrong path or method answers 404 or 405 only once a
// page calls it, so every call is matched against tools-service's own openapi.json (the file its tests check).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { createConnectionsHttp } from './connections-http.ts';

const spec = JSON.parse(readFileSync(new URL('../../../../../services/tools-service/openapi.json', import.meta.url), 'utf8')) as { paths: Record<string, Record<string, unknown>> };
const served = Object.entries(spec.paths).flatMap(([path, ops]) =>
  Object.keys(ops).map((method) => ({ method: method.toUpperCase(), path: new RegExp(`^${path.replace(/\{[^}]+\}/g, '[^/?]+')}(\\?.*)?$`) })),
);

test('every connections call is a route tools-service serves', async () => {
  const calls: { method: string; path: string }[] = [];
  const get = async <T>(path: string) => (calls.push({ method: 'GET', path: `/v1${path}` }), { kinds: [] } as T);
  const send = async <T>(method: string, path: string) => (calls.push({ method, path: `/v1${path}` }), undefined as T);
  const c = createConnectionsHttp(get, send);
  await Promise.all([
    c.get('conn_1'),
    c.kinds(),
    c.setSignIn('conn_1', { revision: 1, signIn: 'person' }),
    c.test('conn_1', { environment: 'test' }),
    c.startSignIn('conn_1', { environment: 'test' }),
    c.completeSignIn('conn_1', { code: 'c', state: 's' }),
    c.openConnectLink('l'),
    c.mine(),
    c.disconnect('conn_1', 'test'),
  ]);
  const missing = calls.filter((call) => !served.some((s) => s.method === call.method && s.path.test(call.path)));
  assert.equal(calls.length, 9);
  assert.deepEqual(missing, []);
});
