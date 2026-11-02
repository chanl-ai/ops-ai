// The /dev and /preview test surfaces draw sample data and record actions instead of sending them; a deployed console
// must never serve them. apps/console/src/proxy.ts opens them on OPS_ALLOW_PREVIEW_PAGES, which only the runner sets.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';
import { test } from 'node:test';

const ROOT = join(import.meta.dirname, '../../..');
const ALLOWED = ['packages/usecase-runner/src/harness.ts', 'packages/usecase-runner/src/preview-pages-switch.test.ts', 'apps/console/src/proxy.ts'];

test('only the use-case runner sets the preview pages switch; no deploy config, image or workflow does', () => {
  let found = '';
  try {
    // Untracked files count too, so a deploy file not yet committed is caught before it is.
    found = execFileSync('git', ['grep', '-l', '--untracked', 'OPS_ALLOW_PREVIEW_PAGES'], { cwd: ROOT, encoding: 'utf8' });
  } catch (e) {
    if ((e as { status?: number }).status !== 1) throw e;
  }
  const outside = found.split('\n').filter((f) => f && !ALLOWED.includes(f) && !f.endsWith('.md'));
  assert.deepEqual(outside, [], `files outside the use-case runner name the preview pages switch: ${outside.join(', ')}`);
});
