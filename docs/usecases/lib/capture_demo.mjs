// Takes the README's screenshots and clips from the demo team that scripts/demo/seed_demo_team.py makes (c-389).
//
//   node docs/usecases/lib/capture_demo.mjs --origin http://localhost:3016 --env .run/demo.env
//   node docs/usecases/lib/capture_demo.mjs --origin https://<install> --env <people env> --only chat,cases
//   node docs/usecases/lib/capture_demo.mjs --origin http://localhost:3016 --env .run/demo.env --clips --no-shots
//
// Signs in on the console as the team's lead (team.json's `lead`, with OPS_DEMO_PASSWORD from --env) in the use-case
// harness's headless Chromium, and saves under docs/media/: <name>-light.png and <name>-dark.png at 1280 x 800 for each
// screen, and <name>.gif for each clip (a Playwright video at 1280 x 800, cut to 960 wide at 10 frames a second by
// ffmpeg). Dark is the console's own `.dark` theme on <html>, as the use cases check it. The record ids each screen
// opens (a chat by title, a run by key, a case by subject) are read from the API. Every screen's text is checked for
// leftovers (test, foo, lorem, an error banner) and the capture stops on one, so a broken screen never lands in docs.
//
// Two clips act on the install: `agent` sends one chat turn to Dispute Desk on the fake model's committed rules and then
// deletes that chat, and `workflow` starts one test-mode run of the dispute workflow, which `task` then approves.
import { execFileSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

import { chromium, ROOT } from '@ops-ai/usecase-runner/harness';

const args = Object.fromEntries(
  process.argv.slice(2).reduce((pairs, arg, i, all) => (arg.startsWith('--') ? [...pairs, [arg.slice(2), all[i + 1] && !all[i + 1].startsWith('--') ? all[i + 1] : '1']] : pairs), []),
);
const ORIGIN = (args.origin ?? 'http://localhost:3016').replace(/\/$/, '');
const OUT = resolve(ROOT, args.out ?? 'docs/media');
const ONLY = args.only ? new Set(args.only.split(',')) : null;
const VIEW = { width: 1280, height: 800 };
const TEAM = JSON.parse(readFileSync(join(ROOT, 'scripts/demo/team.json'), 'utf8'));
const LOCAL_PORTS = { platform: 8710, agents: 8700 };
// Text that marks a screen as broken or as showing another run's leftovers: placeholder words, a failed render, and
// the names use cases and probes give their records. The console's own words ("Test", "Test connection") are not on
// it, so each image is still looked at before it is kept.
const LEFTOVER = /\b(foo|lorem|ipsum|undefined|NaN|probe|seed walk|uc-?\d{3})\b|Something went wrong|\bError:|IMAP intake [0-9a-f]{8}/i;

function readEnv(path) {
  const env = {};
  for (const line of readFileSync(path, 'utf8').split('\n')) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (m) env[m[1]] = m[2].replace(/^['"]|['"]$/g, '');
  }
  return env;
}

async function serviceUrls() {
  try {
    const r = await fetch(`${ORIGIN}/api/platform/v1/health`, { signal: AbortSignal.timeout(90_000) });
    if (r.ok) return { platform: `${ORIGIN}/api/platform`, agents: `${ORIGIN}/api/agents` };
  } catch {}
  return Object.fromEntries(Object.entries(LOCAL_PORTS).map(([s, p]) => [s, `http://127.0.0.1:${process.env[`OPS_${s.toUpperCase()}_PORT`] ?? p}`]));
}

const env = readEnv(resolve(args.env ?? '.run/demo.env'));
const lead = TEAM.people.find((p) => p.key === 'lead');
const approver = TEAM.people.find((p) => p.key === 'approver');
const urls = await serviceUrls();

async function api(service, path, { token, team, method = 'GET', body } = {}) {
  const headers = { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(team ? { 'X-Team-Id': team } : {}) };
  const r = await fetch(`${urls[service]}${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const json = r.headers.get('content-type')?.includes('json') ? await r.json() : null;
  if (!r.ok) throw new Error(`${method} ${path} answered ${r.status}: ${JSON.stringify(json).slice(0, 300)}`);
  return json?.data;
}
const rows = (page) => (Array.isArray(page) ? page : (page?.data ?? page?.items ?? []));

async function signIn(email) {
  const session = await api('platform', '/v1/auth/sign-in', { method: 'POST', body: { email, password: env.OPS_DEMO_PASSWORD } });
  return session.token;
}

const leadToken = await signIn(lead.email);
const teams = rows(await api('platform', '/v1/teams', { token: leadToken }));
const team = teams.find((t) => t.name === TEAM.team.name)?.id;
if (!team) throw new Error(`${lead.email} is not in ${TEAM.team.name}; run scripts/demo/seed_demo_team.py first`);
const as = { token: leadToken, team };

const chatId = async (title) => rows(await api('agents', `/chat/threads?search=${encodeURIComponent(title)}`, as)).find((t) => t.title === title)?.id;
const runOf = async (workflowId, match) => {
  for (const row of rows(await api('agents', `/v1/runs?workflowId=${workflowId}&pageSize=50`, as))) if (!match || match(row)) return row.id;
  return null;
};
const caseId = async (subject) =>
  rows(await api('agents', `/v1/cases?search=${encodeURIComponent(subject)}&pageSize=50`, as))
    .filter((c) => c.subject === subject && c.status !== 'closed')
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))[0]?.id;
const agentId = async (name) => rows(await api('agents', `/v1/agents?search=${encodeURIComponent(name)}&pageSize=50`, as)).find((a) => a.name === name && a.teamId === team)?.id;

const disputeChat = TEAM.chats.find((c) => c.key === 'dispute');
const ids = {
  chat: await chatId(disputeChat.title),
  levyChat: await chatId(TEAM.chats.find((c) => c.key === 'levy').title),
  // The seeded run, never a test-mode run a clip left: those are marked Test on the run page.
  credited: await runOf('card_dispute_intake', (r) => r.mode === 'live' && r.outcome === 'credited' && (r.input?.amount ?? '') === '482.10'),
  levyRun: await runOf('levy_debtor', (r) => r.mode === 'live' && r.status === 'waiting'),
  levyCase: await caseId('Levy notice: Marcus Bell (NS-2026-GN-01187)'),
  agent: await agentId('Dispute Desk'),
};

/** Each screen: the path it opens, text that shows it has loaded, and an optional step before the shot. */
const SCREENS = [
  { name: 'overview', path: '/', ready: 'Needs a decision' },
  { name: 'chat', path: () => `/chat/${ids.chat}`, ready: 'Sources' },
  { name: 'chat-levy', path: () => `/chat/${ids.levyChat}`, ready: 'Holds' },
  { name: 'agents', path: '/agents', ready: 'Dispute Desk', before: filterToTeam },
  { name: 'agent', path: () => `/agents/${ids.agent}`, ready: 'Instructions' },
  { name: 'workflow', path: '/workflows/card_dispute_intake', ready: 'Check the dispute' },
  // The run page draws the whole graph small inside one card; the shot is its steps at twice the scale, cut to 1280
  // wide, so every step's name and status reads.
  { name: 'run', path: () => `/workflows/runs/${ids.credited}`, ready: 'Graph', element: 'The workflow as this run met it' },
  { name: 'human-tasks', path: '/reviews', ready: 'Provisional credit' },
  { name: 'cases', path: '/cases', ready: 'Levy notice' },
  { name: 'case', path: () => `/cases/${ids.levyCase}`, ready: 'Waiting on someone' },
  { name: 'knowledge', path: '/knowledge', ready: 'Card dispute handbook' },
  { name: 'files', path: '/files', ready: 'notice-of-garnishment' },
  { name: 'channels', path: '/channels/email', ready: 'Legal orders' },
  { name: 'activity', path: '/activity', ready: 'Activity' },
];

async function filterToTeam(page) {
  // The agent list is the workspace's; the shot shows the demo team's agents with the Team filter set.
  await page.getByRole('button', { name: 'Team', exact: true }).first().click();
  await page.getByRole('option', { name: new RegExp(TEAM.team.name) }).first().click();
  await page.keyboard.press('Escape');
}

async function context(browser, extra = {}, who = lead) {
  const ctx = await browser.newContext({ viewport: VIEW, deviceScaleFactor: 1, ...extra });
  const page = await ctx.newPage();
  await page.goto(`${ORIGIN}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Work email').fill(who.email);
  await page.getByLabel('Password').fill(env.OPS_DEMO_PASSWORD);
  await page.getByTestId('login-submit').click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 90_000 });
  return { ctx, page };
}

async function open(page, screen) {
  const path = typeof screen.path === 'function' ? screen.path() : screen.path;
  if (path.includes('/null') || path.includes('/undefined')) throw new Error(`${screen.name}: the seeded record it opens was not found`);
  await page.goto(`${ORIGIN}${path}`, { waitUntil: 'domcontentloaded', timeout: 90_000 });
  await page.getByText(screen.ready, { exact: false }).first().waitFor({ timeout: 60_000 });
  if (screen.before) await screen.before(page);
  await page.waitForLoadState('networkidle', { timeout: 30_000 }).catch(() => {});
  await page.waitForTimeout(800);
}

async function leftovers(page, name) {
  const text = await page.locator('main').innerText().catch(() => page.locator('body').innerText());
  const hit = text.match(LEFTOVER);
  if (hit) throw new Error(`${name}: the screen shows "${hit[0]}"; fix the data or file a bug before keeping it`);
}

async function theme(page, dark) {
  await page.evaluate((on) => document.documentElement.classList.toggle('dark', on), dark);
  await page.waitForTimeout(300);
}

async function elementShot(browser, screen) {
  const { ctx, page } = await context(browser, { deviceScaleFactor: 2 });
  await open(page, screen);
  await leftovers(page, screen.name);
  // The graph's steps fill a small part of their card; the shot is cut to the steps with a margin.
  await page.getByText(screen.element).first().scrollIntoViewIfNeeded();
  const clip = await page.evaluate(() => {
    const boxes = [...document.querySelectorAll('.react-flow__node')].map((n) => n.getBoundingClientRect());
    const left = Math.min(...boxes.map((b) => b.left)) - 24;
    const top = Math.min(...boxes.map((b) => b.top)) - 24;
    const right = Math.max(...boxes.map((b) => b.right)) + 24;
    const bottom = Math.max(...boxes.map((b) => b.bottom)) + 24;
    return { x: left + window.scrollX, y: top + window.scrollY, width: right - left, height: bottom - top };
  });
  for (const dark of [false, true]) {
    await theme(page, dark);
    const file = join(OUT, `${screen.name}-${dark ? 'dark' : 'light'}.png`);
    await page.screenshot({ path: file, clip, fullPage: true });
    execFileSync('magick', [file, '-resize', '1280x', file]);
  }
  await ctx.close();
  console.log(`saved ${screen.name}-light.png, ${screen.name}-dark.png (the steps, 1280 wide)`);
}

async function screenshots(browser) {
  const { ctx, page } = await context(browser);
  for (const screen of SCREENS) {
    if (ONLY && !ONLY.has(screen.name)) continue;
    if (screen.element) {
      await elementShot(browser, screen);
      continue;
    }
    await open(page, screen);
    await leftovers(page, screen.name);
    for (const dark of [false, true]) {
      await theme(page, dark);
      await page.screenshot({ path: join(OUT, `${screen.name}-${dark ? 'dark' : 'light'}.png`) });
    }
    await theme(page, false);
    console.log(`saved ${screen.name}-light.png, ${screen.name}-dark.png`);
  }
  await ctx.close();
}

// ── Clips ─────────────────────────────────────────────────────────────────────────────────────────────────────────

/** Records `act` as <name>.gif. `first` (a path) is open and drawn before the clip starts, so it never opens on the
 * sign-in or a loading skeleton. */
async function clip(browser, name, first, act, who = lead) {
  if (ONLY && !ONLY.has(name)) return;
  const videos = mkdtempSync(join(tmpdir(), 'ops-demo-video-'));
  // The video starts with the context; the sign-in before the clip's first screen is cut from it.
  const recording = Date.now();
  const { ctx, page } = await context(browser, { recordVideo: { dir: videos, size: VIEW } }, who);
  await page.goto(`${ORIGIN}${typeof first === 'function' ? first() : first}`, { waitUntil: 'domcontentloaded', timeout: 90_000 });
  await page.waitForLoadState('networkidle', { timeout: 30_000 }).catch(() => {});
  await page.locator('main').getByText(/\S/).first().waitFor({ timeout: 60_000 });
  await page.waitForTimeout(1500);
  const started = Date.now();
  await act(page);
  const duration = (Date.now() - started) / 1000;
  await ctx.close();
  const webm = readdirSync(videos).find((f) => f.endsWith('.webm'));
  const gif = join(OUT, `${name}.gif`);
  const skip = (started - recording) / 1000;
  const filter = 'fps=10,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle';
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-ss', skip.toFixed(2), '-i', join(videos, webm), '-t', duration.toFixed(2), '-vf', filter, gif]);
  rmSync(videos, { recursive: true, force: true });
  console.log(`saved ${name}.gif (${duration.toFixed(1)} s, ${(statSync(gif).size / 1e6).toFixed(1)} MB)`);
}

const pause = (page, ms) => page.waitForTimeout(ms);

async function nav(page, label, ready) {
  // The sidebar, as a person moves around: a client-side move draws without the full-page loading state.
  await page.getByRole('link', { name: new RegExp(`^${label}`) }).first().click();
  await page.getByText(ready, { exact: false }).first().waitFor({ timeout: 60_000 });
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {});
}

