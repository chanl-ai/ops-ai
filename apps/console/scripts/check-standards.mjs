#!/usr/bin/env node
// Enforces the grep-provable rules in CLAUDE.md. Exits 1 with file:line for every violation.
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { join, relative } from 'node:path';

const root = new URL('..', import.meta.url).pathname;
const src = join(root, 'src');

// One read in a try/catch: a check for the file followed by a read is a race, and a missing file is an answer here.
function readOrNull(path) {
  try {
    return readFileSync(path, 'utf8');
  } catch (err) {
    if (err.code === 'ENOENT') return null;
    throw err;
  }
}
function readJson(path, missing = {}) {
  const text = readOrNull(path);
  return text === null ? missing : JSON.parse(text);
}

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
const baseline = readJson(baselinePath);
const counts = {};
// Rule 18: an identifier drawn as JSX text (`{step.nodeId}`, `{c.operation}`, `{error.tool}`), or the operation badge.
const SELF_WORDED = /(?<![=\w$])\{\s*[\w.?]+\.(?:nodeId|operation|tool)\s*\}|<OperationBadge\b/g;
const SELF_WORDED_OK = new Set([
  'components/workflows/run-journal/step-sheet.tsx',
  'components/tools/tool-calls-view.tsx',
  'components/logs/tool-call-sheet.tsx',
  'components/tools/executions-table.tsx',
  'components/tools/versions-panel.tsx',
  'components/secrets/secrets-panel.tsx',
]);
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

  // 17. Reads go through hooks/team-query.ts: a raw React Query read neither waits for the person's team nor
  //     keys its answer by team, so it can ask for a team they do not hold or show one team's data in another.
  if (f.rel !== 'src/hooks/team-query.ts') {
    for (const m of text.matchAll(/import\s*\{[^}]*\b(useQuery|useInfiniteQuery|useQueries|useSuspenseQuery|useSuspenseInfiniteQuery|useSuspenseQueries)\b[^}]*\}\s*from\s*['"]@tanstack\/react-query['"]/g))
      report(f, m.index, `imports ${m[1]} from @tanstack/react-query (use useTeamQuery, useTeamInfiniteQuery or useSessionQuery from @/hooks/team-query)`);
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

  // 18. Steps are worded once, by the API (agents-service run_story.lines): a page that tells people what a run
  //     did draws those lines (StoryFeed) and never prints a step's node id, its operation or a call's tool name as
  //     text. Builder and audit views show what was built or called, by path. Its reach is console TSX only; rule 19
  //     covers task files that word a call's input keys.
  if (/^src\/(app|components)\/.*\.tsx$/.test(f.rel) && !SELF_WORDED_OK.has(f.rel.slice(4))) {
    for (const m of text.matchAll(SELF_WORDED)) report(f, m.index, 'prints a step or tool name itself (draw the API\'s story lines through StoryFeed)');
  }

  // 19. A Human Task never words a call's input keys itself: the API sends each write's fields as the operation
  //     labels them (write_preview.fields from describe_call). A camelCase-splitting humaniser in a task file is that
  //     wording done in the browser.
  if (/^src\/components\/tasks\/.*\.tsx?$/.test(f.rel)) {
    for (const m of text.matchAll(/\.replace\(\/\(\[a-z\]\)\(\[A-Z\]\)\/g/g)) report(f, m.index, "words a call's input keys itself (draw the API's write_preview.fields)");
  }

  // 20. No mock pages in the console: a design mock is HTML in the docs (:3009), never a console route, so what
  //     is reviewed is what ships.
  if (/^src\/app\/preview\//.test(f.rel)) report(f, 0, 'is a preview page (draw design mocks as HTML in the docs; ship the real page)');

  // 21. One way to decide a Human Task: the decide forms and the decision route are used only by the shared
  //     TaskDecision, the queue's panel, the decider and chat's task card, so a new surface cannot drift from them.
  if (!/^src\/components\/reviews\/(task-decision|decision-panel|use-review-decider|option-decision-form|review-detail|model-validation)\.tsx$|^src\/components\/chat\/record-cards\.tsx$|^src\/hooks\/queries\.ts$/.test(f.rel))
    for (const m of text.matchAll(/import\s*\{[^}]*\b(OptionDecisionForm|ReviewDecisionForm|ModelValidationDecisionForm|useDecideReview)\b[^}]*\}\s*from/g)) report(f, m.index, `imports ${m[1]} (decide through components/reviews/task-decision.tsx)`);

  // 22. A paged list that adds rows in place shows each new row right after the add: paged by name or narrowed by a
  //     search, the new row would sit on another page. The page passes `useCreatedRows` to the table as `created`. An
  //     add is a create, add, invite or import hook, a dialog named for one (the hook may live in the dialog), or an
  //     onAdded, onCreated or onSaved prop. A list that opens the new item's own page instead is listed with its reason.
  const OPENS_THE_NEW_ITEM = {
    'src/app/build/agents/page.tsx': 'opens the new agent',
    'src/app/build/skills/page.tsx': 'opens the new skill',
    'src/app/data/tools/custom/page.tsx': 'opens the new module',
    'src/app/build/guardrails/page.tsx': 'opens the new guardrail',
    'src/app/data/knowledge/page.tsx': 'opens the new knowledge base',
    'src/app/build/widgets/page.tsx': 'opens the new widget',
    'src/app/data/document-types/page.tsx': 'opens the new document type',
    'src/app/govern/access/roles/page.tsx': 'opens the new role',
    // Not yet: the invite answers with links, not the invited members' rows (platform-service), so there is no row to show.
    'src/components/access/members-panel.tsx': 'invite returns links, not member rows',
    // Not yet: an upload returns ids, and a file is listed once it has been scanned, so there is no row to show.
    'src/app/data/files/page.tsx': 'upload returns ids; a file is listed once scanned',
  };
  const adds = [...text.matchAll(/\buse(?:Create|Add|Invite|Import)(?!Param\b)[A-Z]\w*\(|<\w*(?:Add|Create|New|Invite|Import)\w*Dialog\b|\bon(?:Added|Created|Saved)=/g)];
  if (adds.length && /<DataTableWithViews\b/.test(text) && /\buseListParams[<(]/.test(text) && !/\bcreated=\{/.test(text) && !(f.rel in OPENS_THE_NEW_ITEM))
    report(f, adds[0].index, 'adds rows to a paged list without showing the new row (pass useCreatedRows to the table as `created`)');
  //     The table lets a created row go when a query hook's write names it, so a list wired with `created` removes,
  //     revokes or archives through a query hook; a call straight to the API would leave the removed row on screen.
  if (/\bcreated=\{/.test(text))
    for (const m of text.matchAll(/\bapi\.[\w.]+\.(remove|revoke|archive|bulkRemove|delete)\(/g))
      report(f, m.index, `calls api.….${m[1]} outside a query hook, so the table cannot let a removed new row go (use the area's mutation hook)`);

  // 11. No ad-hoc state switches from copied projects.
  for (const m of text.matchAll(/usePageState|PageStateGate|[?&]state=(empty|loading|error)/g)) report(f, m.index, 'copied ?state= switch (use React Query states and ?mock=)');
}

// 12. Every routed page reaches PageLayout or RecordLayout: in its own file, or through the components it imports and
// renders, followed up to three levels (FilePage and TaskPage render PageLayout themselves; a preview channel page
// renders ChannelTypePageLayout, which renders ChannelsPageLayout, which renders PageLayout). A name never passes on its
// own: the file that renders the layout has to be found. Named here instead are
// only the full-height shells that are not record pages: the chat (ChatLayout, ChatWorkspace, the embedded chat and
// its sample host) and the workflow editor. A new name on that list needs a Standards-exception trailer a
// maintainer approves.
// A page that only calls next/navigation `redirect()` and renders no JSX (a retired route) has nothing to lay out.
const redirectOnly = (text) => /\bredirect\(/.test(text) && !/<\/|\/>/.test(text);
// Sign-in pages under app/(auth) are laid out by app/(auth)/layout.tsx (centred card, no sidebar), not PageLayout.
// The sign-in pages, and the sign-in window's pages under connections/, draw one card alone as the shell renders them.
const authShell = (rel) => rel.startsWith('src/app/(auth)/') || rel.startsWith('src/app/connections/');
const LAYOUT = /<(PageLayout|RecordLayout)\b/;
const FULL_HEIGHT_SHELL = /<(ChatLayout|ChatWorkspace|EmbedChat|SampleIntranet|WorkflowEditor)\b/;
/** The file of the component `name` that `f` imports, as {abs, text}, or null when it is not imported from src. */
function importedSource(f, name) {
  const m = f.text.match(new RegExp(`import\\s+(?:type\\s+)?(?:\\{[^}]*\\b${name}\\b[^}]*\\}|${name})\\s+from\\s+'([^']+)'`));
  if (!m) return null;
  const spec = m[1];
  const base = spec.startsWith('@/') ? join(src, spec.slice(2)) : spec.startsWith('.') ? join(f.abs, '..', spec) : null;
  if (!base) return null;
  for (const candidate of [`${base}.tsx`, `${base}.ts`, join(base, 'index.tsx')]) {
    const text = readOrNull(candidate);
    if (text !== null) return { abs: candidate, text };
  }
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
// 19. The outside-assistant MCP address is behind the install flag mcp_gateway: a file that links to the MCP
//     channel or names the MCP URL on screen (app/ and components/) reads the flag (hooks/flag-queries), so a new entry point cannot show it on an install
//     that has it off. Exempt: the mock's data, the retired /connect redirect (it lands on the channel page, which checks
//     the flag), and the MCP channel's own panels (app/deployments/_parts/mcp-tab.tsx, components/deployments/mcp/),
//     which render only inside that page.
const mcpExempt = (rel) => rel.startsWith('src/lib/api/mock/') || rel.startsWith('src/components/deployments/mcp/') || ['src/app/connect/page.tsx', 'src/app/deployments/_parts/mcp-tab.tsx'].includes(rel);
for (const f of files.filter((x) => /^src\/(app|components)\//.test(x.rel) && !mcpExempt(x.rel))) {
  const hit = /['"`]\/channels\/mcp['"`]|MCP URL/.exec(f.text);
  if (hit && !f.text.includes("'mcp_gateway'")) report(f, hit.index, 'links to the MCP address without reading the mcp_gateway flag');
}
// A tab's page that draws nothing (`return null`) is laid out by the layout.tsx above it, which is where a record page keeps
// state across its tabs; that layout has to reach the layout itself.
const laidOutByLayout = (f) => {
  if (!/return null;/.test(f.text) || /<\/|\/>/.test(f.text)) return false;
  for (let dir = join(f.abs, '..'); dir.startsWith(join(src, 'app')) && dir !== join(src, 'app'); dir = join(dir, '..')) {
    const text = readOrNull(join(dir, 'layout.tsx'));
    if (text !== null) return reachesLayout({ abs: join(dir, 'layout.tsx'), text });
  }
  return false;
};
for (const f of files.filter((x) => /^src\/app\/.*page\.tsx$/.test(x.rel) && !redirectOnly(x.text) && !authShell(x.rel) && !laidOutByLayout(x))) {
  if (!reachesLayout(f)) report(f, 0, 'page that never reaches PageLayout or RecordLayout (in the page or up to three components down)');
}

// 16. One component per job (16, not 15: services' check_standards owns rule 15, the database drivers): a table is the data table, a status is
//     a badge from components/status-badges.tsx, the chat composer and message renderers live in components/chat, and
//     a link to an app page comes from lib/app-links.
//     The files that broke this when the rule came in are listed per rule in reuse-baseline.json. The list may only
//     shrink: a file not listed fails, and a listed file that no longer breaks the rule fails until it is taken off
//     (`--write-baseline` takes it off and never adds one).
function nameRuleAt(text) {
  return text.search(/\[\^a-z0-9\]|!?[\w.]+\.trim\(\)\s*\?\s*undefined\s*:\s*['"`]Name |if \(!\s*[\w.]*[nN]ame\.trim\(\)\)/);
}
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
  appLink: {
    what: 'an app page link built by hand (use appPageHref from lib/app-links)',
    owns: (rel) => rel === 'src/lib/app-links.ts',
    hit: (text) => text.search(/`\/integrations\/(?:apps\/)?\$\{/),
  },
  // A list someone picks from is searched on the server and pages as it scrolls, so a team with thousands of items can
  // find any of them: EntityPicker or SearchSelect over an /options source (hooks/options-queries.ts), or CaretMenu
  // for a list opened at the caret. A picker built on Command elsewhere, or a list filtered in the browser, finds only
  // what the browser happened to load.
  picker: {
    what: 'a picker built on Command outside the shared ones (use EntityPicker or SearchSelect over an /options source, or CaretMenu at the caret)',
    // The step sheet's field picker lists one workflow's earlier steps, which the sample route returns whole and grouped
    // by step, so there is nothing more on the server to search (editors design, review S2).
    owns: (rel) => rel.startsWith('src/components/ui/') || ['src/components/shared/entity-picker.tsx', 'src/components/shared/search-select.tsx', 'src/components/shared/caret-menu.tsx', 'src/components/workflows/definition-editor/field-picker.tsx'].includes(rel),
    hit: (text) => text.search(/from ['"]@\/components\/ui\/command['"]/),
  },
  listFilter: {
    what: 'a list searched in the browser (search on the server: useServerList in hooks/server-list.ts, or an /options source through hooks/options-queries.ts)',
    owns: (rel) => rel.startsWith('src/lib/api/') || rel === 'src/hooks/options-queries.ts' || rel === 'src/hooks/server-list.ts',
    hit: (text) => listFilterHit(text),
  },
  // A name or title a person types is checked by lib/validation/names (the kit's rules: one line, not invisible, the
  // server's sentence) and a slug is made by its slugify, which keeps non-Latin names distinct.
  nameRule: {
    what: 'a slug or name check written by hand (use slugify or nameError from lib/validation/names)',
    owns: (rel) => rel === 'src/lib/validation/names.ts',
    hit: nameRuleAt,
  },
  dialogColumns: {
    what: 'a form laid out in columns inside a dialog (dialog forms are one column)',
    owns: (rel) => rel.startsWith('src/components/ui/'),
    hit: (text) => (text.includes('<DialogShell') ? text.search(/(?:sm:|md:|lg:|xl:)?grid-cols-[2-9]/) : -1),
  },
};
// A search typed in the browser run over rows already fetched: a `.filter` that lower-cases and tests `includes`, a
// `.filter` testing `includes` of the search box's value, or a predicate that compares a lower-cased search with
// lower-cased fields (a `match(q, row)` helper the filter calls).
function listFilterHit(text) {
  const SEARCH = String.raw`(?:q|query|search|term|needle|\w+Query|\w+Search)`;
  const forms = [
    /\.filter\([^;]*?\.toLowerCase\(\)\.includes\(/,
    new RegExp(String.raw`\.filter\([^;]*?\.includes\(${SEARCH}(?:\.trim\(\))?\)`),
    new RegExp(String.raw`=>[^;]*?\.toLowerCase\(\)\.includes\(${SEARCH}\.toLowerCase\(\)\)`),
  ];
  const at = forms.map((re) => text.search(re)).filter((i) => i >= 0);
  return at.length ? Math.min(...at) : -1;
}
const reusePath = join(root, 'scripts/reuse-baseline.json');
const reuseBaseline = readJson(reusePath);
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
// 23. Lists are asked for the way the screen shows them (docs/architecture/standards/console-and-sdk.md UI1, and
//     data-access.md DA5). Three shapes do the server's work in the browser, each held per file to its count in
//     data-baseline.json: a file may lower its count, never raise it, and a file not listed may have none.
//     `--write-baseline` records a drop.
//       pageSize   a page size above 50, which loads a table to show part of it; only the options hooks, which page
//                  as a picker scrolls, are outside the rule
//       aggregate  `.reduce(` or `.filter(...).length` in a page or component: a sum or a count the API returns
//       fetch      `fetch(` outside lib/api, which skips the contract, the team header and the error envelope
// `pageSize: 200`, `pageSize: BIG` where the same file says `const BIG = 200`, and `pageSize: PAGE_ALL` imported from
// elsewhere (a constant held in another file is read as over the limit, since this file cannot show its value). A
// lower-case name is read when the file assigns it a number or arithmetic on numbers; one passed along as a parameter,
// state or a call's result says nothing about its size, so this reads the literal form only.
function pageSizeHits(text) {
  // A name assigned a number or arithmetic on numbers (`const size = 100 * 2`, `let n = 500`) stands for its value.
  const known = new Map();
  for (const m of text.matchAll(/\b(?:const|let)\s+([A-Za-z_$][\w$]*)\s*(?::\s*number\s*)?=\s*([\d\s*+\-/()._]+?)\s*[;,\n]/g)) {
    if (!/\d/.test(m[2])) continue;
    try {
      const value = Number(Function(`"use strict"; return (${m[2].replace(/_/g, '')});`)());
      if (Number.isFinite(value)) known.set(m[1], value);
    } catch {
      // not arithmetic (an arrow function's parameters, say): the name stays unknown
    }
  }
  return [...text.matchAll(/\bpageSize\s*[:=]\s*([A-Za-z_$][\w$]*|\d+)\b(?!\s*[.(\[])/g)].filter((m) => {
    const v = m[1];
    if (/^\d+$/.test(v)) return Number(v) > 50;
    if (known.has(v)) return known.get(v) > 50;
    return /^[A-Z][A-Z0-9_]*$/.test(v);
  });
}
const DATA = {
  pageSize: {
    what: 'a page size above 50 (ask for the page the screen shows; a picker pages through hooks/options-queries.ts)',
    reads: (rel) => rel !== 'src/hooks/options-queries.ts' && !rel.startsWith('src/lib/api/mock/'),
    hits: pageSizeHits,
  },
  aggregate: {
    what: 'a sum or count worked out in the browser (the API returns it: a facet, a count or a field on the row)',
    reads: (rel) => /^src\/(app|components)\//.test(rel) && !rel.startsWith('src/components/ui/'),
    hits: (text) => [...text.matchAll(/\.reduce\(|\.filter\((?:[^()]|\([^()]*\))*\)\.length\b/g)],
  },
  fetch: {
    what: 'fetch( outside lib/api (call the API contract through a hook)',
    reads: (rel) => !rel.startsWith('src/lib/api/'),
    hits: (text) => [...text.matchAll(/(?<![\w.$])fetch\s*\(/g)],
  },
};

// 24-28. Record-page header order, button labels, control sizes and save wording (docs/console/standards.md).
// Counts for labels and sizes that predate the rules sit in rules-baseline.json; a file may lower its count, never raise it.
/** Every `<Tag ...>` opening of the named components, with its attribute text and the text up to its closing tag. */
function openings(text, tags) {
  const out = [];
  const re = new RegExp(`<(${tags.join('|')})(?=[\\s/>])`, 'g');
  for (const m of text.matchAll(re)) {
    let i = m.index + m[0].length;
    let depth = 0;
    let quote = null;
    for (; i < text.length; i++) {
      const c = text[i];
      if (quote) {
        if (c === quote) quote = null;
      } else if (depth === 0 && (c === '"' || c === "'")) quote = c;
      else if (c === '{') depth++;
      else if (c === '}') depth--;
      else if (c === '>' && depth === 0 && text[i - 1] !== '=') break;
    }
    const attrs = text.slice(m.index + m[0].length, i);
    const selfClosed = attrs.trimEnd().endsWith('/');
    let inner = '';
    if (!selfClosed) {
      const end = text.indexOf(`</${m[1]}>`, i);
      inner = end < 0 ? '' : text.slice(i + 1, end);
    }
    out.push({ index: m.index, tag: m[1], attrs, inner });
  }
  return out;
}
const LABEL_TAGS = ['Button', 'LoadingButton', 'DropdownMenuItem', 'AlertDialogAction'];
/** Rule 25: literal label text of three or more words. */
function labelHits(text) {
  const hits = [];
  for (const o of openings(text, LABEL_TAGS)) {
    const literal = o.inner.replace(/\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}/g, ' ').replace(/<[^>]*>/g, ' ').replace(/[·…]/g, ' ').trim();
    if (literal.split(/\s+/).filter(Boolean).length >= 3) hits.push({ index: o.index });
  }
  for (const m of text.matchAll(/\b(?:addLabel|actionLabel)="([^"]+)"/g)) if (m[1].trim().split(/\s+/).length >= 3) hits.push({ index: m.index });
  return hits;
}
const SIZE_TAGS = ['Button', 'Input', 'SelectTrigger', 'Switch', 'Checkbox', 'ToggleGroupItem'];
/** Rule 26: a size class on a control, or a link button with its padding removed. */
function sizeHits(text) {
  const hits = [];
  for (const o of openings(text, SIZE_TAGS)) {
    const cls = /className=(?:"([^"]*)"|\{`([^`]*)`\}|\{'([^']*)'\})/.exec(o.attrs);
    const c = cls ? cls[1] ?? cls[2] ?? cls[3] ?? '' : '';
    if (/(^|\s)(?:h|size|px|py)-\S+|(^|\s)text-xs(\s|$)/.test(c)) hits.push({ index: o.index });
    else if (o.tag === 'Button' && /variant="link"/.test(o.attrs) && /(^|\s)p-0(\s|$)/.test(c)) hits.push({ index: o.index });
  }
  return hits;
}
const RECORD_PAGE = /^src\/app\/build\/(agents|skills|workflows\/definitions)\/\[id\]\/page\.tsx$/;
/** Rule 24: a record page gives its header actions through RecordActions (fixed order: state, Save, Test, primary, menu). */
function headerHits(rel, text) {
  if (!RECORD_PAGE.test(rel) || /<RecordActions\b/.test(text)) return [];
  return openings(text, ['PageLayout']).filter((o) => /(?<![\w?])actions=\{(?!\s*\w+\s*\})/.test(o.attrs)).map((o) => ({ index: o.index }));
}
/** Rule 27: a bordered card with a heading is `Section` (one header, one padding scale), not a hand-built `<section>`. */
function sectionHits(text) {
  return openings(text, ['section'])
    .filter((o) => {
      const cls = /className=(?:"([^"]*)"|\{`([^`]*)`\}|\{'([^']*)'\})/.exec(o.attrs);
      const c = cls ? cls[1] ?? cls[2] ?? cls[3] ?? '' : '';
      return /(^|\s)rounded-lg(\s|$)/.test(c) && /(^|\s)border(\s|$)/.test(c) && /(^|\s)bg-card(\s|$)/.test(c);
    })
    .map((o) => ({ index: o.index }));
}
/** Rule 28: one save wording, from SaveState. */
function saveWordHits(text) {
  return [...text.matchAll(/Saving soon|Draft v[^`'"\n]*saved/g)].map((m) => ({ index: m.index }));
}
if (process.argv.includes('--self-test')) {
  // Each plant is one way a page size above 50 gets past a digits-only reading; the last three must stay clean.
  const plants = [
    ['useRows({ pageSize: 200 })', 1],
    ['const BIG = 200;\nuseRows({ pageSize: BIG })', 1],
    ['useRows({ pageSize: PAGE_ALL })', 1],
    ['const SMALL = 20;\nuseRows({ pageSize: SMALL })', 0],
    ['useRows({ pageSize: params.pageSize })', 0],
    ['useRows({ pageSize: 25 })', 0],
    ['const size = 100 * 2;\nuseRows({ pageSize: size })', 1],
    ['let size = 500;\nuseRows({ pageSize: size })', 1],
    ['const rows: number = 4 * 5;\nuseRows({ pageSize: rows })', 0],
  ];
  const rules = [
    ['label: three words', labelHits('<Button onClick={() => go()}>Generate with the builder</Button>'), 1],
    ['label: two words with an icon and a count', labelHits('<Button><Plus /> Add skill {n}</Button>'), 0],
    ['label: addLabel of three words', labelHits('<Picker addLabel="Choose a workflow" />'), 1],
    ['size: h-7 on a button', sizeHits('<Button size="sm" className="h-7">Go</Button>'), 1],
    ['size: link with p-0', sizeHits('<Button variant="link" className="p-0">Go</Button>'), 1],
    ['size: the size prop alone', sizeHits('<Button size="sm" className="w-full">Go</Button>'), 0],
    ['header: raw actions on a record page', headerHits('src/app/build/agents/[id]/page.tsx', '<PageLayout title="a" actions={<Button>Go</Button>}>'), 1],
    ['header: RecordActions', headerHits('src/app/build/agents/[id]/page.tsx', '<PageLayout title="a" actions={<RecordActions />}>'), 0],
    ['save: Saving soon', saveWordHits('<span>Saving soon…</span>'), 1],
    ['list: filter lower-casing each row', listFilterHit('const shown = rows.filter((r) => r.name.toLowerCase().includes(q));') < 0 ? [] : [1], 1],
    ['list: filter on the search box', listFilterHit('const shown = data.filter((r) => r.title.includes(search));') < 0 ? [] : [1], 1],
    ['list: a match helper', listFilterHit('const match = (q, r) => !q || r.title.toLowerCase().includes(q.toLowerCase());') < 0 ? [] : [1], 1],
    ['list: server rows from useServerList', listFilterHit('const { rows } = useServerList(key, fetchPage, { search });') < 0 ? [] : [1], 0],
    ['list: a filter by id, not a search', listFilterHit('const kept = rows.filter((r) => wanted.includes(r.id));') < 0 ? [] : [1], 0],
    ['section: a hand-built bordered card', sectionHits('<section className="flex flex-col rounded-lg border bg-card">x</section>'), 1],
    ['section: a plain grouping section', sectionHits('<section className="flex flex-col gap-3">x</section>'), 0],
    ['name: a slug regex by hand', [nameRuleAt("const s = n.toLowerCase().replace(/[^a-z0-9]+/g, '-');")].filter((i) => i >= 0), 1],
    ['name: a blank check by hand', [nameRuleAt("const e = { name: name.trim() ? undefined : 'Name the role.' };")].filter((i) => i >= 0), 1],
    ['name: nameError', [nameRuleAt("const e = { name: nameError(name, 'Name the role.') };")].filter((i) => i >= 0), 0],
  ];
  const badRules = rules.filter(([, hits, want]) => hits.length !== want);
  for (const [name, hits, want] of badRules) console.error(`self-test: ${name} gave ${hits.length}, want ${want}`);
  const failed = plants.filter(([text, want]) => pageSizeHits(text).length !== want);
  failed.push(...badRules.map(([name, , want]) => [name, want]));
  for (const [text, want] of failed) console.error(`self-test: ${JSON.stringify(text)} should give ${want} hit(s)`);
  console.log(failed.length ? 'check-standards self-test: FAILED' : `check-standards self-test: ${plants.length + rules.length} plants behave`);
  process.exit(failed.length ? 1 : 0);
}
const dataPath = join(root, 'scripts/data-baseline.json');
const dataBaseline = readJson(dataPath);
const dataNow = Object.fromEntries(Object.keys(DATA).map((k) => [k, {}]));
for (const f of files) {
  if (/\.test\.tsx?$/.test(f.rel)) continue;
  for (const [key, rule] of Object.entries(DATA)) {
    if (!rule.reads(f.rel)) continue;
    const hits = rule.hits(f.text);
    if (hits.length) dataNow[key][f.rel] = hits.length;
    const allowed = dataBaseline[key]?.[f.rel] ?? 0;
    if (hits.length > allowed) report(f, hits[allowed].index, `${rule.what}: ${hits.length} here, ${allowed} allowed`);
    else if (hits.length < allowed) notes.push(`${f.rel}: ${key} ${hits.length} of ${allowed} allowed; run with --write-baseline to lock the drop in`);
  }
}
const reuseWrite = process.argv.includes('--write-baseline');
if (reuseWrite) {
  // Lowered only: a count never rises and a file is never added once the baseline exists.
  const first = readJson(dataPath, null) === null;
  const kept = Object.fromEntries(
    Object.keys(DATA).map((k) => [
      k,
      Object.fromEntries(
        Object.entries(dataNow[k])
          .map(([rel, n]) => [rel, first ? n : Math.min(n, dataBaseline[k]?.[rel] ?? 0)])
          .filter(([, n]) => n > 0)
          .sort(),
      ),
    ]),
  );
  writeFileSync(dataPath, JSON.stringify(kept, null, 2) + '\n');
}
for (const [key, listed] of Object.entries(reuseBaseline))
  for (const rel of listed)
    if (!reuseNow[key]?.includes(rel) && !reuseWrite) violations.push(`${rel}: listed under ${key} in reuse-baseline.json but no longer breaks it; take it off (run with --write-baseline)`);
if (reuseWrite) {
  const kept = Object.fromEntries(Object.keys(REUSE).map((k) => [k, (reuseBaseline[k] ?? []).filter((rel) => reuseNow[k].includes(rel)).sort()]));
  writeFileSync(reusePath, JSON.stringify(kept, null, 2) + '\n');
}

// Rules 24-28 over the files.
const rulesPath = join(root, 'scripts/rules-baseline.json');
const rulesBaseline = readJson(rulesPath);
const rulesNow = { labels: {}, sizes: {}, sections: {} };
for (const f of files) {
  if (!/^src\/(app|components)\/.*\.tsx$/.test(f.rel) || /^src\/components\/(ui|shared)\//.test(f.rel) || /\.test\./.test(f.rel)) continue;
  for (const h of headerHits(f.rel, f.text)) report(f, h.index, 'rule 24: a record page gives its header actions through RecordActions (save state, Save, Test, primary, menu)');
  for (const h of saveWordHits(f.text)) report(f, h.index, 'rule 28: save wording comes from SaveState (Saved, Unsaved, Saving…, Not saved)');
  for (const [key, hitsOf] of [['labels', labelHits], ['sizes', sizeHits], ['sections', sectionHits]]) {
    const hits = hitsOf(f.text);
    if (hits.length) rulesNow[key][f.rel] = hits.length;
    const allowed = rulesBaseline[key]?.[f.rel] ?? 0;
    if (hits.length > allowed && !process.argv.includes('--write-baseline'))
      report(f, hits[allowed].index, key === 'labels' ? 'rule 25: a button label is one or two words, verb first (put detail in a tooltip)' : key === 'sections' ? 'rule 27: a bordered card with a heading is Section (components/shared/surface), not a hand-built <section>' : 'rule 26: size comes from the size prop, not h-*, size-*, px-*, py-*, text-xs or a link button with p-0');
  }
}
if (process.argv.includes('--write-baseline')) {
  const kept = Object.fromEntries(Object.keys(rulesNow).map((k) => [k, Object.fromEntries(Object.entries(rulesNow[k]).map(([rel, n]) => [rel, Math.min(n, rulesBaseline[k]?.[rel] ?? n)]).sort())]));
  writeFileSync(rulesPath, JSON.stringify(kept, null, 2) + '\n');
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
