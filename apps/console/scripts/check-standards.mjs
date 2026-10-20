#!/usr/bin/env node
// Enforces the grep-provable rules in CLAUDE.md. Exits 1 with file:line for every violation.
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { join, relative } from 'node:path';

const root = new URL('..', import.meta.url).pathname;
const src = join(root, 'src');

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    return statSync(p).isDirectory() ? walk(p) : /\.(ts|tsx)$/.test(name) ? [p] : [];
  });
}

const files = walk(src).map((abs) => ({ abs, rel: relative(root, abs), text: readFileSync(abs, 'utf8') }));
const violations = [];
const notes = [];

// 14. Colours come from the theme tokens and layout widths are fluid (docs/console/standards.md). Files that broke
//     this before the rule existed are listed with their count in palette-baseline.json; a file may lower its count,
//     never raise it, and a file not listed may have none. `--write-baseline` records the current counts after a
//     conversion lowers them.
const PALETTE = /\b(?:text|bg|border|ring|fill|stroke|from|via|to|divide|outline|decoration)-(?:amber|emerald|green|red|slate|gray|zinc|sky|blue|violet|indigo|purple|orange|yellow|rose|pink|teal|cyan|lime|fuchsia|stone|neutral)-\d{2,3}\b/g;
const FIXED_WIDTH = /(?<![\w-])(?:min-|max-)?w-\[\d+px\]/g;
// A rail (a fixed-width column that does not shrink, e.g. the chat thread list) is correct layout, so a px width on an
// element whose classes include shrink-0 is allowed.
const classesAround = (text, index) => {
  const open = Math.max(text.lastIndexOf('"', index), text.lastIndexOf("'", index), text.lastIndexOf('`', index));
  const close = text.indexOf(text[open], index);
  return text.slice(open + 1, close < 0 ? index : close);
};
const isRail = (text, m) => /(^|\s)shrink-0(\s|$)/.test(classesAround(text, m.index));
const baselinePath = join(root, 'scripts/palette-baseline.json');
const baseline = existsSync(baselinePath) ? JSON.parse(readFileSync(baselinePath, 'utf8')) : {};
const counts = {};
const lineOf = (text, index) => text.slice(0, index).split('\n').length;
const report = (f, index, rule) => violations.push(`${f.rel}:${lineOf(f.text, index)}  ${rule}`);

const inDir = (f, d) => f.rel.startsWith(`src/${d}/`);
const isUi = (f) => inDir(f, 'components/ui');
/** The only files allowed to move file bytes: the Files API client and mock, the upload hook, and the shared upload component. */
const isFilesLayer = (f) => /^src\/(lib\/api\/files-[a-z]+\.ts|lib\/api\/mock\/files\/|hooks\/file-queries\.ts|components\/shared\/file-upload\.tsx)/.test(f.rel);

