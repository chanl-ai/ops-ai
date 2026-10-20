#!/usr/bin/env node
// Runs the site's remark plugin over every docs page before `next build` and fails on a broken link, listing each
// one. The same failure inside `next build` shows only as "Cannot find module 'fumadocs-mdx:collections/server'".
import fs from 'node:fs';
import path from 'node:path';

import { remark } from 'remark';
import remarkGfm from 'remark-gfm';

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
if (errors.length) {
  console.error(`check-links: ${errors.length} broken link(s) in docs/\n  ${errors.join('\n  ')}`);
  process.exit(1);
}
console.log(`check-links: ${Object.keys(idx.pages).length} pages, every link resolves`);