async function hero(page) {
  // A morning in the team: what waits on a person, a cited chat answer, the Human Tasks and a levy case.
  await pause(page, 1500);
  await nav(page, 'Chat', 'New chat');
  await page.getByText(disputeChat.title).first().click();
  await page.getByText('Sources').first().waitFor({ timeout: 60_000 });
  await pause(page, 2200);
  await nav(page, 'Human Tasks', 'Provisional credit');
  await pause(page, 1800);
  await nav(page, 'Cases', 'Levy notice');
  await page.getByText('Levy notice: Marcus Bell').first().click();
  await page.getByText('Waiting on someone').first().waitFor({ timeout: 60_000 });
  await pause(page, 2500);
}

async function agentAnswers(page) {
  // A new chat with Dispute Desk: it looks the cardholder up with two tool calls and answers; the chat is deleted after.
  await page.goto(`${ORIGIN}/chat`, { waitUntil: 'domcontentloaded' });
  await page.getByText('What do you need?').waitFor({ timeout: 60_000 });
  await page.getByRole('combobox').first().click().catch(() => {});
  await page.getByRole('option', { name: /Dispute Desk/ }).first().click().catch(() => {});
  const box = page.getByPlaceholder(/Message /);
  await box.click();
  await box.pressSequentially(disputeChat.turns[0], { delay: 30 });
  await box.press('Enter');
  await page.getByText('Tell me the reason he gives', { exact: false }).waitFor({ timeout: 90_000 });
  await pause(page, 4000);
  const url = new URL(page.url());
  const thread = url.pathname.split('/').pop();
  if (thread && thread.startsWith('th_')) await api('agents', '/chat/threads/bulk-delete', { ...as, method: 'POST', body: { ids: [thread] } });
}

