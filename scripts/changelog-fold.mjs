#!/usr/bin/env node
// Folds the changelog fragments (changelog/<topic>.json, one change each, written while work is unreleased so parallel
// pull requests never touch the same file) into one file per release, changelog/releases/<version>.json:
//   { "version", "date", "entries": [{ "title", "description", "tag" }] }
//
//   --release <X.Y.Z> [--date <YYYY-MM-DD>]   every fragment goes into that release's file and the fragments are removed
//                                             (date defaults to today). With --ref <sha> nothing is written: the plan
//                                             {files, remove} is printed as JSON for scripts/release.py, which commits it
//                                             without a checkout.
//   --history                                 one-off: the fragments that exist now go to the release whose tag date they
//                                             are dated on or before (a day with two tags goes to the tag that held the
//                                             file), entries dated before the first tag to releases/earlier.json
//   --self-test
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

// Run from the repository's root (make, scripts/release.py): the checkout or ref it folds is the one it is run in.
const ROOT = process.cwd();
const TAG_RANK = { new: 0, improved: 1, fix: 2 };

/** Fragments as {id, entry} to one release's content: new first, then improved, then fix, each by title. */
export function releaseFile(version, date, fragments) {
  const entries = fragments
    .map(({ entry }) => ({ title: entry.title, description: entry.description, tag: entry.tag, date: entry.date }))
    .sort((a, b) => TAG_RANK[a.tag] - TAG_RANK[b.tag] || b.date.localeCompare(a.date) || a.title.localeCompare(b.title))
    .map(({ title, description, tag }) => ({ title, description, tag }));
  return { version, date, entries };
}

/** Which release file each fragment belongs to. `tags` are [{version, date, has(id)}] oldest first. */
export function assign(fragments, tags) {
  const out = new Map();
  for (const f of fragments) {
    const d = f.entry.date;
    let version = 'earlier';
    if (d >= tags[0].date) {
      const i = tags.findIndex((t) => t.date >= d);
      if (i < 0) continue; // after the newest tag: stays a fragment
      const same = tags.filter((t) => t.date === tags[i].date);
      version = (same.find((t) => t.has(f.id)) ?? same.at(-1)).version;
    }
    out.set(version, [...(out.get(version) ?? []), f]);
  }
  return out;
}

const json = (v) => `${JSON.stringify(v, null, 2)}\n`;
const read = (root) => {
  const dir = join(root, 'changelog');
  return existsSync(dir)
    ? readdirSync(dir).filter((f) => f.endsWith('.json')).sort().map((f) => ({ id: f.replace(/\.json$/, ''), entry: JSON.parse(readFileSync(join(dir, f), 'utf8')) }))
    : [];
};
const git = (...a) => execFileSync('git', a, { cwd: ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();

/** The fragments at a commit, without a checkout. */
function readRef(ref) {
  const names = git('ls-tree', '--name-only', ref, 'changelog/').split('\n').filter((p) => p.endsWith('.json'));
  return names.map((p) => ({ id: p.slice('changelog/'.length, -5), entry: JSON.parse(git('show', `${ref}:${p}`)) }));
}

function plan(fragments, version, date) {
  if (!fragments.length) return { files: {}, remove: [] };
  return { files: { [`changelog/releases/${version}.json`]: json(releaseFile(version, date, fragments)) }, remove: fragments.map((f) => `changelog/${f.id}.json`) };
}

function apply(root, { files, remove }) {
  for (const [p, text] of Object.entries(files)) {
    mkdirSync(dirname(join(root, p)), { recursive: true });
    writeFileSync(join(root, p), text);
  }
  for (const p of remove) rmSync(join(root, p), { force: true });
}

function selfTest() {
  const frag = (id, date, tag, title) => ({ id, entry: { date, title, description: 'Does a thing.', tag } });
  const a = frag('a', '2026-11-19', 'fix', 'Fixed');
  const b = frag('b', '2026-11-19', 'new', 'Brand new');
  const c = frag('c', '2026-11-01', 'improved', 'Early');
  const d = frag('d', '2026-11-25', 'new', 'Same day, first tag');
  const e = frag('e', '2026-11-25', 'new', 'Same day, second tag');
  const f = frag('f', '2026-11-30', 'new', 'After the last tag');
  const tags = [
    { version: '1.0.0', date: '2026-11-19', has: (id) => ['a', 'b'].includes(id) },
    { version: '1.1.0', date: '2026-11-25', has: (id) => id === 'd' },
    { version: '1.1.1', date: '2026-11-25', has: () => true },
  ];
  const got = assign([a, b, c, d, e, f], tags);
  const ids = (v) => (got.get(v) ?? []).map((x) => x.id).join('');
  const checks = [
    ['an entry dated on a tag day goes to that tag', ids('1.0.0') === 'ab'],
    ['an entry before the first tag goes to earlier', ids('earlier') === 'c'],
    ['a day with two tags goes to the one that held the file, else the later', ids('1.1.0') === 'd' && ids('1.1.1') === 'e'],
    ['an entry after the newest tag stays a fragment', ![...got.values()].flat().includes(f)],
    ['a release lists new, then improved, then fix', releaseFile('1.0.0', '2026-11-19', [a, b]).entries.map((x) => x.tag).join() === 'new,fix'],
    ['a release drops the fragment dates', !('date' in releaseFile('1.0.0', '2026-11-19', [a]).entries[0])],
    ['no fragments plans nothing', Object.keys(plan([], '1.2.0', '2026-12-01').files).length === 0],
  ];
  for (const [name, ok] of checks) console.log(`${ok ? 'PASS' : 'FAIL'} ${name}`);
  return checks.every(([, ok]) => ok);
}

const args = process.argv.slice(2);
const opt = (n) => (args.includes(n) ? args[args.indexOf(n) + 1] : null);
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  if (args.includes('--self-test')) process.exit(selfTest() ? 0 : 1);
  else if (opt('--release')) {
    const version = opt('--release');
    if (!/^\d+\.\d+\.\d+$/.test(version)) throw new Error(`'${version}' is not X.Y.Z`);
    const date = opt('--date') ?? new Date().toISOString().slice(0, 10);
    const ref = opt('--ref');
    const p = plan(ref ? readRef(ref) : read(ROOT), version, date);
    if (ref) process.stdout.write(json(p));
    else apply(ROOT, p);
  } else if (args.includes('--history')) {
    const tags = ['v1.0.0', 'v1.1.0', 'v1.1.1'].map((t) => {
      const held = new Set(git('ls-tree', '--name-only', t, 'changelog/').split('\n').map((p) => p.slice('changelog/'.length, -5)));
      return { version: t.slice(1), date: git('log', '-1', '--format=%cs', t), has: (id) => held.has(id) };
    });
    for (const [version, frags] of assign(read(ROOT), tags)) {
      const date = version === 'earlier' ? frags.map((f) => f.entry.date).sort().at(-1) : tags.find((t) => t.version === version).date;
      apply(ROOT, plan(frags, version, date));
      console.log(`${version}: ${frags.length} entries (${frags.filter((f) => f.entry.tag === 'fix').length} fixes)`);
    }
  } else {
    console.error('usage: changelog-fold.mjs --release X.Y.Z [--date D] [--ref sha] | --history | --self-test');
    process.exit(2);
  }
}
