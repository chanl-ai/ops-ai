// uc-671 Connectors for people, ui layer: docs/usecases/tools-service/connectors-for-people.md, steps 8-12. A headless
// walk of the integration console on the run's own stack (withUiStack, never the local dev stack) as Priya (Operations
// admin, signed in to Salesforce there by the script), Ravi (Operations viewer) and Sam (Security admin, Salesforce off for Security). It changes
// only one test chat's connectors. Screenshots at 1280 light and 390 dark go to
// evidenceDir('671', 'uc'). SAM_THREAD names a chat of Sam's that the salesforce-off-for-team script left, for its card.
import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { request as httpsRequest } from 'node:https';
import { join } from 'node:path';
import { createInterface } from 'node:readline';

import { AGENTS_PORT, PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

// The run's own stack (withUiStack): its ports are this run's, never the local dev stack's.
const PLATFORM = `http://127.0.0.1:${PLATFORM_PORT}`;
const AGENTS = `http://127.0.0.1:${AGENTS_PORT}`;
const TOOLS = `http://127.0.0.1:${TOOLS_PORT}`;
const LIB = join(ROOT, 'docs/usecases/lib');
const PLUGINS = join(process.env.OPS_PLUGINS_REPO || join(ROOT, '..', 'ops-ai-plugins'), 'plugins');
let CONSOLE = '';
const PASSWORD = process.env.OPS_DEMO_PASSWORD ?? 'northfield-demo';
const PRIYA = 'p.shah@harborpine.example';
const RAVI = 'r.menon@harborpine.example';
const SAM = 's.adeyemi@harborpine.example';
const SALESFORCE = 'plugin:opsai.salesforce';
const GITHUB = 'plugin:opsai.github';
const SHOTS = evidenceDir('671', 'uc');
const errors = [];

async function token(email) {
  const r = await fetch(`${PLATFORM}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) });
  return (await r.json()).data.token;
}

/** The fake Salesforce of docs/usecases/lib/fake_salesforce.py: its OAuth server, and the settings tools-service needs to reach it. */
async function startFake() {
  const child = spawn('uv', ['run', '--quiet', '--directory', join(ROOT, 'services/agents-service'), 'python', join(LIB, 'fake_salesforce.py')], { stdio: ['pipe', 'pipe', 'inherit'], env: { ...process.env, PYTHONPATH: LIB } });
  const line = await new Promise((resolve, reject) => {
    createInterface({ input: child.stdout }).once('line', resolve);
    child.once('exit', (code) => reject(new Error(`fake Salesforce exited with ${code}`)));
  });
  return { child, info: JSON.parse(line) };
}

async function stopFake(fake) {
  if (!fake || fake.child.exitCode !== null) return;
  const exited = new Promise((resolve) => fake.child.once('exit', resolve));
  fake.child.stdin.end();
  const timer = setTimeout(() => fake.child.kill('SIGTERM'), 20_000);
  await exited;
  clearTimeout(timer);
}

/** A person's browser through the fake's sign-in page: reached by address with the sign-in host named in Host and in SNI, trusting the fake's own certificate (`sf.ca`), whose names include the sign-in host. */
function fakeSignIn(sf, authorizeUrl, username) {
  const url = new URL(authorizeUrl);
  const at = new URL(sf.control);
  const ca = readFileSync(sf.ca);
  const send = (method, body) =>
    new Promise((resolve, reject) => {
      const req = httpsRequest({ host: at.hostname, port: at.port, path: url.pathname + url.search, method, ca, servername: url.hostname, headers: { Host: url.hostname, ...(body ? { 'Content-Type': 'application/x-www-form-urlencoded', 'Content-Length': Buffer.byteLength(body) } : {}) } }, (res) => {
        res.resume();
        res.on('end', () => resolve(res));
      });
      req.on('error', reject);
      req.end(body);
    });
  return send('GET').then(async () => {
    const posted = await send('POST', new URLSearchParams({ username, claims: '' }).toString());
    const back = new URL(posted.headers.location ?? 'http://x/').searchParams;
    return { code: back.get('code') ?? '', state: back.get('state') ?? '' };
  });
}

/** Operations has Salesforce on and Priya signed in to it as herself, as the use case's precondition says; the run's database holds nobody's sign-in until this does it. */
async function setUp(sf) {
  const t = await token(PRIYA);
  const sam = await token(SAM);
  const headers = { Authorization: `Bearer ${t}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
  await fetch(`${TOOLS}/v1/egress/ranges`, { method: 'POST', headers: { Authorization: `Bearer ${sam}`, 'X-Team-Id': 'team_security', 'Content-Type': 'application/json' }, body: JSON.stringify({ value: sf.range, note: 'uc-671' }) });
  const on = await fetch(`${TOOLS}/v1/apps/${encodeURIComponent(SALESFORCE)}/team`, { method: 'PUT', headers, body: JSON.stringify({ enabled: true, signIn: 'person_or_team', accountName: 'Retail org', settings: { login_url: sf.login_url } }) });
  // The team's assistant gets Salesforce's tools, as the Turn on window's box gives them, so a chat lists Salesforce.
  await fetch(`${AGENTS}/v1/team-assistant/app-tools`, { method: 'POST', headers, body: JSON.stringify({ moduleIds: (await on.json()).data?.moduleIds ?? [] }) });
  const rows = (await (await fetch(`${TOOLS}/v1/me/connections`, { headers })).json()).data;
  const account = rows.find((r) => r.appId === SALESFORCE)?.primaryAccountId;
  const started = await (await fetch(`${TOOLS}/v1/apps/${encodeURIComponent(SALESFORCE)}/accounts/${account}/sign-in`, { method: 'POST', headers, body: JSON.stringify({ account: 'self' }) })).json();
  const back = await fakeSignIn(sf, started.data.authorizeUrl, 'priya.own');
  const done = await fetch(`${TOOLS}/v1/sign-ins/complete`, { method: 'POST', headers, body: JSON.stringify(back) });
  const after = (await (await fetch(`${TOOLS}/v1/me/connections`, { headers })).json()).data;
  console.log('SETUP', on.status, done.status, JSON.stringify(after.map((x) => ({ id: x.appId, st: x.appState, g: x.appGroup, n: x.accountCount }))));
}

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

/** Whether every element matching `selector` that is shown lies inside the viewport's width. */
const inside = (page, selector) =>
  page.$$eval(selector, (els) => els.filter((e) => e.getClientRects().length).every((e) => e.getBoundingClientRect().right <= window.innerWidth + 1));

const fake = await startFake();
try {
await withUiStack(
  async (consoleUrl) => {
    CONSOLE = consoleUrl.replace(/\/$/, '');
    await setUp(fake.info);
  const browser = await chromium.launch();
  try {
    const priya = await consoleSignIn(browser, CONSOLE, PRIYA, PASSWORD, errors);
    await priya.setViewportSize({ width: 1280, height: 900 });

    await step('8 Connectors (Mine) at 1280: one GitHub card, +N accounts only when there are more, a can-do line per card, a switcher to Team setup', async () => {
      await priya.goto(`${CONSOLE}/integrations/my-accounts`, { waitUntil: 'domcontentloaded' });
      await priya.getByTestId('connectors').waitFor({ timeout: 60_000 });
      const github = await priya.locator(`[data-testid="connector-${GITHUB}"]`).count();
      const more = await priya.getByTestId(`connector-more-${GITHUB}`).count();
      // "+N accounts" shows exactly when the person holds more than one GitHub account, as the API counts them.
      const rows = (await (await fetch(`${TOOLS}/v1/me/connections`, { headers: { Authorization: `Bearer ${await token(PRIYA)}`, 'X-Team-Id': 'team_ops' } })).json()).data;
      const several = (rows.find((r) => r.appId === GITHUB)?.accountCount ?? 0) > 1;
      const lines = await priya.locator('[data-testid^="connector-can-do-"]').allInnerTexts();
      await priya.getByTestId('title-switcher').click();
      const views = await priya.locator('[data-testid^="title-switcher-"][data-testid$="-connectors"]').allInnerTexts();
      await priya.keyboard.press('Escape');
      await priya.locator('[data-testid^="title-switcher-"][data-testid$="-connectors"]').first().waitFor({ state: 'hidden', timeout: 10_000 });
      await priya.screenshot({ path: join(SHOTS, 'mine-1280-light.png'), fullPage: true });
      // My connectors is the user menu's row; Connectors (Team setup) is the Data area's sidebar row (lib/nav.ts).
      await priya.goto(`${CONSOLE}/data/connectors`, { waitUntil: 'domcontentloaded' });
      const sidebar = priya.locator('[data-sidebar="sidebar"]').first();
      await sidebar.getByRole('link', { name: 'Connectors', exact: true }).first().waitFor({ timeout: 30_000 }).catch(() => {});
      const hub = await sidebar.getByRole('link', { name: 'Connectors', exact: true }).count();
      await sidebar.getByTestId('nav-user').click();
      const top = await priya.getByTestId('nav-connections').filter({ hasText: 'My connectors' }).count();
      await priya.keyboard.press('Escape');
      check('8c at 1280 the user menu reads My connectors and the Data area row Connectors', top === 1 && hub === 1, { top, hub });
      await priya.goto(`${CONSOLE}/integrations/my-accounts`, { waitUntil: 'domcontentloaded' });
      await priya.getByTestId('connectors').waitFor({ timeout: 60_000 });
      // An app the install no longer loads (Ticket desk) is not a connector, so it is never offered Add key.
      const gone = await priya.locator('[data-testid="connectors"]').getByText('Ticket desk').count();
      const search = priya.getByPlaceholder('Search connectors…');
      await search.fill('git');
      await priya.waitForTimeout(500);
      const found = await priya.locator('[data-testid^="connector-plugin:"]').count();
      await search.fill('jira');
      await priya.waitForTimeout(500);
      const none = await priya.locator('[data-testid^="connector-plugin:"]').count();
      await search.fill('');
      check('8b search finds GitHub alone, "jira" finds none, and an app the install lacks is not listed', found === 1 && none === 0 && gone === 0, { found, none, gone });
      check('8 Connectors (Mine) at 1280: one GitHub card, +N accounts only when there are more, a can-do line per card, a switcher to Team setup', github === 1 && more === (several ? 1 : 0) && lines.length > 0 && lines.every(Boolean) && views.map((v) => v.trim()).join('|') === 'Mine|Team setup', { github, more, several, lines, views });
    });

    await step("9 a row's details: what it can do with Read, Write and Reviewed, Used by as links, Test now and Disconnect", async () => {
      await priya.locator(`[data-testid="connector-${SALESFORCE}"]`).click();
      const sheet = priya.getByTestId('connector-sheet');
      await sheet.waitFor({ timeout: 30_000 });
      const marks = await sheet.getByTestId('connector-tools').innerText();
      const links = await sheet.getByTestId('connector-used-by').locator('a').count();
      const lists = await sheet.getByTestId('connector-used-by').locator('ul, table').count();
      const buttons = (await sheet.getByTestId('connector-test').count()) + (await sheet.getByTestId('connector-disconnect').count());
      await priya.screenshot({ path: join(SHOTS, 'sheet-1280-light.png') });
      await priya.keyboard.press('Escape');
      check("9 a row's details: what it can do with Read, Write and Reviewed, Used by as links, Test now and Disconnect", /Read/.test(marks) && links === 3 && lists === 0 && buttons === 2, { marks: marks.slice(0, 200), links, lists, buttons });
    });

    await step('10 at 390 in dark the state and action stay on screen, and no screen says Apps or My accounts', async () => {
      const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, colorScheme: 'dark', storageState: await priya.context().storageState() });
      const p = await phone.newPage();
      p.on('pageerror', (e) => errors.push(`390: ${e.message}`));
      await p.goto(`${CONSOLE}/integrations/my-accounts`, { waitUntil: 'domcontentloaded' });
      await p.getByTestId('connectors').waitFor({ timeout: 60_000 });
      const fits = await inside(p, '[data-testid^="connector-plugin:"] button, [data-testid^="connector-plugin:"] a');
      const scroll = await p.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
      await p.screenshot({ path: join(SHOTS, 'mine-390-dark.png'), fullPage: true });
      await p.goto(`${CONSOLE}/data/connectors`, { waitUntil: 'domcontentloaded' });
      await p.getByRole('button', { name: 'Toggle Sidebar' }).first().click();
      const drawer = p.locator('[data-mobile="true"]').first();
      await drawer.waitFor({ timeout: 15_000 });
      const hub390 = await drawer.getByRole('link', { name: 'Connectors', exact: true }).count();
      await drawer.getByTestId('nav-user').first().click();
      const top390 = await p.getByTestId('nav-connections').filter({ hasText: 'My connectors' }).count();
      await p.keyboard.press('Escape');
      check('10b at 390 the drawer\'s user menu reads My connectors and its Data area row Connectors', top390 === 1 && hub390 === 1, { top390, hub390 });
      const words = [];
      for (const path of ['/integrations/my-accounts', '/integrations', `/integrations/${encodeURIComponent(GITHUB)}`]) {
        await p.goto(`${CONSOLE}${path}`, { waitUntil: 'domcontentloaded' });
        await p.waitForTimeout(1500);
        const text = await p.locator('body').innerText();
        if (/My accounts|\bApps\b(?! that| your| whose)/.test(text)) words.push(path);
      }
      await p.goto(`${CONSOLE}/integrations`, { waitUntil: 'domcontentloaded' });
      await p.waitForTimeout(1500);
      await p.screenshot({ path: join(SHOTS, 'team-setup-390-dark.png'), fullPage: true });
      await phone.close();
      check('10 at 390 in dark the state and action stay on screen, and no screen says Apps or My accounts', fits && scroll && words.length === 0, { fits, scroll, words });
    });

    await step('11 the composer picker lists Salesforce checked, and unchecking it leaves its tools out of that chat only', async () => {
      const auth = { Authorization: `Bearer ${await token(PRIYA)}`, 'Content-Type': 'application/json', 'X-Team-Id': 'team_ops' };
      const made = await (await fetch(`${AGENTS}/chat/threads`, { method: 'POST', headers: auth, body: JSON.stringify({ kbIds: [], title: '[test] connectors picker' }) })).json();
      const tid = made.data.id;
      await priya.goto(`${CONSOLE}/chat/${tid}`, { waitUntil: 'domcontentloaded' });
      await priya.getByTestId('connectors-picker').click();
      const toggle = priya.getByTestId(`connector-toggle-${SALESFORCE}`);
      await toggle.waitFor({ timeout: 30_000 });
      const before = await toggle.getAttribute('data-on');
      const listed = await (await fetch(`${AGENTS}/chat/threads/${tid}/connectors`, { headers: auth })).json();
      // Each connector's group comes from its app's state (lib/app-state.ts): off and needs_auth_config are an admin's.
      const want = { sign_in: 'Needs your sign-in', off_for_team: 'Off for this team' };
      const groupOf = (state) => (state === 'needs_sign_in' ? 'sign_in' : ['off', 'needs_auth_config'].includes(state) ? 'off_for_team' : 'on');
      const groups = await priya.getByTestId('connectors-picker-list').innerText();
      const states = new Set(listed.data.connectors.map((c) => groupOf(c.appState)));
      const groupsOk = Object.entries(want).every(([state, heading]) => states.has(state) === groups.includes(heading));
      check('11b the picker draws a sign-in group and an off-for-team group exactly when the chat has such connectors', groupsOk, { states: [...states], groups: groups.slice(0, 300) });
      await priya.screenshot({ path: join(SHOTS, 'picker-1280-light.png') });
      await toggle.click();
      await priya.waitForFunction((id) => document.querySelector(`[data-testid="connector-toggle-${id}"]`)?.getAttribute('data-on') === 'false', SALESFORCE, { timeout: 15_000 });
      const settings = await (await fetch(`${AGENTS}/chat/threads/${tid}/settings`, { headers: auth })).json();
      const off = settings.data.effective.toolsOff ?? [];
      const other = await (await fetch(`${AGENTS}/chat/threads`, { method: 'POST', headers: auth, body: JSON.stringify({ kbIds: [], title: '[test] connectors next' }) })).json();
      const next = await (await fetch(`${AGENTS}/chat/threads/${other.data.id}/connectors`, { headers: auth })).json();
      const nextOn = next.data.connectors.find((c) => c.appId === SALESFORCE)?.on;
      check('11 the composer picker lists Salesforce checked, and unchecking it leaves its tools out of that chat only', before === 'true' && off.length > 0 && off.every((t) => t.startsWith('salesforce_')) && nextOn === true, { before, off, nextOn });
    });

    await step('11c on Chat\'s home the picker works before the first message, and the new chat takes its choice', async () => {
      const auth = { Authorization: `Bearer ${await token(PRIYA)}`, 'X-Team-Id': 'team_ops' };
      await priya.goto(`${CONSOLE}/chat`, { waitUntil: 'domcontentloaded' });
      await priya.getByTestId('connectors-picker').click();
      const toggle = priya.getByTestId(`connector-toggle-${SALESFORCE}`);
      await toggle.waitFor({ timeout: 30_000 });
      await toggle.click();
      await priya.waitForFunction((id) => document.querySelector(`[data-testid="connector-toggle-${id}"]`)?.getAttribute('data-on') === 'false', SALESFORCE, { timeout: 15_000 });
      await priya.keyboard.press('Escape');
      await priya.getByRole('textbox').first().fill('What needs me today?');
      await priya.keyboard.press('Enter');
      await priya.waitForURL(/\/chat\/th_/, { timeout: 60_000 });
      const tid = new URL(priya.url()).pathname.split('/').pop();
      const settings = await (await fetch(`${AGENTS}/chat/threads/${tid}/settings`, { headers: auth })).json();
      const off = settings.data.effective.toolsOff ?? [];
      check('11c on Chat\'s home the picker works before the first message, and the new chat takes its choice', off.length > 0 && off.every((t) => t.startsWith('salesforce_')), { tid, off });
    });

    await step("13 with two GitHub accounts Mine marks the person's default plainly", async () => {
      await priya.goto(`${CONSOLE}/integrations/my-accounts`, { waitUntil: 'domcontentloaded' });
      await priya.getByTestId('connectors').waitFor({ timeout: 60_000 });
      await priya.locator(`[data-testid="connector-${GITHUB}"]`).click();
      const sheet = priya.getByTestId('connector-sheet');
      await sheet.waitFor({ timeout: 30_000 });
      const marks = await sheet.getByText('Default', { exact: true }).count();
      await priya.screenshot({ path: join(SHOTS, 'sheet-github-default.png') });
      await priya.keyboard.press('Escape');
      check("13 with two GitHub accounts Mine marks the person's default plainly", marks <= 1, { marks });
    });

    await step("12 Ravi's Team setup has no Add custom app and no Connect; Sam's chat shows the off-for-team card", async () => {
      const ravi = await consoleSignIn(browser, CONSOLE, RAVI, PASSWORD, errors);
      await ravi.goto(`${CONSOLE}/integrations`, { waitUntil: 'domcontentloaded' });
      await ravi.getByTestId('systems-grid').waitFor({ timeout: 60_000 });
      const add = await ravi.getByTestId('connect-system').count();
      await ravi.goto(`${CONSOLE}/integrations/${encodeURIComponent(SALESFORCE)}`, { waitUntil: 'domcontentloaded' });
      await ravi.waitForTimeout(3000);
      const connect = await ravi.getByTestId('app-connect').count();
      await ravi.screenshot({ path: join(SHOTS, 'team-setup-app-viewer-1280.png') });
      let card = 'no SAM_THREAD given';
      if (process.env.SAM_THREAD) {
        const sam = await consoleSignIn(browser, CONSOLE, SAM, PASSWORD, errors);
        await sam.goto(`${CONSOLE}/chat/${process.env.SAM_THREAD}`, { waitUntil: 'domcontentloaded' });
        await sam.getByTestId('app-off-card').first().waitFor({ timeout: 60_000 });
        card = await sam.getByTestId('app-off-card').first().innerText();
        await sam.screenshot({ path: join(SHOTS, 'chat-off-for-team-1280.png') });
      }
      check("12 Ravi's Team setup has no Add custom app and no Connect; Sam's chat shows the off-for-team card", add === 0 && connect === 0 && (!process.env.SAM_THREAD || /off for Security/.test(card)), { add, connect, card: card.slice(0, 200) });
    });
  } finally {
    await browser.close();
  }
  },
  {
    platform: true,
    tools: {
      // The chat picker reads the apps through agents-service, which reaches tools-service as the gateway.
      gateway: true,
      env: {
        ...fake.info.settings,
        OPS_PLUGINS: 'true',
        OPS_PLUGIN_PATHS: JSON.stringify([join(PLUGINS, 'github/src/ops_plugin_github'), join(PLUGINS, 'salesforce/src/ops_plugin_salesforce')]),
        // Ops AI's own app for Salesforce only: GitHub signs in through a team's auth config or not at all.
        OPS_PLUGIN_CLIENTS: JSON.stringify({ 'opsai.salesforce': { id: 'ops-ai-acme', secret: 'acme-connected-app-secret' } }),
      },
    },
  },
);
} finally {
  await stopFake(fake);
}
check('no page error on any screen', errors.length === 0, errors.slice(0, 5));
finish();
