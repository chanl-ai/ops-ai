#!/usr/bin/env node
// Holds the reader pages (the tabs SITE marks `public`: Docs, Security, Reference) to the reader-page rules in
// docs/guide/skills/ops-docs-write.md. A reader page says what the product does for the reader; it carries no build
// bookkeeping and uses the names and console paths of docs/guide/glossary.md.
//
// | Rule | What counts |
// |---|---|
// | repository path, file:line, local port, make target | In code spans and code blocks; local ports also in text and links |
// | status line | A first paragraph that starts "Status:" |
// | roadmap word | planned, upcoming, partial; allowed only on the Feature status page |
// | release or test word | staging, merged, branch and release wording, how something was tested; changelog pages may name releases |
// | internal term | lease, journal, store layer, fencing, outbox |
// | internal name | A service, package or environment variable name, outside the Reference tab |
// | glossary name | A name the glossary's Not column lists |
// | menu path | A console path (parts joined by ›) that is not one of the glossary's, or one written with another separator |
// | repository link | A link to a file in the repository or to a Contributing page |
// | long table cell | A table cell over 15 words |
//
// The glossary's own console paths are checked against the console's menus: every part must be a label in
// apps/console/src/lib/nav.ts, settings-tree.ts or the sidebar.
//
// public-pages-allowlist.json lists the pages that broke a rule when the rule arrived, with a count per rule. The list
// may only shrink: the check fails when a page has more offences of a rule than listed, an unlisted page has any, or a
// listed count is higher than what the page holds now. `--shrink` lowers the counts to what the pages hold now; it never
// raises one. `--self-test` plants one line per rule and fails unless each rule counts it.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { toString as mdToString } from 'mdast-util-to-string';
import { remark } from 'remark';
import remarkGfm from 'remark-gfm';
import { visit } from 'unist-util-visit';

import { pagesOfTab, publicPages } from '../src/lib/nav.mjs';
import { resolveRepoPath } from '../src/lib/remark-ops-ai.mjs';
import { REPO, repoIndex } from '../src/lib/repo.mjs';

const ALLOWLIST = path.join(path.dirname(fileURLToPath(import.meta.url)), 'public-pages-allowlist.json');
const GLOSSARY = 'guide/glossary.md';
const FEATURE_STATUS = 'guide/whats-built-today.md';
const CHANGELOG_PAGES = ['guide/whats-new.md', 'sdk/changelog.md', 'sdk/upgrading.md'];
const CONSOLE_MENUS = ['apps/console/src/lib/nav.ts', 'apps/console/src/lib/settings-tree.ts', 'apps/console/src/components/app-sidebar.tsx'];
const MAX_CELL_WORDS = 15;

