// uc-703 Add account is on the Accounts tab for whoever manages apps, and never for a member, ui layer:
// docs/usecases/tools-service/add-account-lives-on-the-accounts-tab.md. Salesforce has two team accounts (Retail org and
// EU org, at two My Domains of the fake Salesforce). Priya (admin) and Maya (member) open its Accounts tab at 1440 and
// 390; Maya also opens Connectors > Mine. Screenshots go to OPS_USECASE_SHOTS when set (the evidence folder otherwise).
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { createInterface } from 'node:readline';
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const agentsUrl = `http://127.0.0.1:${AGENTS_PORT}`;
const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const PASSWORD = 'northfield-demo';
const PRIYA = 'p.shah@harborpine.example';
const MAYA = 'm.okafor@harborpine.example';
const SHOTS = process.env.OPS_USECASE_SHOTS || evidenceDir('703', 'uc');
const SALESFORCE = join(process.env.OPS_PLUGINS_REPO || join(ROOT, '..', 'ops-ai-plugins'), 'plugins/salesforce/src/ops_plugin_salesforce');
const LIB = join(ROOT, 'docs/usecases/lib');
const APP = 'plugin:opsai.salesforce';

async function startFake() {
  const child = spawn('uv', ['run', '--quiet', '--directory', join(ROOT, 'services/agents-service'), 'python', join(LIB, 'fake_salesforce.py')], {
    stdio: ['pipe', 'pipe', 'inherit'],
    env: { ...process.env, PYTHONPATH: LIB },
  });
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

let fake;
try {
  fake = await startFake();
  const sf = fake.info;
  const tokenFor = async (email) => (await (await fetch(`${platform}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
  const as = (token, team) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
  const call = async (method, path, headers, body) => {
    const r = await fetch(`${tools}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    const json = await r.json().catch(() => null);
    return { status: r.status, data: json?.data, text: JSON.stringify(json).slice(0, 300) };
  };

  async function signedIn(browser, consoleUrl, email, width) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, ignoreHTTPSErrors: true });
    const page = await context.newPage();
    page.errors = [];
    page.on('pageerror', (e) => page.errors.push(e.message));
    await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByLabel('Work email').fill(email);
    await page.getByLabel('Password').fill(PASSWORD);
    await page.getByTestId('login-submit').click();
    await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
    return page;
  }

  async function step(name, body, page) {
    try {
      await body();
    } catch (e) {
      await page?.screenshot({ path: join(SHOTS, `failed-${name.split(' ')[0]}.png`) }).catch(() => {});
      check(name, false, `${String(e).slice(0, 300)} at ${page?.url() ?? 'no page'}`);
    }
  }

  const accountsTab = async (page, consoleUrl) => {
    await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(APP)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByTestId('app-tab-accounts').click({ timeout: 90_000 });
    await page.getByTestId('account-Retail org').waitFor({ timeout: 60_000 });
  };
  const shot = (page, name) => page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true });

  await withUiStack(
    async (consoleUrl) => {
      mkdirSync(SHOTS, { recursive: true });
      const sam = as(await tokenFor('s.adeyemi@harborpine.example'), 'team_security');
      const priya = as(await tokenFor(PRIYA), 'team_ops');
      await call('POST', '/v1/egress/ranges', sam, { value: sf.range, note: 'uc-703' });
      const on = await call('PUT', `/v1/apps/${encodeURIComponent(APP)}/team`, priya, { enabled: true, signIn: 'person_or_team', accountName: 'Retail org', settings: { login_url: sf.login_url } });
      const eu = await call('POST', `/v1/apps/${encodeURIComponent(APP)}/accounts`, priya, { name: 'EU org', settings: { login_url: sf.eu_login_url } });
      check('0 Salesforce has Retail org and EU org', on.status === 200 && eu.status === 201, { on: on.text, eu: eu.text });
      const browser = await chromium.launch();
      try {
        for (const width of [1440, 390]) {
          const page = await signedIn(browser, consoleUrl, PRIYA, width);
          await step(`1 at ${width} an admin's Accounts tab has Add account in its toolbar, each row says where it points, and the header adds nothing`, async () => {
            await accountsTab(page, consoleUrl);
            const add = page.getByTestId('app-add-account');
            await add.waitFor({ timeout: 30_000 });
            const enabled = await add.isEnabled();
            const header = await page.getByTestId('app-connect').count();
            const eu = ((await page.getByTestId('account-org-EU org').innerText({ timeout: 10_000 })) ?? '').trim();
            const retail = ((await page.getByTestId('account-org-Retail org').innerText({ timeout: 10_000 })) ?? '').trim();
            let stacked = true;
            if (width === 390) {
              // The button has its own row under the search, so the search keeps its width.
              const search = await page.getByPlaceholder('Search accounts…').boundingBox();
              const button = await add.boundingBox();
              stacked = Boolean(search && button && button.y >= search.y + search.height - 1 && search.width > 200);
            }
            await shot(page, `accounts-admin-${width}`);
            check(`1 at ${width} an admin's Accounts tab has Add account in its toolbar, each row says where it points, and the header adds nothing`, enabled && header === 0 && eu.includes('kestrel-eu.my.salesforce.test') && retail.includes('kestrel.my.salesforce.test') && stacked, { enabled, header, eu, retail, stacked });
          }, page);
          if (width === 1440) {
            await step('2 Add account opens the Connect window asking the account name first', async () => {
              await page.getByTestId('app-add-account').click();
              const name = page.getByTestId('connect-window-name');
              await name.waitFor({ timeout: 30_000 });
              await shot(page, `add-account-admin-${width}`);
              check('2 Add account opens the Connect window asking the account name first', await name.isVisible(), 'name field visible');
              await page.keyboard.press('Escape');
            }, page);
            const settings = async (name) => {
              await page.getByTestId(`account-menu-${name}`).click();
              await page.getByTestId(`account-action-Settings-${name}`).click();
              await page.getByTestId('account-settings').waitFor({ timeout: 30_000 });
            };
            await step('7 Settings opens apart from Connect with where the account points, who signs in and how many of the team signed in', async () => {
              await settings('Retail org');
              const points = (await page.getByTestId('account-settings-points').innerText()).trim();
              const count = (await page.getByTestId('who-signed-in-count').innerText({ timeout: 10_000 })).trim();
              const connect = await page.getByTestId('connect-window-name').count();
              await shot(page, `account-settings-admin-${width}`);
              check('7 Settings opens apart from Connect with where the account points, who signs in and how many of the team signed in', points.includes('kestrel.my.salesforce.test') && /^0 of \d+ people signed in$/.test(count) && connect === 0, { points, count, connect });
            }, page);
            await step('8 changing who signs in warns with the count of what names the account before saving', async () => {
              await page.getByText('Shared team login').click();
              const warn = page.getByTestId('account-who-uses');
              await warn.waitFor({ timeout: 30_000 });
              await page.waitForFunction(() => !document.querySelector('[data-testid="account-who-uses"]')?.textContent?.startsWith('Checking'), null, { timeout: 30_000 });
              const text = (await warn.innerText()).trim();
              await shot(page, `account-settings-who-warning-${width}`);
              check('8 changing who signs in warns with the count of what names the account before saving', text === 'No workflow or agent names it.' || /published and \d+ draft versions name Retail org/.test(text), text);
              await page.keyboard.press('Escape');
            }, page);
            await step('9 while the count loads and when it cannot be read the dialog says so instead of a number', async () => {
              let release;
              const held = new Promise((r) => (release = r));
              await page.route('**/v1/workflows/definitions/account-uses**', async (route) => { await held; await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ success: false, error: { code: 'unavailable', message: 'down' } }) }); });
              await settings('EU org');
              await page.getByTestId('account-settings-name').fill('Europe org');
              const loading = (await page.getByTestId('account-rename-uses').innerText({ timeout: 10_000 })).trim();
              await shot(page, `account-settings-slow-${width}`);
              release();
              await page.waitForFunction(() => document.querySelector('[data-testid="account-rename-uses"]')?.textContent?.startsWith('Couldn'), null, { timeout: 60_000 });
              const failed = (await page.getByTestId('account-rename-uses').innerText()).trim();
              await shot(page, `account-settings-error-${width}`);
              await page.unroute('**/v1/workflows/definitions/account-uses**');
              check('9 while the count loads and when it cannot be read the dialog says so instead of a number', loading.startsWith('Checking') && failed.startsWith('Couldn’t check'), { loading, failed });
            }, page);
            await step('10 saving a new name renames the row', async () => {
              await page.getByTestId('account-settings-save').click();
              await page.getByTestId('account-Europe org').waitFor({ timeout: 30_000 });
              const back = await call('GET', `/v1/apps/${encodeURIComponent(APP)}`, priya);
              const names = (back.data?.accounts ?? []).filter((a) => a.kind === 'team').map((a) => a.name).sort();
              check('10 saving a new name renames the row', JSON.stringify(names) === JSON.stringify(['Europe org', 'Retail org']), names);
              // Back to EU org, which the 390 pass reads.
              const europe = (back.data?.accounts ?? []).find((a) => a.name === 'Europe org');
              if (europe) await call('PATCH', `/v1/apps/${encodeURIComponent(APP)}/accounts/${europe.id}`, priya, { revision: europe.revision, name: 'EU org' });
            }, page);
            await step('11 an app page that cannot load says so, and an app with no accounts shows the empty state', async () => {
              const route = `**/v1/apps/${encodeURIComponent(APP)}`;
              await page.route(route, (r) => r.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ success: false, error: { code: 'unavailable', message: 'The tools service is not answering.' } }) }));
              await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(APP)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
              await page.getByText('Couldn’t load this app').waitFor({ timeout: 90_000 });
              await shot(page, `accounts-error-${width}`);
              await page.unroute(route);
              await page.route(route, async (r) => {
                const real = await r.fetch();
                const body = await real.json();
                body.data.accounts = [];
                await r.fulfill({ response: real, body: JSON.stringify(body) });
              });
              await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(APP)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
              await page.getByTestId('app-tab-accounts').click({ timeout: 90_000 });
              const empty = await page.getByTestId('app-accounts-empty').waitFor({ timeout: 60_000 }).then(() => true, () => false);
              await shot(page, `accounts-empty-${width}`);
              await page.unrouteAll({ behavior: 'ignoreErrors' });
              check('11 an app page that cannot load says so, and an app with no accounts shows the empty state', empty, { empty });
            }, page);
            await step('12 an agent’s Account picker says when the team’s apps cannot be read, and otherwise lists each org with where it points', async () => {
              const made = await fetch(`${agentsUrl}/v1/agents`, { method: 'POST', headers: priya, body: JSON.stringify({ name: 'Case desk', role: 'Answers the team about cases' }) });
              const agent = (await made.json())?.data;
              const appsList = (url) => new URL(url).pathname === '/v1/apps';
              await page.route(appsList, (r) => r.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ success: false, error: { code: 'unavailable', message: 'down' } }) }));
              await page.goto(`${consoleUrl}/agents/${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
              const refused = await page.getByTestId('agent-accounts-app-error').waitFor({ timeout: 90_000 }).then(() => true, () => false);
              await page.getByTestId('agent-accounts-app').scrollIntoViewIfNeeded().catch(() => {});
              await page.screenshot({ path: join(SHOTS, `agent-account-error-${width}.png`) });
              await page.unrouteAll({ behavior: 'ignoreErrors' });
              const seen = [];
              page.on('response', async (r) => { if (appsList(r.url())) seen.push([r.status(), r.url().slice(0, 120), (await r.text().catch(() => '')).slice(0, 200)]); });
              await page.reload({ waitUntil: 'domcontentloaded' });
              const trigger = page.getByTestId('agent-accounts-app');
              await trigger.waitFor({ timeout: 90_000 });
              await page.waitForFunction(() => !document.querySelector('[data-testid="agent-accounts-app"]')?.hasAttribute('aria-busy'), null, { timeout: 60_000 }).catch(() => {});
              const said = ((await trigger.innerText()) ?? '').trim();
              if (await trigger.isDisabled()) throw new Error(`the App picker is disabled and reads "${said}"; GET /v1/apps answered ${JSON.stringify(seen)}`);
              await trigger.click({ timeout: 30_000 });
              await page.getByRole('option', { name: 'Salesforce' }).click();
              await page.getByTestId('agent-accounts-account').click();
              const eu = ((await page.getByTestId('agent-accounts-account-EU org').innerText({ timeout: 30_000 })) ?? '').replace(/\s+/g, ' ');
              await page.screenshot({ path: join(SHOTS, `agent-account-picker-${width}.png`) });
              await page.keyboard.press('Escape');
              check('12 an agent’s Account picker says when the team’s apps cannot be read, and otherwise lists each org with where it points', made.status === 201 && refused && eu.includes('kestrel-eu.my.salesforce.test'), { made: made.status, refused, eu });
            }, page);
          } else {
            await step(`7 at ${width} Settings fits the phone with every field reachable`, async () => {
              await page.getByTestId('account-menu-Retail org').click();
              await page.getByTestId('account-action-Settings-Retail org').click();
              await page.getByTestId('account-settings').waitFor({ timeout: 30_000 });
              await page.getByTestId('account-settings-save').scrollIntoViewIfNeeded();
              const wide = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
              await shot(page, `account-settings-admin-${width}`);
              check(`7 at ${width} Settings fits the phone with every field reachable`, wide <= 0 && (await page.getByTestId('account-settings-save').isVisible()), { wide });
              await page.keyboard.press('Escape');
            }, page);
          }
          check(`3 at ${width} no page errors for the admin`, page.errors.length === 0, page.errors.slice(0, 3));
          await page.context().close();
        }
        for (const width of [1440, 390]) {
          const page = await signedIn(browser, consoleUrl, MAYA, width);
          await step(`4 at ${width} a member sees the team's accounts with no Add account and no Delete or Settings`, async () => {
            await accountsTab(page, consoleUrl);
            const add = await page.getByTestId('app-add-account').count();
            const menus = page.locator('[data-testid^="account-menu-"]');
            let manage = 0;
            for (let i = 0; i < (await menus.count()); i++) {
              await menus.nth(i).click();
              manage += await page.locator('[data-testid^="account-action-Delete-"], [data-testid^="account-action-Settings-"]').count();
              await page.keyboard.press('Escape');
            }
            await shot(page, `accounts-member-${width}`);
            check(`4 at ${width} a member sees the team's accounts with no Add account and no Delete or Settings`, add === 0 && manage === 0, { add, manage });
          }, page);
          await step(`5 at ${width} a member's Connectors > Mine opens`, async () => {
            await page.goto(`${consoleUrl}/integrations/my-accounts`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
            await page.getByTestId('connectors').or(page.getByTestId('connectors-empty')).first().waitFor({ timeout: 60_000 });
            await shot(page, `mine-member-${width}`);
            check(`5 at ${width} a member's Connectors > Mine opens`, true);
          }, page);
          check(`6 at ${width} no page errors for the member`, page.errors.length === 0, page.errors.slice(0, 3));
          await page.context().close();
        }
      } finally {
        await browser.close();
      }
    },
    {
      platform: true,
      tools: {
        env: {
          OPS_EGRESS_CA_FILE: sf.settings.OPS_EGRESS_CA_FILE,
          OPS_EGRESS_RESOLVE: sf.settings.OPS_EGRESS_RESOLVE,
          OPS_PLUGINS: 'true',
          OPS_PLUGIN_PATHS: JSON.stringify([SALESFORCE]),
          OPS_PLUGIN_CLIENTS: JSON.stringify({ 'opsai.salesforce': { id: 'ops-ai-acme', secret: 'acme-app' } }),
        },
      },
    },
  );
} finally {
  await stopFake(fake);
}
finish();
