#!/usr/bin/env node
// Every console route named in a table row of docs/architecture/console-areas.md must be a page the console serves,
// so the page cannot name /agents after the console moved it to /build/agents. A `{x}` in the doc stands for any
// dynamic segment. Pages come from apps/console/src/app; an old address that only redirects (MOVED in
// apps/console/src/lib/routes/moved.ts) is not a page, so the doc may name it in prose but not in a table.
// Usage: node scripts/check-doc-routes.mjs [--self-test]
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const DOC = 'docs/architecture/console-areas.md';
const APP = 'apps/console/src/app';

function pagesUnder(dir, prefix = '') {
  const routes = [];
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    if (e.isDirectory()) {
      const group = /^\(.*\)$/.test(e.name);
      routes.push(...pagesUnder(join(dir, e.name), group ? prefix : `${prefix}/${e.name}`));
    } else if (e.name === 'page.tsx') routes.push(prefix || '/');
  }
  return routes;
}

const segments = (route) => route.split('/').filter(Boolean);
const dynamic = (s) => /^\[.*\]$/.test(s);

export function check(text, pages) {
  const misses = [];
  const pageSegs = pages.map(segments);
  for (const line of text.split('\n')) {
    if (!line.startsWith('|')) continue;
    for (const [, code] of line.matchAll(/`(\/[^`\s]*)`/g)) {
      const path = code.split(/[?#]/)[0];
      if (!/^\/[a-z0-9{}[\]/-]*$/.test(path)) continue;
      const want = segments(path);
      const hit = pageSegs.some((p) => p.length === want.length && p.every((s, i) => s === want[i] || (dynamic(s) && /^\{.*\}$/.test(want[i]))));
      if (!hit) misses.push(`${code}: the console serves no page there`);
    }
  }
  return misses;
}

function selfTest() {
  const pages = ['/', '/build/agents', '/build/agents/[id]', '/data/tools'];
  const bad = check('| a | `/agents` | `/build/agents/{id}/x` | `/data/missing` |', pages);
  const good = check('| a | `/` | `/build/agents` | `/build/agents/{id}?tab=test` | `/data/tools` |\nprose `/agents`', pages);
  if (bad.length !== 3 || good.length !== 0) {
    console.error('check-doc-routes self-test failed', { bad, good });
    process.exit(1);
  }
  console.log('check-doc-routes self-test: 3 planted routes found, 0 on good input');
}

if (process.argv.includes('--self-test')) selfTest();
else {
  if (!existsSync(DOC) || !existsSync(APP)) { console.error(`check-doc-routes: ${DOC} or ${APP} is missing`); process.exit(1); }
  const misses = check(readFileSync(DOC, 'utf8'), pagesUnder(APP));
  for (const m of misses) console.error(`${DOC}: ${m}`);
  console.log(`check-doc-routes: ${misses.length} misses`);
  process.exit(misses.length ? 1 : 0);
}
