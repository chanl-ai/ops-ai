// uc-707 An account a workflow or agent names is not deleted until nothing names it, ui layer:
// docs/usecases/agents-service/an-account-in-use-is-not-deleted.md. Salesforce has two team accounts (Retail org and EU
// org) and an agent names EU org. Priya deletes EU org from its row's menu at 1440 and 390: the dialog says the delete
// is refused and why, naming the agent, and the row stays. Screenshots go to OPS_USECASE_SHOTS when set.
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
const SHOTS = process.env.OPS_USECASE_SHOTS || evidenceDir('707', 'uc');
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
  const call = async (base, method, path, headers, body) => {
    const r = await fetch(`${base}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    const json = await r.json().catch(() => null);
    return { status: r.status, data: json?.data, text: JSON.stringify(json).slice(0, 300) };
  };
  async function signedIn(browser, consoleUrl, email, width) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, ignoreHTTPSErrors: true, reducedMotion: 'reduce' });
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
  const settled = (page) => page.evaluate(() => Promise.all(document.getAnimations().map((a) => a.finished.catch(() => null))));

  await withUiStack(
    async (consoleUrl) => {
      mkdirSync(SHOTS, { recursive: true });
      const sam = as(await tokenFor('s.adeyemi@harborpine.example'), 'team_security');
      const priya = as(await tokenFor(PRIYA), 'team_ops');
      await call(tools, 'POST', '/v1/egress/ranges', sam, { value: sf.range, note: 'uc-707' });
      const on = await call(tools, 'PUT', `/v1/apps/${encodeURIComponent(APP)}/team`, priya, { enabled: true, signIn: 'team', accountName: 'Retail org', settings: { login_url: sf.login_url } });
      const eu = await call(tools, 'POST', `/v1/apps/${encodeURIComponent(APP)}/accounts`, priya, { name: 'EU org', settings: { login_url: sf.eu_login_url } });
      const agent = await call(agentsUrl, 'POST', '/v1/agents', priya, { name: 'Claims desk', role: 'Answers about claims' });
      const named = await call(agentsUrl, 'PATCH', `/v1/agents/${agent.data?.id}`, priya, { accounts: { [APP]: 'EU org' } });
      check('0 Salesforce has Retail org and EU org, and an agent names EU org', on.status === 200 && eu.status === 201 && named.status === 200, { on: on.text, eu: eu.text, named: named.text });
      const browser = await chromium.launch();
      try {
        for (const width of [1440, 390]) {
          const page = await signedIn(browser, consoleUrl, PRIYA, width);
          const name = `1 at ${width} deleting EU org says it is refused because an agent names it, and the row stays`;
          try {
            await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(APP)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
            await page.getByTestId('app-tab-accounts').click({ timeout: 90_000 });
            await page.getByTestId('account-EU org').waitFor({ timeout: 60_000 });
            await page.getByTestId('account-menu-EU org').click();
            await page.getByTestId('account-action-Delete-EU org').click();
            await page.getByTestId('delete-account-delete-EU org-confirm-btn').click({ timeout: 30_000 });
            const toast = page.locator('[data-sonner-toast]').filter({ hasText: 'Couldn’t delete it' });
            await toast.waitFor({ timeout: 30_000 });
            const said = ((await toast.innerText()) ?? '').replace(/\s+/g, ' ');
            await settled(page);
            await page.screenshot({ path: join(SHOTS, `account-delete-in-use-${width}.png`), fullPage: true });
            const kept = await page.getByTestId('account-EU org').isVisible();
            check(name, /EU org is named by 0 published and 1 draft workflow or agent version\. Change those to another account first\./.test(said) && kept, { said, kept });
          } catch (e) {
            await page.screenshot({ path: join(SHOTS, `failed-707-${width}.png`) }).catch(() => {});
            check(name, false, `${String(e).slice(0, 300)} at ${page.url()}`);
          }
          check(`2 at ${width} no page errors`, page.errors.length === 0, page.errors.slice(0, 3));
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