let testRun = args['test-run'] ?? null;
async function workflowRun(page) {
  // One test-mode run of the dispute workflow, its steps lighting up on the run page until it waits on a person.
  await open(page, SCREENS.find((s) => s.name === 'workflow'));
  await pause(page, 1200);
  const started = await api('agents', '/v1/runs', {
    ...as,
    token: await signIn(TEAM.people.find((p) => p.key === 'builder').email),
    method: 'POST',
    body: { workflowId: 'card_dispute_intake', mode: 'test', input: TEAM.runs.find((r) => r.key === 'dispute-northline').input },
  });
  testRun = started.runId;
  await page.goto(`${ORIGIN}/workflows/runs/${testRun}`, { waitUntil: 'domcontentloaded' });
  await page.getByText('Waiting', { exact: true }).first().waitFor({ timeout: 90_000 });
  await pause(page, 2500);
}

async function taskDecided(page) {
  // The workflow clip's run, decided by its approver on the Human Task page, then the run going on to its end.
  if (!testRun) throw new Error('task: run the workflow clip first, in the same capture');
  await pause(page, 1500);
  await page.getByRole('button', { name: 'Details' }).click();
  await pause(page, 3000);
  await page.getByRole('button', { name: 'Approve', exact: true }).last().click();
  const confirm = page.getByRole('dialog').getByRole('button', { name: /^Approve/ });
  if (await confirm.isVisible({ timeout: 2000 }).catch(() => false)) await confirm.click();
  await pause(page, 1500);
  for (let i = 0; i < 20 && (await api('agents', `/v1/runs/${testRun}`, as)).status !== 'succeeded'; i++) await pause(page, 1000);
  await page.goto(`${ORIGIN}/workflows/runs/${testRun}`, { waitUntil: 'domcontentloaded' });
  await page.getByText('Ended at Credited').first().waitFor({ timeout: 60_000 });
  await pause(page, 3500);
  // The test run's case is marked [Test]; it is closed so the team's open cases stay the seeded ones.
  for (const c of rows(await api('agents', '/v1/cases?search=%5BTest%5D&pageSize=50', as))) {
    if (c.status === 'closed' || !c.subject.startsWith('[Test]')) continue;
    await api('agents', `/v1/cases/${c.id}`, { ...as, method: 'PATCH', body: { status: 'closed' } });
  }
}

async function mailToCase(page) {
  // The emailed notice: the mailbox that received it, the run it started and the case per debtor.
  await open(page, SCREENS.find((s) => s.name === 'channels'));
  await pause(page, 1500);
  await open(page, { name: 'levy-run', path: () => `/workflows/runs/${ids.levyRun}`, ready: 'Graph' });
  await pause(page, 2000);
  await open(page, SCREENS.find((s) => s.name === 'cases'));
  await pause(page, 1500);
  await open(page, SCREENS.find((s) => s.name === 'case'));
  await pause(page, 2200);
}

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
try {
  if (!args['no-shots']) await screenshots(browser);
  // Clips act on the install (one chat turn, one test-mode run each time), so they are taken only when asked for.
  if (args.clips) {
    await clip(browser, 'hero', '/', hero);
    await clip(browser, 'agent', '/chat', agentAnswers);
    await clip(browser, 'workflow', '/workflows/card_dispute_intake', workflowRun);
    await clip(browser, 'task', () => `/reviews/${testRun}:review:1`, taskDecided, approver);
    await clip(browser, 'mail', '/channels/email', mailToCase);
  }
} finally {
  await browser.close();
}
