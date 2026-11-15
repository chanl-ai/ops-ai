#!/usr/bin/env node
// Checks that every agent guide (each CLAUDE.md and AGENTS.md) points at things that exist: relative links and their
// #anchors, repo paths in backticks (with any :line inside the file), and `make` targets, including `make -C <dir>`.
// A guide that names a moved file or a renamed target sends the next agent down a dead end, and nothing else catches it.
// Exit 1 lists every miss; run from the repo root (`make docs-guides-check`). `--self-test` proves each check can fail.
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, normalize } from 'node:path';

const ROOTS = /^(apps|services|packages|sdk|scripts|make|docs|deploy|examples|config|plugins|builtin-plugins|changelog|\.github|\.claude|\.githooks|\.devcontainer)\//;
const targetCache = new Map();

function makeTargets(dir) {
  if (!targetCache.has(dir)) {
    let db = '';
    try {
      db = execFileSync('make', ['-C', dir, '-pRrq', ':'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], maxBuffer: 64 << 20 });
    } catch (e) {
      db = e.stdout ?? ''; // -q exits non-zero when ":" is out of date; the database is still printed
    }
    const names = new Set();
    for (const line of db.split('\n')) {
      const m = /^([A-Za-z0-9][\w.%/-]*):(?!=)/.exec(line);
      if (m) names.add(m[1]);
    }
    targetCache.set(dir, names);
  }
  return targetCache.get(dir);
}

// GitHub's heading slug: lower case, drop punctuation except hyphens and spaces, spaces to hyphens.
const slug = (h) => h.trim().toLowerCase().replace(/[^\p{L}\p{N} _-]/gu, '').replace(/ /g, '-');
function anchors(file) {
  const text = readFileSync(file, 'utf8').replace(/```[\s\S]*?```/g, '');
  return new Set([...text.matchAll(/^#{1,6}\s+(.+?)\s*$/gm)].map((m) => slug(m[1].replace(/`/g, ''))));
}

// The nearest folder at or above `dir` (below the root) with its own Makefile.
function ownMakefile(dir) {
  for (let d = dir; d && d !== '.'; d = dirname(d)) if (existsSync(join(d, 'Makefile'))) return [d];
  return [];
}

const placeholder = (s) => /[<>*{}$]|\.\.\.|…/.test(s);

export function check(file, text) {
  const misses = [];
  const dir = dirname(file);
  const body = text.replace(/```[\s\S]*?```/g, '');
  for (const [, target] of body.matchAll(/\[[^\]]*\]\(([^)\s]+)\)/g)) {
    if (/^(https?:|mailto:)/.test(target)) continue;
    const [path, anchor] = target.split('#');
    const resolved = path ? normalize(join(dir, path)) : file;
    if (!existsSync(resolved)) { misses.push(`link ${target}: ${resolved} does not exist`); continue; }
    if (anchor && resolved.endsWith('.md') && !anchors(resolved).has(anchor)) misses.push(`link ${target}: no heading #${anchor} in ${resolved}`);
  }
  for (const [, code] of body.matchAll(/`([^`\n]+)`/g)) {
    for (const m of code.matchAll(/(?:^|[;&|(]\s*|\s)make((?:\s+-C\s+\S+)?)\s+([A-Za-z][\w.-]*)/g)) {
      const mdir = m[1].trim().replace(/^-C\s+/, '');
      if (placeholder(mdir) || placeholder(m[2]) || m[2].endsWith('-')) continue;
      // Without -C, a folder guide's `make x` may mean the root Makefile or the folder's own (run from that folder).
      const dirs = mdir ? [mdir.startsWith('.') ? normalize(join(dir, mdir)) : mdir] : ['.', ...ownMakefile(dir)];
      if (!dirs.some((d) => existsSync(join(d, 'Makefile')))) { misses.push(`make -C ${mdir}: no Makefile`); continue; }
      if (!dirs.some((d) => existsSync(join(d, 'Makefile')) && makeTargets(d).has(m[2]))) misses.push(`make ${mdir ? '-C ' + mdir + ' ' : ''}${m[2]}: no such target`);
    }
    const p = code.trim();
    if (!/^[\w.@-]+(\/[\w.@-]+)+\/?(:\d+)?$/.test(p) || placeholder(p)) continue;
    const [, rel, line] = /^(.*?)(?::(\d+))?$/.exec(p);
    const candidates = [rel, normalize(join(dir, rel))];
    const hit = candidates.find((c) => existsSync(c));
    if (!hit) { if (ROOTS.test(rel) || existsSync(dir + '/' + rel.split('/')[0])) misses.push(`path ${p}: does not exist`); continue; }
    if (line && statSync(hit).isFile() && readFileSync(hit, 'utf8').split('\n').length < Number(line)) misses.push(`path ${p}: file has fewer lines`);
  }
  return misses;
}

function selfTest() {
  const bad = check('CLAUDE.md', '[x](no-such-file.md) [y](AGENTS.md#no-such-heading) `make no-such-target` `scripts/no-such.py` `make/docs.mk:99999`');
  const good = check('CLAUDE.md', '[x](AGENTS.md) `make help` `make -C services/tools-service lint` `scripts/check-docs.mjs`');
  if (bad.length !== 5 || good.length !== 0) {
    console.error('check-guides self-test failed', { bad, good });
    process.exit(1);
  }
  console.log('check-guides self-test: 5 planted misses found, 0 on good input');
}

if (process.argv.includes('--self-test')) selfTest();
else {
  const files = execFileSync('git', ['ls-files', '--cached', '--others', '--exclude-standard', '*CLAUDE.md', '*AGENTS.md'], { encoding: 'utf8' })
    .split('\n').filter((f) => f && existsSync(f) && !f.startsWith('docs/'));
  let n = 0;
  for (const f of files) for (const miss of check(f, readFileSync(f, 'utf8'))) { console.error(`${f}: ${miss}`); n++; }
  console.log(`check-guides: ${files.length} guides, ${n} misses`);
  process.exit(n ? 1 : 0);
}
