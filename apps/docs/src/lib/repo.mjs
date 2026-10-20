/**
 * What the docs site knows about the repository it lives in: every public file, every docs page with its URL and
 * heading anchors, and the order docs/README.md lists them in. Read once per process from the working tree, so the
 * site always renders the commit it is built from.
 *
 * JavaScript, not TypeScript, so the link check (scripts/check-links.mjs) imports it under plain node.
 */
import fs from 'node:fs';
import path from 'node:path';

import Slugger from 'github-slugger';
import { toString as mdToString } from 'mdast-util-to-string';
import { remark } from 'remark';
import remarkGfm from 'remark-gfm';
import { visit } from 'unist-util-visit';

export const REPO = 'chanl-ai/ops-ai';
// The commit a GitHub link points at: the deployed commit on Vercel, otherwise main.
export const REF = process.env.VERCEL_GIT_COMMIT_SHA || process.env.OPS_DOCS_GIT_REF || 'main';

// Folders that exist in a working copy but never in the public repository (.codeloop/ is the private board,
// evidence/ and shape/ are stripped from snapshots); a link into one is a broken link.
const NOT_PUBLIC = ['.codeloop', 'evidence', 'shape', 'triage', 'dist'];
const SKIP_DIRS = new Set(['.git', 'node_modules', '.next', '.source', '.venv', '__pycache__', '.pytest_cache', '.turbo']);
// Folders of docs/ the site does not show: docs/plan/ (delivery plans) and docs/media/ (README screenshots).
export const SITE_EXCLUDE = ['docs/plan/', 'docs/media/'];

/** The repository root: two folders above the docs app. */
export function repoRoot() {
  const fromCwd = path.resolve(process.cwd(), '../..');
  if (fs.existsSync(path.join(fromCwd, 'docs/README.md'))) return fromCwd;
  return path.resolve(process.cwd());
}

function walk(root, dir = '', out = []) {
  for (const e of fs.readdirSync(path.join(root, dir), { withFileTypes: true })) {
    if (SKIP_DIRS.has(e.name)) continue;
    const rel = dir ? `${dir}/${e.name}` : e.name;
    if (!dir && NOT_PUBLIC.includes(e.name)) continue;
    if (e.isDirectory()) walk(root, rel, out);
    else out.push(rel);
  }
  return out;
}

/** docs/a/b.md -> /a/b, docs/a/README.md -> /a, docs/README.md -> / */
export function pageUrl(repoPath) {
  const rel = repoPath.replace(/^docs\//, '').replace(/\.md$/, '');
  const trimmed = rel === 'README' ? '' : rel.replace(/\/README$/, '');
  return `/${trimmed}`;
}

export function isSitePage(repoPath) {
  return repoPath.startsWith('docs/') && repoPath.endsWith('.md') && !SITE_EXCLUDE.some((d) => repoPath.startsWith(d));
}

function headingSlugs(markdown) {
  const tree = remark().use(remarkGfm).parse(markdown);
  const slugger = new Slugger();
  const slugs = [];
  visit(tree, 'heading', (node) => {
    if (node.depth > 1) slugs.push(slugger.slug(mdToString(node)));
  });
  return slugs;
}

let index;

/** { root, files: Set, dirs: Set, pages: { 'docs/x.md': { url, anchors } }, order: ['architecture/overview.md', ...] } */
export function repoIndex() {
  if (index) return index;
  const root = repoRoot();
  const list = walk(root);
  const files = new Set(list);
  const dirs = new Set();
  for (const f of list) {
    const parts = f.split('/');
    for (let i = 1; i < parts.length; i++) dirs.add(parts.slice(0, i).join('/'));
  }
  const pages = {};
  for (const f of list) {
    if (!isSitePage(f)) continue;
    pages[f] = { url: pageUrl(f), anchors: headingSlugs(fs.readFileSync(path.join(root, f), 'utf8')) };
  }
  const readme = fs.readFileSync(path.join(root, 'docs/README.md'), 'utf8');
  const order = [];
  for (const m of readme.matchAll(/`([\w./-]+\.(?:md|html))`|\]\(([\w./-]+\.md)\)/g)) {
    const p = path.posix.normalize(m[1] ?? m[2]);
    if (!order.includes(p)) order.push(p);
  }
  index = { root, files, dirs, pages, order };
  return index;
}

export function githubUrl(kind, repoPath, hash = '') {
  return `https://github.com/${REPO}/${kind}/${REF}/${repoPath}${hash}`;
}
