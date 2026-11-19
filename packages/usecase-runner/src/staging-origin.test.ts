// The walks that sign in to a deployed console and write to it (STG_ORIGIN), by failure mode: any origin was accepted,
// another app of the same shape as staging was reachable, and an unset staging host did not stop a run. A refused walk
// exits before it launches a browser, so each case runs the real script and reads its exit code.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '../../..');
const WALKS = ['stg_functional_walk.mjs', 'stg_click_walk.mjs', 'stg_pages_walk.mjs'];
const BASE = { PATH: process.env.PATH ?? '', STG_EMAIL: 'a@example.com', STG_PASSWORD: 'x' };

function walk(script: string, origin: string | undefined, staging: string | undefined) {
  const env: Record<string, string> = { ...BASE };
  if (origin) env.STG_ORIGIN = origin;
  if (staging) env.OPS_USECASE_STAGING_HOST = staging;
  const done = spawnSync(process.execPath, [join(ROOT, 'docs/usecases/lib', script)], { cwd: ROOT, env, encoding: 'utf8', timeout: 30_000 });
  return { code: done.status, err: done.stderr };
}

for (const script of WALKS) {
  test(`${script} refuses an unset origin, an unset staging host, another host and a production name`, () => {
    for (const [origin, staging] of [
      [undefined, 'acme-web.fly.dev'],
      ['https://acme-web.fly.dev', undefined],
      ['https://other-web.fly.dev', 'acme-web.fly.dev'],
      ['https://other-web.fly.dev', '*-web.fly.dev'],
      ['https://acme-prod-web.fly.dev', 'acme-prod-web.fly.dev'],
      ['http://acme-web.fly.dev', 'acme-web.fly.dev'],
    ] as const) {
      const got = walk(script, origin, staging);
      assert.equal(got.code, 2, `${origin} with ${staging}: ${got.err}`);
      assert.match(got.err, /refused by the staging-host guard/);
    }
  });
}