for (const f of files) {
  const { text } = f;

  // 1. Fixtures live only in the mock layer.
  if (!inDir(f, 'lib/api')) {
    for (const m of text.matchAll(/from ['"](@\/lib\/api\/mock[^'"]*|\.{1,2}\/[^'"]*mock[^'"]*)['"]/g)) report(f, m.index, 'imports the mock layer outside src/lib/api');
  }

  // 2. Components are props-only: no runtime import of the API client.
  if (inDir(f, 'components')) {
    for (const m of text.matchAll(/^import (?!type )[^\n]*from ['"]@\/lib\/api['"]/gm)) report(f, m.index, 'component imports the API client (use a hook in the page, pass props)');
  }

  // 3. Pages read data through hooks, never the client directly.
  if (inDir(f, 'app')) {
    for (const m of text.matchAll(/^import \{[^}]*\bapi\b[^}]*\} from ['"]@\/lib\/api['"]/gm)) report(f, m.index, 'page imports `api` directly (use a hook from src/hooks)');
  }

  // 4. Only the API entry reads env. proxy.ts also reads the server-side switch that lets a use-case run open /dev and /preview.
  if (f.rel !== 'src/lib/api/index.ts' && f.rel !== 'src/proxy.ts') {
    for (const m of text.matchAll(/process\.env\.(?!NODE_ENV)/g)) report(f, m.index, 'reads process.env outside src/lib/api/index.ts');
  }

  if (isUi(f)) continue;

  // 5. Dialogs go through DialogShell / DeleteDialog.
  if (!/components\/shared\/(dialog-shell|delete-dialog|detail-sheet)\.tsx$/.test(f.rel)) {
    for (const m of text.matchAll(/<DialogContent\b/g)) report(f, m.index, 'raw DialogContent (use DialogShell)');
  }

  // 6. Lists use the table primitives, not raw HTML tables.
  for (const m of text.matchAll(/<table[\s>]/g)) report(f, m.index, 'raw <table> (use DataTableWithViews or ui/table)');

  // 7. Effects must not return a value.
  for (const m of text.matchAll(/useEffect\(\(\) => (?!\{)/g)) report(f, m.index, 'expression-bodied useEffect (wrap the body in braces)');

  // 8. No browser dialogs.
  for (const m of text.matchAll(/\b(window\.)?(alert|confirm|prompt)\(/g)) {
    if (!/\.(confirm|prompt)\(/.test(text.slice(m.index - 1, m.index + 10)) || m[1]) report(f, m.index, 'browser alert/confirm/prompt (build the confirm into the UI)');
  }

  // 9. Copy: no "(s)" plurals in user-facing strings.
  for (const m of text.matchAll(/[a-z]\(s\)(?=[ '"`,.])/g)) report(f, m.index, '"(s)" plural in copy (use plural())');

  // 10. "New" is a dialog, never a page.
  if (/^src\/app\/.*\/new\/page\.tsx$/.test(f.rel)) report(f, 0, '/new page (create in a DialogShell, then open the edit page)');

  // 13. File bytes leave the browser only through the Files API: its client and mock, the upload hook and the
  //     shared upload component. Anything else that sends a File or Blob, builds FormData or opens an
  //     XMLHttpRequest is a second upload path that skips presigned URLs, limits and scanning.
  if (!isFilesLayer(f)) {
    for (const m of text.matchAll(/\bnew FormData\b|\bXMLHttpRequest\b/g)) report(f, m.index, 'FormData or XMLHttpRequest outside the files layer (upload through components/shared/file-upload)');
    for (const m of text.matchAll(/\bfetch\s*\(/g)) {
      const call = text.slice(m.index, m.index + 400);
      if (/method:\s*['"`](PUT|POST)['"`]/.test(call) && /body:\s*(new (File|Blob)\b|[\w.]*(file|blob|File|Blob)\w*)/.test(call)) report(f, m.index, 'fetch PUT/POST with a File or Blob body outside the files layer (upload through components/shared/file-upload)');
    }
  }

  const hits = [...text.matchAll(PALETTE), ...[...text.matchAll(FIXED_WIDTH)].filter((m) => !isRail(text, m))];
  if (hits.length) counts[f.rel] = hits.length;
  const allowed = baseline[f.rel] ?? 0;
  if (hits.length > allowed) {
    const first = hits.sort((a, b) => a.index - b.index)[0];
    report(f, first.index, `${hits.length} raw palette classes or fixed px widths, ${allowed} allowed (use the success, warning and destructive tokens and fluid widths)`);
  } else if (hits.length < allowed) notes.push(`${f.rel}: ${hits.length} of ${allowed} allowed; run with --write-baseline to lock the drop in`);

  // 11. No ad-hoc state switches from copied projects.
  for (const m of text.matchAll(/usePageState|PageStateGate|[?&]state=(empty|loading|error)/g)) report(f, m.index, 'copied ?state= switch (use React Query states and ?mock=)');
}

// 12. Every routed page reaches PageLayout or RecordLayout: in its own file, or through the components it imports and
// renders, followed up to three levels (FilePage and TaskPage render PageLayout themselves; a preview channel page
// renders ChannelTypePageLayout, which renders ChannelsPageLayout, which renders PageLayout). A name never passes on its
// own: the file that renders the layout has to be found. Named here instead are
// only the full-height shells that are not record pages: the chat (ChatLayout, ChatWorkspace, the embedded chat and
// its sample host) and the workflow editor. A new name on that list needs a Standards-exception trailer the
// orchestrator approves (delivery rubric: checks are met, never widened).
// A page that only calls next/navigation `redirect()` and renders no JSX (a retired route) has nothing to lay out.
const redirectOnly = (text) => /\bredirect\(/.test(text) && !/<\/|\/>/.test(text);
// Sign-in pages under app/(auth) are laid out by app/(auth)/layout.tsx (centred card, no sidebar), not PageLayout.
const authShell = (rel) => rel.startsWith('src/app/(auth)/');
const LAYOUT = /<(PageLayout|RecordLayout)\b/;
const FULL_HEIGHT_SHELL = /<(ChatLayout|ChatWorkspace|EmbedChat|SampleIntranet|WorkflowEditor)\b/;
/** The file of the component `name` that `f` imports, as {abs, text}, or null when it is not imported from src. */
function importedSource(f, name) {
  const m = f.text.match(new RegExp(`import\\s+(?:type\\s+)?(?:\\{[^}]*\\b${name}\\b[^}]*\\}|${name})\\s+from\\s+'([^']+)'`));
  if (!m) return null;
  const spec = m[1];
  const base = spec.startsWith('@/') ? join(src, spec.slice(2)) : spec.startsWith('.') ? join(f.abs, '..', spec) : null;
  if (!base) return null;
  for (const candidate of [`${base}.tsx`, `${base}.ts`, join(base, 'index.tsx')]) if (existsSync(candidate)) return { abs: candidate, text: readFileSync(candidate, 'utf8') };
  return null;
}
const reachesLayout = (f, depth = 0) =>
  LAYOUT.test(f.text) ||
  FULL_HEIGHT_SHELL.test(f.text) ||
  (depth < 3 &&
    [...new Set([...f.text.matchAll(/<([A-Z]\w+)/g)].map((m) => m[1]))].some((name) => {
      const source = importedSource(f, name);
      return !!source && source.abs !== f.abs && reachesLayout(source, depth + 1);
    }));
for (const f of files.filter((x) => /^src\/app\/.*page\.tsx$/.test(x.rel) && !redirectOnly(x.text) && !authShell(x.rel))) {
  if (!reachesLayout(f)) report(f, 0, 'page that never reaches PageLayout or RecordLayout (in the page or up to three components down)');
}

// 16. One component per job (16, not 15: services' check_standards owns rule 15, the database drivers) (docs/plans/ops-ai console reuse sweep, 2026-10-18): a table is the data table, a status is
//     a badge from components/status-badges.tsx, and the chat composer and message renderers live in components/chat.
//     The files that broke this when the rule came in are listed per rule in reuse-baseline.json. The list may only
//     shrink: a file not listed fails, and a listed file that no longer breaks the rule fails until it is taken off
//     (`--write-baseline` takes it off and never adds one).
const REUSE = {
  rawTable: {
    what: 'a raw <Table> outside the data table (use data-table-with-views, or DataTable for a fixed list)',
    owns: (rel) => rel.startsWith('src/components/ui/') || /^src\/components\/data-table[\w-]*\.tsx$/.test(rel),
    hit: (text) => text.search(/from ['"]@\/components\/ui\/table['"]/),
  },
  statusBadge: {
    what: 'a local status badge (add the status to components/status-badges.tsx and use it)',
    owns: (rel) => rel === 'src/components/status-badges.tsx',
    hit: (text) => text.search(/\b(?:function|const)\s+[A-Z]\w*StatusBadge\b/),
  },
  chatRenderer: {
    what: 'a chat composer or message renderer outside components/chat (use Composer and MessageView)',
    owns: (rel) => rel.startsWith('src/components/chat/'),
    hit: (text) => text.search(/\b(?:function|const)\s+[A-Z]\w*(?:Composer|MessageView|MessageList|Bubble|ToolCall|Chat(?:Response|Prompt|Conversation|Thinking))\b/),
  },
};
const reusePath = join(root, 'scripts/reuse-baseline.json');
const reuseBaseline = existsSync(reusePath) ? JSON.parse(readFileSync(reusePath, 'utf8')) : {};
const reuseNow = Object.fromEntries(Object.keys(REUSE).map((k) => [k, []]));
for (const f of files) {
  if (f.rel.endsWith('.test.ts')) continue;
  for (const [key, rule] of Object.entries(REUSE)) {
    if (rule.owns(f.rel)) continue;
    const at = rule.hit(f.text);
    if (at < 0) continue;
    reuseNow[key].push(f.rel);
    if (!(reuseBaseline[key] ?? []).includes(f.rel)) report(f, at, rule.what);
  }
}
const reuseWrite = process.argv.includes('--write-baseline');
for (const [key, listed] of Object.entries(reuseBaseline))
  for (const rel of listed)
    if (!reuseNow[key]?.includes(rel) && !reuseWrite) violations.push(`${rel}: listed under ${key} in reuse-baseline.json but no longer breaks it; take it off (run with --write-baseline)`);
if (reuseWrite) {
  const kept = Object.fromEntries(Object.keys(REUSE).map((k) => [k, (reuseBaseline[k] ?? []).filter((rel) => reuseNow[k].includes(rel)).sort()]));
  writeFileSync(reusePath, JSON.stringify(kept, null, 2) + '\n');
}

if (process.argv.includes('--write-baseline')) {
  // Recording the counts is the point of this mode, so rule 14 does not fail it.
  for (let i = violations.length - 1; i >= 0; i--) if (violations[i].includes('raw palette classes')) violations.splice(i, 1);
  writeFileSync(baselinePath, JSON.stringify(Object.fromEntries(Object.entries(counts).sort()), null, 2) + '\n');
  console.log(`check-standards: baseline written, ${Object.keys(counts).length} files, ${Object.values(counts).reduce((a, b) => a + b, 0)} uses`);
}
for (const f of Object.keys(baseline)) if (!files.some((x) => x.rel === f)) notes.push(`${f}: listed in palette-baseline.json but gone; run with --write-baseline`);
if (notes.length) console.log(notes.map((n) => `  note: ${n}`).join('\n'));

if (violations.length) {
  console.error(`check-standards: ${violations.length} violation(s)\n` + violations.map((v) => `  ${v}`).join('\n'));
  process.exit(1);
}
console.log(`check-standards: ${files.length} files clean`);
