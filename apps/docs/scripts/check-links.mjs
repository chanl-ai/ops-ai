#!/usr/bin/env node
// Runs the site's remark plugin over every docs page before `next build` and fails on a broken link or a page that no
// sidebar tab places, listing each one. The same failure inside `next build` shows only as "Cannot find module
// 'fumadocs-mdx:collections/server'".
import fs from 'node:fs';
import path from 'node:path';

import { remark } from 'remark';
import remarkGfm from 'remark-gfm';
import { visit } from 'unist-util-visit';

import { docsTabPages, unplacedPages } from '../src/lib/nav.mjs';
import { remarkOpsAi } from '../src/lib/remark-ops-ai.mjs';
import { repoIndex } from '../src/lib/repo.mjs';

const idx = repoIndex();
const processor = remark().use(remarkGfm).use(remarkOpsAi, { throwOnError: false });
const errors = [];
for (const page of Object.keys(idx.pages)) {
  const file = { path: path.join(idx.root, page), value: fs.readFileSync(path.join(idx.root, page), 'utf8'), data: {} };
  try {
    await processor.run(processor.parse(file.value), file);
  } catch (err) {
    errors.push(`${page}: ${err.message}`);
  }
  errors.push(...(file.data.opsAi?.errors ?? []));
}
// A page no tab places renders but cannot be reached from the sidebar.
for (const page of unplacedPages(Object.keys(idx.pages).map((p) => p.slice('docs/'.length)))) {
  errors.push(`docs/${page}: in no sidebar tab; add it to SITE in apps/docs/src/lib/nav.mjs`);
}
// A Docs-tab page opens in the reader's words: no code span (a path, a service, a package) in its status line or its
// first paragraph. Where things live belongs in a table further down.
for (const page of docsTabPages()) {
  const tree = remark().use(remarkGfm).parse(fs.readFileSync(path.join(idx.root, 'docs', page), 'utf8'));
  const paragraphs = tree.children.filter((n) => n.type === 'paragraph');
  const opening = paragraphs.slice(0, /^Status:/.test(paragraphs[0]?.children[0]?.value ?? '') ? 2 : 1);
  let codes = 0;
  for (const p of opening) visit(p, 'inlineCode', () => void codes++);
  if (codes) errors.push(`docs/${page}: ${codes} code span(s) in the opening; say it in words and move paths lower`);
}
if (errors.length) {
  console.error(`check-links: ${errors.length} problem(s) in docs/\n  ${errors.join('\n  ')}`);
  process.exit(1);
}
console.log(`check-links: ${Object.keys(idx.pages).length} pages, every link resolves and every page is in a tab`);
