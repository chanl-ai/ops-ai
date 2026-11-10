// uc-703 Add account is on the Accounts tab for whoever manages apps, and never for a member, ui layer:
// docs/usecases/tools-service/add-account-lives-on-the-accounts-tab.md. Salesforce has two team accounts (Retail org and
// EU org, at two My Domains of the fake Salesforce). Priya (admin) and Maya (member) open its Accounts tab at 1440 and
// 390; Maya also opens Connectors > Mine. Screenshots go to OPS_USECASE_SHOTS when set (the evidence folder otherwise).
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { createInterface } from 'node:readline';
import { join } from 'node:path';

import { PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
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
          }
          check(`3 at ${width} no page errors for the admin`, page.errors.length === 0, page.errors.slice(0, 3));
          await page.context().close();
        }
        for (const width of [1440, 390]) {
          const page = await signedIn(browser, consoleUrl, MAYA, width);
          await step(`4 at ${width} a member sees the team's accounts with no Add account and no Delete or Rename`, async () => {
            await accountsTab(page, consoleUrl);
            const add = await page.getByTestId('app-add-account').count();
            const menus = page.locator('[data-testid^="account-menu-"]');
            let manage = 0;
            for (let i = 0; i < (await menus.count()); i++) {
              await menus.nth(i).click();
              manage += await page.locator('[data-testid^="account-action-Delete-"], [data-testid^="account-action-Rename-"]').count();
              await page.keyboard.press('Escape');
            }
            await shot(page, `accounts-member-${width}`);
            check(`4 at ${width} a member sees the team's accounts with no Add account and no Delete or Rename`, add === 0 && manage === 0, { add, manage });
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