const TOP_DIRS = 'services|packages|apps|scripts|sdk|deploy|make|docs|examples|plugins|builtin-plugins|config|changelog|\\.github';
// Counted in code spans and code blocks.
const CODE_RULES = [
  { kind: 'repository path', re: new RegExp(`(?<![\\w./-])(?:\\./)?(?:${TOP_DIRS})/[\\w.-]`, 'g') },
  { kind: 'file:line', re: /[\w-]\.(?:py|pyi|ts|tsx|js|mjs|cjs|md|ya?ml|json|sql|sh|toml|css|html):\d+/g },
  { kind: 'local port', re: /(?:localhost|127\.0\.0\.1|0\.0\.0\.0):\d+/g },
  { kind: 'make target', re: /(?:^|[\s;&|(`$])make\s+(?:-C\s+\S+\s+)?[a-z][\w-]*/gm },
];
const LOCAL_PORT = CODE_RULES[2];
// Counted in prose. `code` also counts the rule in code spans, where names are usually written.
const WORD_RULES = [
  { kind: 'roadmap word', re: /\b(?:planned|upcoming|partial(?:ly)?)\b/gi, except: (p) => p.page === FEATURE_STATUS },
  {
    kind: 'release or test word',
    re: /\b(?:staging|(?:un)?merged|release (?:branch|candidate|train)|(?:feature|develop|main) branch|on develop|(?:this|next|current|later|future) release|tested (?:on|against|with|in|by)|was tested|verified (?:on|against|by)|proven by|use[- ]case (?:run|test)s?|unit tests?|end-to-end tests?|smoke tests?)\b|\bCI\b/g,
    except: (p) => CHANGELOG_PAGES.includes(p.page),
  },
  { kind: 'internal term', re: /\b(?:leases?|leased|journal(?:s|ed)?|store layer|fenc(?:e|ed|ing)|outbox)\b/gi, code: true },
  { kind: 'internal name', re: /\bops_[a-z][a-z_]*\b|\bOPS_[A-Z0-9_]+\b/g, code: true, except: (p) => p.tab === 'Reference' },
];
// The services' own names (the folders under services/) count as internal names too.
const serviceNames = () => [...repoIndex().dirs].filter((d) => /^services\/[^/]+$/.test(d)).map((d) => d.split('/')[1]);

const parse = (text) => remark().use(remarkGfm).parse(text);
const count = (value, re) => value.match(re)?.length ?? 0;
const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** The glossary's console paths and the names its Not column refuses, read from the page's tables. */
export function readGlossary(text) {
  const paths = new Set();
  const avoid = new Set();
  visit(parse(text), 'table', (table) => {
    const [head, ...rows] = table.children.map((row) => row.children.map((cell) => mdToString(cell).trim()));
    const where = head.indexOf('In the console');
    const not = head.indexOf('Not');
    for (const row of rows) {
      if (where >= 0 && row[where]) paths.add(row[where]);
      if (not >= 0) for (const name of (row[not] ?? '').split(',').map((n) => n.trim()).filter(Boolean)) avoid.add(name);
    }
  });
  return { paths: [...paths], avoid: [...avoid] };
}

// A name in lower case is refused in any case, with its plural; a name with a capital is refused as written.
const avoidRe = (name) => new RegExp(`\\b${escape(name)}s?\\b`, name === name.toLowerCase() ? 'gi' : 'g');

/** Console paths in one block of prose that the glossary does not have, plus paths written with another separator. */
function menuPathOffences(text, glossary) {
  const roots = [...new Set(glossary.paths.map((p) => p.split(' › ')[0]))].sort((a, b) => b.length - a.length);
  const starts = glossary.paths.map((p) => p.split(' › ').slice(0, 2).join(' › '));
  let n = 0;
  let from = 0;
  for (let i = text.indexOf(' › ', from); i >= 0; i = text.indexOf(' › ', from)) {
    const left = text.slice(0, i);
    const root = roots.find((r) => left.endsWith(r) && !/\w/.test(left.at(-r.length - 1) ?? ''));
    if (!root || !starts.some((s) => text.slice(i - root.length).startsWith(s))) n++;
    // The rest of the same path (its later ›) belongs to this one.
    from = i + 3;
    for (let k = text.indexOf(' › ', from); k >= 0 && k - from <= 30 && !/[.,;:]/.test(text.slice(from, k)); k = text.indexOf(' › ', from)) from = k + 3;
  }
  if (roots.length) n += count(text, new RegExp(`\\b(?:${roots.map(escape).join('|')})\\s*(?:>|→|->)\\s*[A-Z]`, 'g'));
  return n;
}

/** Offences on one reader page, as { rule: count }. `page` is { page, tab, text }, with `page` relative to docs/. */
export function offences(page, glossary) {
  const tree = parse(page.text);
  const found = {};
  const add = (kind, n) => {
    if (n) found[kind] = (found[kind] ?? 0) + n;
  };
  const words = WORD_RULES.map((r) => (r.kind === 'internal name' ? { ...r, re: new RegExp(`${r.re.source}|\\b(?:${serviceNames().join('|')})\\b`, 'g') } : r)).filter(
    (r) => !r.except?.(page),
  );

  visit(tree, ['inlineCode', 'code'], (node) => {
    if (node.type === 'code' && node.lang === 'mermaid') return;
    for (const { kind, re } of CODE_RULES) add(kind, count(node.value, re));
    if (node.type === 'inlineCode') for (const r of words) if (r.code) add(r.kind, count(node.value, r.re));
  });
  visit(tree, 'text', (node) => {
    add(LOCAL_PORT.kind, count(node.value, LOCAL_PORT.re));
    for (const r of words) add(r.kind, count(node.value, r.re));
    if (page.page !== GLOSSARY) for (const name of glossary.avoid) add('glossary name', count(node.value, avoidRe(name)));
  });

  const first = tree.children.find((n) => n.type === 'paragraph');
  if (first && /^Status:/.test(mdToString(first))) add('status line', 1);

  visit(tree, ['paragraph', 'tableCell', 'heading'], (node) => add('menu path', menuPathOffences(mdToString(node), glossary)));
  visit(tree, 'tableCell', (node) => add('long table cell', mdToString(node).split(/\s+/).filter(Boolean).length > MAX_CELL_WORDS ? 1 : 0));

  const dir = path.posix.dirname(`docs/${page.page}`);
  const contributing = new Set(pagesOfTab('Contributing').map((p) => `docs/${p}`));
  const pages = repoIndex().pages;
  visit(tree, 'link', (node) => {
    const url = node.url;
    add(LOCAL_PORT.kind, count(url, LOCAL_PORT.re));
    if (url.startsWith(`https://github.com/${REPO}/blob/`) || url.startsWith(`https://github.com/${REPO}/tree/`)) return add('repository link', 1);
    if (/^[a-z][a-z0-9+.-]*:/i.test(url) || url.startsWith('//') || url.startsWith('#') || url.startsWith('/')) return;
    const target = path.posix.normalize(path.posix.join(dir, decodeURI(url.split('#')[0]))).replace(/\/$/, '');
    const key = pages[target] ? target : `${target}/README.md`;
    if (pages[key] ? contributing.has(key) : resolveRepoPath(target).url?.startsWith('https://github.com/')) add('repository link', 1);
  });
  return found;
}

/** What the allow list refuses, given each page's offences now: more than listed, or a listing higher than the page. */
export function compare(counts, allow) {
  const errors = [];
  for (const [page, now] of Object.entries(counts)) {
    for (const [kind, n] of Object.entries(now)) {
      const listed = allow[page]?.[kind] ?? 0;
      if (n > listed) errors.push(`docs/${page}: ${n} ${kind} (allowed ${listed})`);
    }
  }
  for (const [page, listed] of Object.entries(allow)) {
    if (!counts[page]) errors.push(`docs/${page}: on the allowlist but not a reader page; remove it from the list`);
    else for (const [kind, n] of Object.entries(listed)) if ((counts[page][kind] ?? 0) < n) errors.push(`docs/${page}: ${counts[page][kind] ?? 0} ${kind}, listed ${n}; run with --shrink`);
  }
  return errors;
}

/** Parts of the glossary's console paths that are not a label in the console's menus. */
function pathsNotInConsole(glossary, root) {
  const source = CONSOLE_MENUS.map((f) => fs.readFileSync(path.join(root, f), 'utf8')).join('\n');
  const labels = new Set([...source.matchAll(/'([^'\n]+)'|"([^"\n]+)"|>\s*([A-Z][\w ]+?)\s*</g)].map((m) => m[1] ?? m[2] ?? m[3]));
  return [...new Set(glossary.paths.flatMap((p) => p.split(' › ')))].filter((part) => !labels.has(part));
}

// One planted line per rule, on a page that is otherwise clean. Each must count under its own rule and no other: once,
// or twice for the internal name line, which plants a variable and a service.
const PLANTS = {
  'repository path': 'Read `apps/console/src/lib/nav.ts` first.',
  'file:line': 'See `main.py:42`.',
  'local port': 'Open `localhost:3016`.',
  'make target': 'Run `make stack-up`.',
  'status line': 'Status: current.',
  'roadmap word': 'Exports are planned.',
  'release or test word': 'This runs on staging today.',
  'internal term': 'Another worker takes the lease.',
  'internal name': 'Set `OPS_MODELS_URL` on agents-service first.',
  'glossary name': 'Turn the connector on.',
  'menu path': 'Open **Data › Apps**.',
  'repository link': 'See [the check](../../scripts/check-docs.mjs).',
  'long table cell': '| A |\n|---|\n| one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen |',
};

function selfTest() {
  const glossary = { paths: ['Data Gateway › Apps', 'Governance › Access › Roles'], avoid: ['connector'] };
  const clean = '# A page\n\nYou connect an app in **Data Gateway › Apps**, then give a role in **Governance › Access › Roles**.\n\nSee [the glossary](glossary.md).\n';
  const on = (text) => offences({ page: 'guide/self-test.md', tab: 'Docs', text }, glossary);
  const failures = [];
  if (Object.keys(on(clean)).length) failures.push(`the clean page counts ${JSON.stringify(on(clean))}`);
  for (const [kind, line] of Object.entries(PLANTS)) {
    const got = on(kind === 'status line' ? clean.replace('\n\n', `\n\n${line}\n\n`) : `${clean}\n${line}\n`);
    if (got[kind] !== (kind === 'internal name' ? 2 : 1) || Object.keys(got).length !== 1) failures.push(`"${kind}" planted, counted ${JSON.stringify(got)}`);
  }
  const listed = { 'a.md': { 'status line': 1 } };
  if (compare({ 'a.md': { 'status line': 1 } }, listed).length) failures.push('a listed offence is refused');
  if (!compare({ 'a.md': { 'status line': 1, 'roadmap word': 1 } }, listed).length) failures.push('a new rule on a listed page passes');
  if (!compare({ 'a.md': { 'status line': 1 }, 'b.md': { 'menu path': 1 } }, listed).length) failures.push('an unlisted page passes');
  if (!compare({ 'a.md': {} }, listed).length) failures.push('a listing higher than the page passes');
  if (failures.length) {
    console.error(`check-public-pages self-test: ${failures.length} failure(s)\n  ${failures.join('\n  ')}`);
    process.exit(1);
  }
  console.log(`check-public-pages self-test: ${Object.keys(PLANTS).length} planted rules counted, 0 on the clean page`);
}

function main() {
  const idx = repoIndex();
  const read = (page) => fs.readFileSync(path.join(idx.root, 'docs', page), 'utf8');
  const glossary = readGlossary(read(GLOSSARY));
  const allow = JSON.parse(fs.readFileSync(ALLOWLIST, 'utf8'));
  const pages = publicPages().filter((p) => idx.pages[`docs/${p.page}`]);
  const counts = Object.fromEntries(pages.map((p) => [p.page, offences({ ...p, text: read(p.page) }, glossary)]));

  if (process.argv.includes('--shrink')) {
    for (const [page, listed] of Object.entries(allow)) {
      for (const [kind, n] of Object.entries(listed)) {
        const now = counts[page]?.[kind] ?? 0;
        if (now) listed[kind] = Math.min(n, now);
        else delete listed[kind];
      }
      if (!Object.keys(listed).length) delete allow[page];
    }
    fs.writeFileSync(ALLOWLIST, `${JSON.stringify(allow, null, 2)}\n`);
    console.log(`check-public-pages: allowlist now ${Object.keys(allow).length} pages`);
  }

  const errors = [
    ...pathsNotInConsole(glossary, idx.root).map((part) => `docs/${GLOSSARY}: "${part}" is not a label in the console's menus (${CONSOLE_MENUS[0]})`),
    ...compare(counts, allow),
  ];
  if (errors.length) {
    console.error(`check-public-pages: ${errors.length} problem(s); the rules are in docs/guide/skills/ops-docs-write.md\n  ${errors.join('\n  ')}`);
    process.exit(1);
  }
  const left = Object.values(allow).reduce((a, kinds) => a + Object.values(kinds).reduce((x, y) => x + y, 0), 0);
  console.log(`check-public-pages: ${pages.length} reader pages; ${Object.keys(allow).length} on the allowlist with ${left} offences left`);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  if (process.argv.includes('--self-test')) selfTest();
  else main();
}
