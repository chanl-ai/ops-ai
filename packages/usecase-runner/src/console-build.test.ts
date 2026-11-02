import assert from 'node:assert/strict';
import { existsSync, mkdirSync, mkdtempSync, rmSync, utimesSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { pruneOld } from './console-build.ts';

const DAY = 86_400_000;

function cache(ages: Record<string, number>, now: number): string {
  const dir = mkdtempSync(join(tmpdir(), 'build-cache-'));
  for (const [key, age] of Object.entries(ages)) {
    const build = join(dir, `console-build-${key}`);
    mkdirSync(build);
    writeFileSync(join(dir, `tsconfig-build-${key}.json`), '{}');
    const when = new Date(now - age);
    utimesSync(build, when, when);
  }
  return dir;
}

test('only the newest builds under a day old stay, the current one always, and their tsconfigs go with the rest', () => {
  const now = Date.now();
  const dir = cache({ a: 1000, b: 2000, c: 3000, d: 4000, e: 5000, old: 2 * DAY, current: 3 * DAY }, now);
  const removed = pruneOld(dir, 'node_modules/.cache/console-build-current', now);
  assert.deepEqual(removed.sort(), ['console-build-d', 'console-build-e', 'console-build-old']);
  for (const key of ['a', 'b', 'c', 'current']) assert.ok(existsSync(join(dir, `console-build-${key}`)), key);
  for (const key of ['d', 'e', 'old']) {
    assert.ok(!existsSync(join(dir, `console-build-${key}`)), key);
    assert.ok(!existsSync(join(dir, `tsconfig-build-${key}.json`)), `${key} tsconfig`);
  }
  assert.ok(existsSync(join(dir, 'tsconfig-build-a.json')));
  rmSync(dir, { recursive: true, force: true });
});

test('a build being made (its lock beside it) is never pruned', () => {
  const now = Date.now();
  const dir = cache({ a: 1000 }, now);
  mkdirSync(join(dir, 'console-build-busy.lock'));
  assert.deepEqual(pruneOld(dir, 'x', now), []);
  rmSync(dir, { recursive: true, force: true });
});
