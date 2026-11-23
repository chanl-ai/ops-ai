// uc-770 Admins see people's app sign-ins and end one, ui layer: docs/usecases/tools-service/admins-see-people-s-app-sign.md.
// A headless walk on the run's own stack (withUiStack): Priya (Operations admin) adds a key app each person signs in
// to, James (builder) and Ravi (viewer) give their own keys through the API as My apps does, then Priya reads Apps and
// People at 1440 and 390 and ends James's sign-in from his sheet. James is refused People. Screenshots go to
// evidenceDir('770', 'uc').
import { join } from 'node:path';

import { PLATFORM_PORT, TOOLS_PORT, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const PLATFORM = `http://127.0.0.1:${PLATFORM_PORT}`;
const TOOLS = `http://127.0.0.1:${TOOLS_PORT}`;
const PASSWORD = process.env.OPS_DEMO_PASSWORD ?? 'northfield-demo';
const PRIYA = 'p.shah@harborpine.example';
const JAMES = 'j.richardson@harborpine.example';
const RAVI = 'r.menon@harborpine.example';
const SALESFORCE = 'plugin:opsai.salesforce';
const CORE = 'plugin:opsai.core';
const SHOTS = evidenceDir('770', 'uc');
const errors = [];

async function headers(email) {
  const r = await fetch(`${PLATFORM}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) });
  return { Authorization: `Bearer ${(await r.json()).data.token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
}

async function api(email, method, path, body) {
  const r = await fetch(`${TOOLS}${path}`, { method, headers: await headers(email), body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, body: await r.json().catch(() => null) };
}

/** Claims desk: a key app each person signs in to, with James's and Ravi's own keys given as My apps gives them. */
async function setUp() {
  const made = await api(PRIYA, 'POST', '/v1/apps', { name: 'Claims desk', authKind: 'api_key', signIn: 'person', category: 'Insurance' });
  const id = made.body?.data?.id;
  const path = `/v1/apps/${id}/accounts/${id}`;
  const set = await api(PRIYA, 'PATCH', path, { revision: made.body?.data?.revision, settings: { baseUrl: 'https://claims.desk.test', name: 'X-Api-Key' } });
  const james = await api(JAMES, 'PUT', `/v1/me/accounts/${id}/credentials`, { credentials: { key: 'james-key' } });
  const ravi = await api(RAVI, 'PUT', `/v1/me/accounts/${id}/credentials`, { credentials: { key: 'ravi-key' } });
  console.log('SETUP', made.status, set.status, james.status, ravi.status, id);
  return id;
}

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

const fits = (p) => p.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);

/** Server errors a page's requests answered while `body` ran. */
async function failures(page, body) {
  const bad = [];
  const seen = (r) => r.status() >= 500 && bad.push(`${r.status()} ${r.url()}`);
  page.on('response', seen);
  try {
    await body();
  } finally {
    page.off('response', seen);
  }
  return bad;
}

await withUiStack(async (consoleUrl) => {
  const CONSOLE = consoleUrl.replace(/\/$/, '');
  const app = await setUp();
  const browser = await chromium.launch();
  try {
    const priya = await consoleSignIn(browser, CONSOLE, PRIYA, PASSWORD, errors);
    await priya.setViewportSize({ width: 1440, height: 1000 });

    await step('1 Apps opens as a table with how people sign in and the sign-in health, no content pack, and a People tab', async () => {
      await priya.goto(`${CONSOLE}/data/connectors`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const row = priya.getByTestId(`app-row-${app}`);
      await row.waitFor({ timeout: 120_000 });
      const health = (await priya.getByTestId(`app-${app}-sign-ins`).innerText()).replace(/\s+/g, ' ');
      const table = await priya.getByTestId('view-toggle-table').getAttribute('aria-pressed');
      const how = await priya.getByText('Each person', { exact: true }).count();
      const pack = await priya.getByTestId(`app-row-${CORE}`).count();
      const tab = await priya.getByTestId('apps-tab-people').count();
      await priya.screenshot({ path: join(SHOTS, 'apps-priya-1440.png'), fullPage: true });
      check('1 Apps opens as a table with how people sign in and the sign-in health, no content pack, and a People tab', table === 'true' && /2 connected/.test(health) && how >= 1 && pack === 0 && tab === 1, { table, health, how, pack, tab });
    });

    await step('2 People lists James and Ravi with counts that match the server', async () => {
      await priya.getByTestId('apps-tab-people').click();
      await priya.getByTestId('people-table').waitFor({ timeout: 60_000 });
      await priya.getByText('Ravi', { exact: false }).first().waitFor({ timeout: 30_000 });
      const listed = (await api(PRIYA, 'GET', '/v1/apps/people')).body?.data?.data ?? [];
      const shown = [];
      for (const p of listed) {
        const row = priya.getByTestId(`person-row-${p.personId}`);
        const connected = (await priya.getByTestId(`person-${p.personId}-connected`).innerText()).trim();
        shown.push({ name: p.name, rows: await row.count(), connected, server: p.connected });
      }
      await priya.screenshot({ path: join(SHOTS, 'people-priya-1440.png'), fullPage: true });
      check('2 People lists James and Ravi with counts that match the server', listed.length === 2 && shown.every((s) => s.rows === 1 && s.connected === String(s.server)), shown);
    });

    await step("3 End sign-in from James's sheet marks it Ended by an admin, and his row and the server count it refused", async () => {
      const listed = (await api(PRIYA, 'GET', '/v1/apps/people')).body?.data?.data ?? [];
      const james = listed.find((p) => /james/i.test(`${p.name} ${p.personId}`));
      await priya.getByTestId(`person-row-${james.personId}`).click();
      const sheet = priya.getByTestId('person-sheet');
      await sheet.waitFor({ timeout: 30_000 });
      await sheet.getByTestId(`end-sign-in-${app}`).click();
      await priya.getByRole('dialog').getByRole('button', { name: 'End sign-in' }).click();
      const badge = sheet.getByTestId(`sign-in-${app}-state`);
      await priya.waitForFunction((id) => /Ended by an admin/.test(document.querySelector(`[data-testid="sign-in-${id}-state"]`)?.textContent ?? ''), app, { timeout: 30_000 });
      const word = (await badge.innerText()).trim();
      const again = await sheet.getByTestId(`end-sign-in-${app}`).count();
      await priya.screenshot({ path: join(SHOTS, 'people-sheet-ended-1440.png') });
      await priya.keyboard.press('Escape');
      const refused = (await priya.getByTestId(`person-${james.personId}-refused`).innerText()).trim();
      const server = ((await api(PRIYA, 'GET', '/v1/apps/people')).body?.data?.data ?? []).find((p) => p.personId === james.personId);
      check("3 End sign-in from James's sheet marks it Ended by an admin, and his row and the server count it refused", word === 'Ended by an admin' && again === 0 && refused === '1' && server?.refused === 1 && server?.connected === 0, { word, again, refused, server: server && { c: server.connected, r: server.refused } });
    });

    await step('4 at 390 Apps and People fit the screen, the tables scrolling inside their frames', async () => {
      const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, storageState: await priya.context().storageState() });
      const p = await phone.newPage();
      p.on('pageerror', (e) => errors.push(`390: ${e.message}`));
      await p.goto(`${CONSOLE}/data/connectors`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await p.getByTestId(`app-row-${app}`).waitFor({ timeout: 60_000 });
      const apps = await fits(p);
      await p.screenshot({ path: join(SHOTS, 'apps-priya-390.png'), fullPage: true });
      await p.goto(`${CONSOLE}/data/connectors/people`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await p.getByTestId('people-table').waitFor({ timeout: 60_000 });
      const people = await fits(p);
      await p.screenshot({ path: join(SHOTS, 'people-priya-390.png'), fullPage: true });
      await phone.close();
      check('4 at 390 Apps and People fit the screen, the tables scrolling inside their frames', apps && people, { apps, people });
    });

    await step("5 James is not offered People, a direct visit names the permission, and his My apps card says an admin ended it", async () => {
      const james = await consoleSignIn(browser, CONSOLE, JAMES, PASSWORD, errors);
      await james.goto(`${CONSOLE}/data/connectors`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByTestId(`app-row-${app}`).waitFor({ timeout: 60_000 });
      const tab = await james.getByTestId('apps-tab-people').count();
      const people = (await api(JAMES, 'GET', '/v1/apps/people')).status;
      await james.goto(`${CONSOLE}/data/connectors/people`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const refused = james.getByTestId('query-forbidden');
      await refused.waitFor({ timeout: 60_000 });
      const words = (await refused.innerText()).replace(/\s+/g, ' ');
      await james.screenshot({ path: join(SHOTS, 'people-james-refused-1440.png'), fullPage: true });
      await james.goto(`${CONSOLE}/work/apps`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const ended = await james.getByTestId(`connector-ended-${app}`).waitFor({ timeout: 60_000 }).then(() => true, () => false);
      await james.screenshot({ path: join(SHOTS, 'my-apps-james-ended-1440.png'), fullPage: true });
      await james.context().close();
      check("5 James is not offered People, a direct visit names the permission, and his My apps card says an admin ended it", tab === 0 && people === 403 && /Manage on Connections/.test(words) && ended, { tab, people, words, ended });
    });

    await step('6 the Salesforce app page loads as an admin and a viewer with no request failing', async () => {
      const ravi = await consoleSignIn(browser, CONSOLE, RAVI, PASSWORD, errors);
      const out = {};
      for (const [who, page] of [['priya', priya], ['ravi', ravi]]) {
        out[who] = await failures(page, async () => {
          await page.goto(`${CONSOLE}/data/connectors/${encodeURIComponent(SALESFORCE)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByText('Salesforce').first().waitFor({ timeout: 60_000 });
          await page.waitForLoadState('networkidle', { timeout: 30_000 }).catch(() => {});
        });
      }
      const status = (await api(RAVI, 'GET', `/v1/apps/${encodeURIComponent(SALESFORCE)}`)).status;
      await ravi.context().close();
      check('6 the Salesforce app page loads as an admin and a viewer with no request failing', status === 200 && out.priya.length === 0 && out.ravi.length === 0, { status, ...out });
    });

    check('no page error on any screen', errors.length === 0, errors.slice(0, 5));
  } finally {
    await browser.close();
  }
}, { platform: true, tools: { gateway: true, env: { OPS_PLUGINS: 'true' } } });
finish();
