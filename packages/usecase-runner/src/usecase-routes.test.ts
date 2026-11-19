// Two ways the add and update routes could mislead a person: a new console test slipping in or a short title that never
// reaches the list, and a reworded step reported as unchanged.
import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { parseRegistry } from './registry.ts';
import { scaffold } from './scaffold.ts';
import { parseSteps } from './stories.ts';
import { changedSteps } from './update.ts';
import { buildIndex } from './usecase-index.ts';

const TABLE = `| Id | Service | Title | Layers | Status |
|---|---|---|---|---|
| uc-001 | agents-service | Chat turn | api | passing |
`;

function repo(): string {
  const root = mkdtempSync(join(tmpdir(), 'uc-routes-'));
  mkdirSync(join(root, 'services/agents-service'), { recursive: true });
  mkdirSync(join(root, 'docs/usecases/agents-service'), { recursive: true });
  writeFileSync(join(root, 'docs/usecases/README.md'), TABLE);
  writeFileSync(join(root, 'docs/README.md'), '| `usecases/README.md` | registry |\n');
  return root;
}

test('add refuses a console layer, and a short title written by add reaches the index', () => {
  const root = repo();
  assert.throws(() => scaffold(root, parseRegistry(TABLE), 'agents-service', 'X', ['ui']), /no new console tests/);
  const made = scaffold(root, parseRegistry(TABLE), 'agents-service', 'Chat with an agent', ['api']);
  const rows = buildIndex(root, parseRegistry(readFileSync(join(root, 'docs/usecases/README.md'), 'utf8')));
  const row = rows.find((r) => r.id === made.id)!;
  assert.deepEqual([row.title, row.layers], ['Chat with an agent', ['api']]);
});

test('update names a reworded, a new and a removed step', () => {
  const doc = (rows: string) => parseSteps(`## Steps\n\n| # | Step | Expected |\n|---|---|---|\n${rows}\n`);
  const before = doc('| 1 | Open the page | It loads |\n| 2 | Click save | Saved |\n| 3 | Sign out | Gone |');
  const after = doc('| 1 | Open the page | It loads |\n| 2 | Click publish | Saved |\n| 4 | Check mail | Sent |');
  assert.deepEqual(changedSteps(before, after), ['step 2 changed: Click publish', 'step 4 is new: Check mail', 'step 3 was removed: Sign out']);
});
