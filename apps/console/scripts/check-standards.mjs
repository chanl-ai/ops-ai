#!/usr/bin/env node
// Enforces the grep-provable rules in CLAUDE.md. Exits 1 with file:line for every violation.
import { readdirSync, readFileSync, statSync } from 'node:fs';
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
const lineOf = (text, index) => text.slice(0, index).split('\n').length;
const report = (f, index, rule) => violations.push(`${f.rel}:${lineOf(f.text, index)}  ${rule}`);

const inDir = (f, d) => f.rel.startsWith(`src/${d}/`);
const isUi = (f) => inDir(f, 'components/ui');

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

  // 4. Only the API entry reads env.
  if (f.rel !== 'src/lib/api/index.ts') {
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

  // 11. No ad-hoc state switches from copied projects.
  for (const m of text.matchAll(/usePageState|PageStateGate|[?&]state=(empty|loading|error)/g)) report(f, m.index, 'copied ?state= switch (use React Query states and ?mock=)');
}

// 12. Every routed page has a recognised header or shell. ChatWorkspace renders ChatLayout, the full-height chat shell.
for (const f of files.filter((x) => /^src\/app\/.*page\.tsx$/.test(x.rel))) {
  if (!/PageLayout|ReviewsPageLayout|WorkflowEditor|<AgentSettingsPage|KbPageLayout|SourcePageLayout|ChatLayout|<ChatWorkspace/.test(f.text)) report(f, 0, 'page without PageLayout (or a documented shell)');
}

if (violations.length) {
  console.error(`check-standards: ${violations.length} violation(s)\n` + violations.map((v) => `  ${v}`).join('\n'));
  process.exit(1);
}
console.log(`check-standards: ${files.length} files clean`);
