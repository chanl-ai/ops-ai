// One test per way a page could be reported wrongly: a step that failed shown as passed or at the wrong line, a later
// step run on a broken state, an open gap ignored, or a use case without a page losing its script.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { cliProgram, parsePage, pythonProgram, stepVerdicts, typescriptProgram } from './page.ts';
import { parseRegistry } from './registry.ts';
import { resolveScript } from './resolve.ts';

const fence = '```';
const PAGE = `# Push knowledge

| Use case | |
|---|---|
| Id | \`uc-900\` |

## Who is in it

| Person | Role | Signs in as |
|---|---|---|
| The owner | Builder | the \`builder\` profile |

## Before you start

${fence}python tab="Python" tab-group="language"
total = 1
${fence}

${fence}ts tab="TypeScript"
import assert from 'node:assert/strict';
let total = 1;
${fence}

${fence}bash tab="CLI"
TOTAL=1
${fence}

## Steps

### 1. Adds one

${fence}python tab="Python" tab-group="language"
total += 1
assert total == 2
${fence}

${fence}ts tab="TypeScript"
total += 1;
assert.equal(total, 2);
${fence}

${fence}bash tab="CLI"
TOTAL=$((TOTAL + 1))
test "$TOTAL" = 2
${fence}

### 2. Expects the wrong total

${fence}python tab="Python" tab-group="language"
total += 1
assert total == 99
${fence}

${fence}ts tab="TypeScript"
total += 1;
assert.equal(total, 99);
${fence}

${fence}bash tab="CLI"
TOTAL=$((TOTAL + 1))
test "$TOTAL" = 99
${fence}

### 3. Never reached

${fence}python tab="Python" tab-group="language"
print("PASS reached step 3")
${fence}

${fence}ts tab="TypeScript"
console.log('PASS reached step 3');
${fence}

${fence}bash tab="CLI"
echo "PASS reached step 3"
${fence}

## Gaps

| Product fix | Step | Tab | What is missing | Where |
|---|---|---|---|---|
| Push verbs | 2 | CLI | \`opsai kb push\` | kb.py:1 |
`;

const P = 'docs/usecases/knowledge/push.md';
const page = parsePage(PAGE, P);
const line = (text: string) => PAGE.split('\n').indexOf(text) + 1;

function run(argv: string[]): { code: number | null; out: string } {
  const r = spawnSync(argv[0]!, argv.slice(1), { encoding: 'utf8' });
  return { code: r.status, out: `${r.stdout}${r.stderr}` };
}

function program(name: string, text: string): string {
  const dir = mkdtempSync(join(tmpdir(), 'ucr-page-'));
  writeFileSync(join(dir, name), text);
  return join(dir, name);
}

test('a page parses into its setup, numbered steps with page lines, profiles and open gaps', () => {
  assert.deepEqual(page.steps.map((s) => [s.n, s.line, s.blocks.map((b) => b.tab)]), [
    [1, line('### 1. Adds one'), ['Python', 'TypeScript', 'CLI']],
    [2, line('### 2. Expects the wrong total'), ['Python', 'TypeScript', 'CLI']],
    [3, line('### 3. Never reached'), ['Python', 'TypeScript', 'CLI']],
  ]);
  assert.deepEqual(page.setup.map((b) => b.tab), ['Python', 'TypeScript', 'CLI']);
  assert.deepEqual(page.profiles, ['builder']);
  assert.equal(page.gaps.length, 1);
});

// Each tab's program: step 1 passes, step 2 fails at its assert's page line, step 3 never runs.
for (const [tab, make] of [
  ['Python', () => ['python3', program('program.py', pythonProgram(page, '/nowhere'))]],
  ['TypeScript', () => [process.execPath, program('program.mts', typescriptProgram(page, '/nowhere/index.js'))]],
  ['CLI', () => ['bash', program('program.sh', cliProgram(page))]],
] as const) {
  test(`${tab}: a failing step names its page line and later steps do not run`, () => {
    const { code, out } = run([...make()]);
    const wrong = { Python: 'assert total == 99', TypeScript: 'assert.equal(total, 99);', CLI: 'test "$TOTAL" = 99' }[tab];
    assert.notEqual(code, 0);
    assert.match(out, new RegExp(`^PASS ${tab} step 1: Adds one \\(${P}:${line('### 1. Adds one')}\\)$`, 'm'));
    assert.match(out, new RegExp(`^FAIL ${tab} step 2: Expects the wrong total .* at ${P}:${line(wrong)}$`, 'm'));
    assert.doesNotMatch(out, /reached step 3/);
  });
}

test('a program that exits without a FAIL line still fails its first unpassed step', () => {
  const extra = stepVerdicts(page, 'CLI', 1, `PASS CLI step 1: Adds one (${P}:${line('### 1. Adds one')})\nboom`);
  assert.deepEqual(extra, [`FAIL CLI step 2: Expects the wrong total (${P}:${line('### 2. Expects the wrong total')}): exited 1: PASS CLI step 1: Adds one (${P}:${line('### 1. Adds one')}) / boom`]);
});

test('a use case with a page runs the page for sdk and cli; one without keeps its script', () => {
  const root = mkdtempSync(join(tmpdir(), 'ucr-'));
  mkdirSync(join(root, 'docs/usecases/knowledge'), { recursive: true });
  mkdirSync(join(root, 'docs/usecases/kb-service/scripts'), { recursive: true });
  mkdirSync(join(root, 'sdk/python'), { recursive: true });
  writeFileSync(join(root, P), PAGE);
  for (const id of ['uc-900', 'uc-901']) writeFileSync(join(root, `docs/usecases/kb-service/scripts/test-${id}-sdk.py`), '');
  const [paged, scripted] = parseRegistry(`| Id | Service | Title | Layers | Status |\n|---|---|---|---|---|\n| uc-900 | kb-service | Push | sdk | passing |\n| uc-901 | kb-service | Other | sdk | passing |\n`);
  assert.deepEqual(resolveScript(root, paged!, 'sdk'), { kind: 'page', path: P });
  assert.equal(resolveScript(root, scripted!, 'sdk').kind, 'script');
});
