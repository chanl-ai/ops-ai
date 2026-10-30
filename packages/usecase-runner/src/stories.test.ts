// One test per way the stories report could tell a person a story works when it does not, or hide what broke.
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { report } from './cli.ts';
import type { UseCase } from './registry.ts';
import { docTemplate } from './scaffold.ts';
import { formatStories, judge, parseStories, saveRun, StoryError } from './stories.ts';

const DOC = `# Approve a hold

Status: current. Id: \`uc-900\`. Service: \`agents-service\`. Layers: api, ui.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | Maya opens Human Tasks and sees the hold waiting | ui | 1-2 | 2 |
| S2 | Maya approves the hold and the run finishes | ui | 3-4 | 4 |
| S3 | A builder places the hold through the API | api | 1 | 1 |

## Steps and expected results
`;

const UC: UseCase = { id: 'uc-900', service: 'agents-service', title: 'Approve a hold', layers: ['api', 'ui'], status: 'passing' };
const ui = parseStories(DOC).filter((s) => s.layer === 'ui');

test('stories parse with their layer, steps and proving step', () => {
  const s = parseStories(DOC);
  assert.deepEqual(s.map((x) => [x.id, x.layer, x.steps, x.proof]), [['S1', 'ui', [1, 2], 2], ['S2', 'ui', [3, 4], 4], ['S3', 'api', [1], 1]]);
});

test('a story whose proving step never ran is broken, not working', () => {
  // The script stopped after step 2: S2 has no failed check, and still must not read as working.
  const r = judge(ui, { passed: ['1 the queue opens', '2 the hold is listed'], failed: [] });
  assert.deepEqual(r.map((x) => [x.story.id, x.state]), [['S1', 'works'], ['S2', 'broken']]);
  assert.equal(r[1]!.why, 'the script stopped before step 4');
});

test('a failed check breaks only its own story and names the step', () => {
  const r = judge(ui, { passed: ['1 the queue opens', '2 the hold is listed', '4 the run finished'], failed: ['3 approve: 422 step-up required'] });
  assert.deepEqual(r.map((x) => [x.story.id, x.state]), [['S1', 'works'], ['S2', 'broken']]);
  assert.equal(r[1]!.why, 'step 3 failed: 3 approve: 422 step-up required');
});

test('a failed check outside every story is still shown', () => {
  const run = { id: 'uc-900', layer: 'ui' as const, at: 'now', exit: 1, checks: { passed: ['1 a', '2 b', '3 c', '4 d'], failed: ['no page errors'] } };
  const text = formatStories(UC, ui, { ui: run });
  assert.match(text, /works +S2/);
  assert.match(text, /also failed \(ui\): no page errors/);
  assert.match(text, /4 of 5 passed, script exited 1/);
});

test('a malformed Stories table is refused rather than read as no stories', () => {
  const bad = (row: string) => () => parseStories(DOC.replace(/\| S3 .*\n/, `${row}\n`), 'uc-900');
  assert.throws(bad('| S3 | A builder | web | 1 | 1 |'), StoryError);
  assert.throws(bad('| S3 | A builder | api | 1-2 | 5 |'), /proved by must be one of its steps/);
  assert.throws(bad('| 3 | A builder | api | 1 | 1 |'), /look like S1/);
});

test('the new-use-case template is a valid Stories table', () => {
  assert.equal(parseStories(docTemplate('uc-901', 'agents-service', 'X')).length, 1);
});

test('report reads the saved run, finds the doc by its Id line, and says when a layer has not run', () => {
  const root = mkdtempSync(join(tmpdir(), 'ucs-'));
  mkdirSync(join(root, 'docs/usecases/agents-service'), { recursive: true });
  writeFileSync(join(root, 'docs/usecases/agents-service/some-other-name.md'), DOC);
  saveRun(root, { id: 'uc-900', layer: 'ui', at: 'now', exit: 0, checks: { passed: ['1 a', '2 b', '3 c', '4 d'], failed: [] } });
  const text = report(root, [UC]);
  assert.match(text, /works +S1 +ui/);
  assert.match(text, /works +S2 +ui/);
  assert.match(text, /not run +S3 +api/);
});
