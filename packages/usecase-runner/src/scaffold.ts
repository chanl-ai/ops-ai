// `new <service> "<title>"`: the next id, a doc from the template, a registry row, and an api script that fails until
// it is written, so a new use case cannot pass before it tests anything.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import type { UseCase } from './registry.ts';
import { USECASE_DIR } from './resolve.ts';

export function nextId(registry: UseCase[]): string {
  const max = registry.reduce((m, u) => Math.max(m, Number(u.id.slice(3))), 0);
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

export function docTemplate(id: string, service: string, title: string): string {
  return `# ${title}

Status: draft. Id: \`${id}\`. Service: \`${service}\`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | \`make db-up\` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | | |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | \`${service}/scripts/test-${id}-api.py\` | not written |

## Non-vacuous check

Name the check that fails if the behaviour is broken, and how it was seen failing once.
`;
}

const SCRIPT_STUB = (id: string) => `"""${id}, api layer. Replace this body with the steps from the use case doc."""

from __future__ import annotations

from usecase_harness import check, finish

check("script written", False, "${id} has no steps yet")
finish()
`;

export function scaffold(root: string, registry: UseCase[], service: string, title: string): { id: string; files: string[] } {
  if (!existsSync(join(root, 'services', service))) throw new Error(`no services/${service}; a use case belongs to a service folder`);
  const id = nextId(registry);
  const doc = join(USECASE_DIR, service, `${slug(title)}.md`);
  if (existsSync(join(root, doc))) throw new Error(`${doc} already exists; pick a title naming a different topic`);
  const script = join(USECASE_DIR, service, 'scripts', `test-${id}-api.py`);
  for (const [path, body] of [
    [doc, docTemplate(id, service, title)],
    [script, SCRIPT_STUB(id)],
  ] as const) {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), body);
  }
  const readme = join(root, USECASE_DIR, 'README.md');
  const lines = readFileSync(readme, 'utf8').split('\n');
  const last = lines.findLastIndex((l) => /^\| `?uc-\d{3}/.test(l));
  lines.splice(last + 1, 0, `| ${id} | ${service} | ${title} | api | draft |`);
  writeFileSync(readme, lines.join('\n'));
  const index = join(root, 'docs/README.md');
  const idx = readFileSync(index, 'utf8').split('\n');
  const at = idx.findLastIndex((l) => l.includes('`usecases/'));
  const rel = doc.slice('docs/'.length);
  if (at >= 0) {
    idx.splice(at + 1, 0, `| \`${rel}\` | ${id}: ${title} |`);
    writeFileSync(index, idx.join('\n'));
  }
  return { id, files: [doc, script, `${USECASE_DIR}/README.md`, ...(at >= 0 ? ['docs/README.md'] : [])] };
}
