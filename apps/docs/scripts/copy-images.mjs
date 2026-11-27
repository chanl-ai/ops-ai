#!/usr/bin/env node
// Copies every image under docs/ into public/, at the same path it has under docs/, so the static export serves
// docs/media/hero.gif at /docs/media/hero.gif. Markdown across the repository names images by that URL
// (src/lib/repo.mjs, IMAGE_HOSTS), which keeps them loading on GitHub and anywhere else a page is read.
// public/ is generated and git ignores it; the copy starts clean so a deleted image is not served from an old run.
import fs from 'node:fs';
import path from 'node:path';

import { IMAGE_EXT, repoIndex } from '../src/lib/repo.mjs';

const { root, files } = repoIndex();
const out = path.join(root, 'apps/docs/public');
fs.rmSync(out, { recursive: true, force: true });
let n = 0;
for (const f of files) {
  if (!f.startsWith('docs/') || !IMAGE_EXT.test(f)) continue;
  const dest = path.join(out, f.slice('docs/'.length));
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(path.join(root, f), dest);
  n++;
}
console.log(`copy-images: ${n} images from docs/ into public/`);
