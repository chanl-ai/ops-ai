// `new <service> "<title>"`: the next id, a doc from the template, a registry row, and an api script that fails until
// it is written, so a new use case cannot pass before it tests anything.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import type { UseCase } from './registry.ts';
import { USECASE_DIR } from './resolve.ts';

export function nextId(registry: UseCase[]): string {
  const max = registry.reduce((m, u) => (/^uc-\d{3}$/.test(u.id) ? Math.max(m, Number(u.id.slice(3))) : m), 0);
  return `uc-${String(max + 1).padStart(3, '0')}`;
}

export function slug(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .split('-')
    .slice(0, 6)
    .join('-');
}

/** Layers `add` writes a stub for. The console has no new use case scripts for now, so ui is not offered. */
export const ADDABLE_LAYERS = ['api', 'sdk', 'cli'] as const;

export function docTemplate(id: string, service: string, title: string, layers: readonly string[] = ['api']): string {
  const stories = layers.map((l, i) => `| S${i + 1} | A <person> <does something> and <sees the result> | ${l} | 1 | 1 |`).join('\n');
  const scripts = layers.map((l) => `| ${l} | \`${service}/scripts/test-${id}-${l}.py\` | not written |`).join('\n');
  return `# ${title}

Status: draft. Id: \`${id}\`. Service: \`${service}\`. Layers: ${layers.join(', ')}.

Short title: ${title}

## Story

As a <person>, I want to <task> so that <result>.

## People

| Person | Role | Does what |
|---|---|---|
| <name> | <builder, member or admin> | <what they do here> |

## In this example

In this example we will <do X>. It assumes <Y> and <Z>.

## Stories

Four or five things a person does and sees work, in plain words, each on one layer. Its steps are rows of the steps
table below, and "Proved by" is the one step whose check shows the story works. A script names each check by its step
("2 the hold is placed"), so a run reports each story as works or broken, with the step that failed.

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
${stories}

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | \`make db-up\` |

## Steps and expected results

Each step is something a person does through the public SDK, the CLI or the console. A step the product cannot do yet
stays in the table as **Open**, and a card is filed for it; the script never reaches around the product with a helper.

| # | Step | Expected |
|---|---|---|
| 1 | | |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
${scripts}

## Non-vacuous check

Name the check that fails if the behaviour is broken, and how it was seen failing once.
`;
}

const HEAD = (id: string, layer: string) => `"""${id}, ${layer} layer. Replace this body with the steps from the use case doc. Name each check by its step, such as
"1 the list opens". Steps go through the public ${layer === 'sdk' ? 'SDK' : layer === 'cli' ? 'CLI' : 'HTTP routes'} only; a step that cannot is an Open step in the doc, never a helper here."""

from __future__ import annotations
`;

const STUBS: Record<string, (id: string) => string> = {
  api: (id) => `${HEAD(id, 'api')}
from usecase_harness import check, finish

check("1 script written", False, "${id} has no steps yet")
finish()
`,
  sdk: (id) => `${HEAD(id, 'sdk')}
import sys
from pathlib import Path

from usecase_harness import check, finish

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "sdk" / "python" / "src"))
from ops_ai import OpsAI  # noqa: E402,F401  (see test-uc-092-sdk.py for connecting to this run's services)

check("1 script written", False, "${id} has no steps yet")
finish()
`,
  cli: (id) => `${HEAD(id, 'cli')}
import subprocess  # noqa: F401  (run the command a person types, as test-uc-568-cli.py does)

from usecase_harness import check, finish

check("1 script written", False, "${id} has no steps yet")
finish()
`,
};

export function scaffold(root: string, registry: UseCase[], service: string, title: string, layers: readonly string[] = ['api']): { id: string; files: string[] } {
  const bad = layers.filter((l) => !(ADDABLE_LAYERS as readonly string[]).includes(l));
  if (bad.length || !layers.length) throw new Error(`layers for a new use case are some of ${ADDABLE_LAYERS.join(', ')}; got "${layers.join(',')}" (no new console tests for now)`);
  if (!existsSync(join(root, 'services', service))) throw new Error(`no services/${service}; a use case belongs to a service folder`);
  const id = nextId(registry);
  const doc = join(USECASE_DIR, service, `${slug(title)}.md`);
  if (existsSync(join(root, doc))) throw new Error(`${doc} already exists; pick a title naming a different topic`);
  const scripts = layers.map((l) => [join(USECASE_DIR, service, 'scripts', `test-${id}-${l}.py`), STUBS[l]!(id)] as const);
  for (const [path, body] of [[doc, docTemplate(id, service, title, layers)] as const, ...scripts]) {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), body);
  }
  const readme = join(root, USECASE_DIR, 'README.md');
  const lines = readFileSync(readme, 'utf8').split('\n');
  const last = lines.findLastIndex((l) => /^\| `?uc-(\d{3}|[a-z]+-\d+)/.test(l));
  lines.splice(last + 1, 0, `| ${id} | ${service} | ${title} | ${layers.join(', ')} | draft |`);
  writeFileSync(readme, lines.join('\n'));
  const index = join(root, 'docs/README.md');
  const idx = readFileSync(index, 'utf8').split('\n');
  const at = idx.findLastIndex((l) => l.includes('`usecases/'));
  const rel = doc.slice('docs/'.length);
  if (at >= 0) {
    idx.splice(at + 1, 0, `| \`${rel}\` | ${id}: ${title} |`);
    writeFileSync(index, idx.join('\n'));
  }
  return { id, files: [doc, ...scripts.map(([p]) => p), `${USECASE_DIR}/README.md`, ...(at >= 0 ? ['docs/README.md'] : [])] };
}
