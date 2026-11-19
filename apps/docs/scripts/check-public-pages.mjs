#!/usr/bin/env node
// Holds the pages in the user tabs (Docs, Security, Reference: the tabs SITE marks `public`) to the user-page rule in
// docs/guide/skills/ops-docs-write.md: they state behaviour, not where the code lives. In code spans and code blocks it
// counts repository paths, file:line references, local ports and make targets; local ports also count in links.
//
// public-pages-allowlist.json lists the pages that broke the rule when the check arrived, with their counts. The list
// may only shrink: the check fails when a page has more offences than listed, an unlisted page has any, or a listed page
// is clean or no longer in a user tab. `--shrink` lowers the counts to what the pages hold now; it never raises one.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { remark } from 'remark';
import remarkGfm from 'remark-gfm';
import { visit } from 'unist-util-visit';

import { publicPages } from '../src/lib/nav.mjs';
import { repoIndex } from '../src/lib/repo.mjs';

const ALLOWLIST = path.join(path.dirname(fileURLToPath(import.meta.url)), 'public-pages-allowlist.json');

const TOP_DIRS = 'services|packages|apps|scripts|sdk|deploy|make|docs|examples|plugins|builtin-plugins|config|changelog|\\.github';
const RULES = [
  { kind: 'repository path', re: new RegExp(`(?<![\\w./-])(?:\\./)?(?:${TOP_DIRS})/[\\w.-]`, 'g') },
  { kind: 'file:line', re: /[\w-]\.(?:py|pyi|ts|tsx|js|mjs|cjs|md|ya?ml|json|sql|sh|toml|css|html):\d+/g },
  { kind: 'local port', re: /(?:localhost|127\.0\.0\.1|0\.0\.0\.0):\d+/g },
  { kind: 'make target', re: /(?:^|[\s;&|(`$])make\s+(?:-C\s+\S+\s+)?[a-z][\w-]*/gm },
];

/** Offences on one page (path relative to docs/), as { kind: count }. */
export function offences(page) {
  const text = fs.readFileSync(path.join(repoIndex().root, 'docs', page), 'utf8');
  const tree = remark().use(remarkGfm).parse(text);
  const found = {};
  const scan = (value, kinds) => {
    for (const { kind, re } of RULES) {
      if (!kinds.includes(kind)) continue;
      const n = value.match(re)?.length ?? 0;
      if (n) found[kind] = (found[kind] ?? 0) + n;
    }
  };
  const all = RULES.map((r) => r.kind);
  visit(tree, ['inlineCode', 'code'], (node) => {
    if (node.type === 'code' && node.lang === 'mermaid') return;
    scan(node.value, all);
  });
  visit(tree, 'link', (node) => scan(node.url, ['local port']));
  visit(tree, 'text', (node) => scan(node.value, ['local port']));
  return found;
}

const total = (o) => Object.values(o).reduce((a, b) => a + b, 0);

function main() {
  const idx = repoIndex();
  const pages = publicPages(Object.keys(idx.pages).map((p) => p.slice('docs/'.length))).sort();
  const allow = JSON.parse(fs.readFileSync(ALLOWLIST, 'utf8'));
  const counts = Object.fromEntries(pages.map((p) => [p, offences(p)]));

  if (process.argv.includes('--shrink')) {
    const next = {};
    for (const [page, listed] of Object.entries(allow)) {
      const now = counts[page] ? total(counts[page]) : 0;
      if (now) next[page] = Math.min(listed, now);
    }
    fs.writeFileSync(ALLOWLIST, `${JSON.stringify(next, null, 2)}\n`);
    console.log(`check-public-pages: allowlist now ${Object.keys(next).length} pages`);
  }

  const errors = [];
  const describe = (o) => Object.entries(o).map(([k, n]) => `${n} ${k}`).join(', ');
  for (const page of pages) {
    const n = total(counts[page]);
    const listed = allow[page] ?? 0;
    if (n > listed) {
      errors.push(`docs/${page}: ${describe(counts[page])} (allowed ${listed}); state the behaviour and the public surface instead`);
    }
  }
  for (const [page, listed] of Object.entries(allow)) {
    if (!pages.includes(page)) errors.push(`docs/${page}: listed in the allowlist but not in a user tab; remove it from the list`);
    else if (total(counts[page]) === 0) errors.push(`docs/${page}: clean now; remove it from the allowlist`);
    else if (total(counts[page]) < listed) console.log(`check-public-pages: docs/${page} has ${total(counts[page])}, listed ${listed}; run with --shrink`);
  }
  if (errors.length) {
    console.error(`check-public-pages: ${errors.length} problem(s), see apps/docs/scripts/check-public-pages.mjs\n  ${errors.join('\n  ')}`);
    process.exit(1);
  }
  const listed = Object.keys(allow);
  console.log(
    `check-public-pages: ${pages.length} user pages; ${listed.length} on the allowlist with ${listed.reduce((a, p) => a + allow[p], 0)} offences left`,
  );
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main();
