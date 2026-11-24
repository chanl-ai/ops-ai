/**
 * What the docs site knows about the repository it lives in: every public file, every published page with its URL and
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

import { sitePages } from './nav.mjs';

export const REPO = 'chanl-ai/ops-ai';
// The commit a GitHub link points at: the deployed commit on Vercel, otherwise main.
export const REF = process.env.VERCEL_GIT_COMMIT_SHA || process.env.OPS_DOCS_GIT_REF || 'main';

// Folders that exist in a working copy but not in the repository; a link into one is a broken link.
const NOT_PUBLIC = ['evidence', 'shape', 'triage', 'dist'];
const SKIP_DIRS = new Set(['.git', 'node_modules', '.next', '.source', '.venv', '__pycache__', '.pytest_cache', '.turbo']);
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

// The site opens on the Welcome page; docs/README.md, the index of every document, sits at /contents.
/** @type {Record<string, string>} */
export const SITE_ROOTS = { 'docs/welcome.md': '/', 'docs/README.md': '/contents' };

/** docs/a/b.md -> /a/b, docs/a/README.md -> /a, with SITE_ROOTS for the two top pages */
export function pageUrl(repoPath) {
  if (SITE_ROOTS[repoPath]) return SITE_ROOTS[repoPath];
  const rel = repoPath.replace(/^docs\//, '').replace(/\.md$/, '');
  const trimmed = rel === 'README' ? '' : rel.replace(/\/README$/, '');
  return `/${trimmed}`;
}

const SITE_PAGES = new Set(sitePages().map((p) => `docs/${p}`));

/** True for a page the site publishes: one that SITE in nav.mjs names. Every other file under docs/ is only in the repository. */
export function isSitePage(repoPath) {
  return SITE_PAGES.has(repoPath);
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

const anchorCache = new Map();

/**
 * A page's heading anchors, re-read whenever the file's mtime changes. The index below is built once per process, so a
 * dev server that outlives an edit would otherwise check links against the page as it was at start.
 */
export function pageAnchors(repoPath) {
  const file = path.join(repoRoot(), repoPath);
  const mtime = fs.statSync(file).mtimeMs;
  const hit = anchorCache.get(repoPath);
  if (hit?.mtime === mtime) return hit.anchors;
  const anchors = headingSlugs(fs.readFileSync(file, 'utf8'));
  anchorCache.set(repoPath, { mtime, anchors });
  return anchors;
}

let index;

/** { root, files: Set, dirs: Set, pages: { 'docs/x.md': { url } }, order: ['architecture/README.md', ...] } */
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
    pages[f] = { url: pageUrl(f) };
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
