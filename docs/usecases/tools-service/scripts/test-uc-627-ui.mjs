// uc-627 A team connects Salesforce at its company address, ui layer: docs/usecases/tools-service/salesforce-org-address.md.
// Priya adds an auth config holding the org's My Domain from the console's own form, connects Salesforce with it
// against the fake Salesforce, sees the account Connected with its org address, and runs a SOQL query from the tool's
// Test. Security allows the fake's private range only. Screenshots go to OPS_USECASE_SHOTS when set (the evidence
// folder otherwise), at 1280 and 390.
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { createInterface } from 'node:readline';
import { join } from 'node:path';

import { PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

import { openSignIn } from '../../lib/connection_ui.mjs';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const PASSWORD = 'northfield-demo';
const PRIYA = 'p.shah@harborpine.example';
const SHOTS = process.env.OPS_USECASE_SHOTS || evidenceDir('627', 'uc');
const SALESFORCE = process.env.OPS_SALESFORCE_PLUGIN || join(process.env.OPS_PLUGINS_REPO || join(ROOT, '..', 'ops-ai-plugins'), 'plugins/salesforce/src/ops_plugin_salesforce');
const LIB = join(ROOT, 'docs/usecases/lib');
const APP = 'plugin:opsai.salesforce';
const CONFIG = 'Kestrel org';
const CASE = "SELECT Id, CaseNumber, Status FROM Case WHERE CaseNumber = '00044818'";

/** The fake Salesforce from its script, resolved with the one JSON line it prints once it serves. */
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

/** Closes the fake's stdin, its cue to remove the sign-in container, and waits for it to exit. */
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
  const resolve = JSON.parse(sf.settings.OPS_EGRESS_RESOLVE);
  const myDomain = new URL(sf.login_url).host;

  const tokenFor = async (email) => (await (await fetch(`${platform}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
  const as = (token, team) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
  const call = async (method, path, headers, body) => {
    const r = await fetch(`${tools}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    const json = await r.json().catch(() => null);
    return { status: r.status, data: json?.data };
  };
  const shot = (page, name, width) => page.screenshot({ path: join(SHOTS, `${name}-${width}.png`), fullPage: true });

  /** A fresh window signed in as `email`, reaching the fake's hosts on this machine's address. */
  async function signedIn(browser, consoleUrl, email, width) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, ignoreHTTPSErrors: true });
    for (const host of sf.hosts) {
      await context.route(`https://${host}/**`, async (route) => {
        const u = new URL(route.request().url());
        const response = await route.fetch({ url: `https://${resolve[host]}${u.pathname}${u.search}`, headers: { ...route.request().headers(), host }, maxRedirects: 0 });
        await route.fulfill({ response });
      });
    }
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

  /** One check; a failure keeps the page it was on beside the evidence. */
  async function step(name, body, page) {
    try {
      await body();
    } catch (e) {
      await page?.screenshot({ path: join(SHOTS, `failed-${name.split(' ')[0]}.png`) }).catch(() => {});
      check(name, false, `${String(e).slice(0, 300)} at ${page?.url() ?? 'no page'}`);
    }
  }

  const appUrl = (consoleUrl) => `${consoleUrl}/integrations/apps/${encodeURIComponent(APP)}`;

  await withUiStack(
    async (consoleUrl) => {
      mkdirSync(SHOTS, { recursive: true });
      const sam = as(await tokenFor('s.adeyemi@harborpine.example'), 'team_security');
      const priya = as(await tokenFor(PRIYA), 'team_ops');
      await call('POST', '/v1/egress/ranges', sam, { value: sf.range, note: 'uc-627' });
      const browser = await chromium.launch();
      try {
        const page = await signedIn(browser, consoleUrl, PRIYA, 1280);

        await step('7 the console\'s New auth config form saves the org\'s My Domain, fixed, and the row reads it', async () => {
          await page.goto(appUrl(consoleUrl), { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId('app-tab-auth').click({ timeout: 90_000 });
          await page.getByTestId('auth-config-new').click();
          const form = page.getByTestId('new-credential-form');
          await form.waitFor({ timeout: 30_000 });
          await page.getByTestId('new-credential-name').fill(CONFIG);
          await page.getByTestId('new-credential-client-id').fill('ops-ai-acme');
          await page.getByTestId('new-credential-client-secret').fill('acme-connected-app-secret');
          await page.getByTestId('new-credential-setting-login_url').click();
          await page.getByTestId('new-credential-setting-login_url-other').click();
          await page.getByTestId('new-credential-setting-login_url-host').fill(myDomain);
          const mode = ((await page.getByTestId('new-credential-mode-login_url').innerText({ timeout: 10_000 })) ?? '').trim();
          await shot(page, '1-new-auth-config', 1280);
          await page.getByTestId('new-credential-create').click();
          await page.getByTestId('new-credential').waitFor({ state: 'detached', timeout: 30_000 });
          const place = page.getByTestId(`auth-config-place-${CONFIG}`);
          const row = ((await place.innerText({ timeout: 30_000 })) ?? '').replace(/\s+/g, ' ').trim();
          await shot(page, '2-auth-config-row', 1280);
          check('7 the console\'s New auth config form saves the org\'s My Domain, fixed, and the row reads it', /Always sign in here/.test(mode) && row.includes(myDomain) && row.includes('Fixed'), { mode, row });
        }, page);

        let popupUrl = '';
        await step('8 Connect with the config shows its address, asks nothing, and opens the sign-in on the My Domain', async () => {
          const config = ((await call('GET', `/v1/apps/${encodeURIComponent(APP)}`, priya)).data?.authConfigs ?? []).find((c) => c.name === CONFIG);
          await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId(`connect-${APP}`).click({ timeout: 90_000 });
          const win = page.getByTestId('connect-window');
          await win.waitFor({ timeout: 30_000 });
          await win.getByTestId('connect-window-app').click();
          await page.getByTestId(`connect-window-app-option-${config.id}`).click();
          const shown = ((await win.getByTestId('connect-window-config-place').innerText({ timeout: 30_000 })) ?? '').replace(/\s+/g, ' ');
          const asked = await win.getByTestId('connect-window-place-login_url').count();
          await shot(page, '3-connect-window', 1280);
          // The window offers who signs in and defaults to each person; this use case connects the team's own login.
          await win.locator('#who-shared').click();
          // Turn on saves the team's setting with the config; signing in is the saved state's Connect.
          const popup = await openSignIn(page);
          await popup.locator('input[name=username]').waitFor({ timeout: 60_000 });
          popupUrl = popup.url();
          check('8 Connect with the config shows its address, asks nothing, and opens the sign-in on the My Domain', shown.includes(myDomain) && asked === 0 && new URL(popupUrl).host === myDomain, { shown, asked, popupUrl: popupUrl.slice(0, 120) });
          await popup.locator('input[name=username]').fill('kestrel.integration');
          await popup.locator('input[type=submit], button[type=submit]').first().click();
          await popup.waitForEvent('close', { timeout: 60_000 }).catch(() => undefined);
        }, page);

        await step('9 the app reads Connected, and the account shows the org address from the token answer', async () => {
          await page.goto(appUrl(consoleUrl), { waitUntil: 'domcontentloaded' });
          await page.getByTestId('app-status').filter({ hasText: 'Connected' }).waitFor({ timeout: 60_000 });
          await page.getByTestId('app-tab-accounts').click();
          const org = page.locator('[data-testid^="account-org-"]').first();
          const text = ((await org.innerText({ timeout: 30_000 })) ?? '').trim();
          await shot(page, '4-account-connected', 1280);
          check('9 the app reads Connected, and the account shows the org address from the token answer', text.includes(new URL(sf.api_base).host), { text });
        }, page);

        await step('10 the tool\'s Test runs the SOQL query against the org and shows case 00044818', async () => {
          const ops = (await call('GET', '/v1/modules/mod_plugin_salesforce', priya)).data?.operations ?? [];
          const op = ops.find((o) => o.name === 'salesforce_query' || o.id === 'salesforce_query');
          await page.goto(`${consoleUrl}/tools/mod_plugin_salesforce/operations/${op?.id ?? 'salesforce_query'}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId('run-mode').getByText('Real', { exact: true }).click({ timeout: 60_000 });
          await page.locator('#t-q').fill(CASE);
          await page.getByTestId('run').click();
          await page.getByText('Card declined abroad').first().waitFor({ timeout: 60_000 });
          await page.getByText('Card declined abroad').first().scrollIntoViewIfNeeded();
          const said = ((await page.locator('main').innerText()) ?? '').replace(/\s+/g, ' ');
          await page.screenshot({ path: join(SHOTS, '5-tool-test-1280.png') });
          check('10 the tool\'s Test runs the SOQL query against the org and shows case 00044818', said.includes('00044818') && said.includes('Card declined abroad'), { said: said.slice(0, 300) });
        }, page);

        await step('12 at 390 the auth config and the account read the same', async () => {
          const phone = await signedIn(browser, consoleUrl, PRIYA, 390);
          await phone.goto(appUrl(consoleUrl), { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await phone.getByTestId('app-tab-auth').click({ timeout: 90_000 });
          const row = ((await phone.getByTestId(`auth-config-place-${CONFIG}`).innerText({ timeout: 30_000 })) ?? '').replace(/\s+/g, ' ');
          await shot(phone, '2-auth-config-row', 390);
          await phone.getByTestId('app-tab-accounts').click();
          const org = ((await phone.locator('[data-testid^="account-org-"]').first().innerText({ timeout: 30_000 })) ?? '').trim();
          await shot(phone, '4-account-connected', 390);
          const wide = await phone.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
          check('12 at 390 the auth config and the account read the same, with no sideways scroll', row.includes(myDomain) && org.includes(new URL(sf.api_base).host) && !wide, { row, org, wide });
          if (phone.errors.length) page.errors.push(...phone.errors);
          await phone.context().close();
        }, page);

        check('11 no page errors', page.errors.length === 0, page.errors.slice(0, 3));
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
          OPS_PLUGIN_CLIENTS: JSON.stringify({ 'opsai.salesforce': { id: 'ops-ai-acme', secret: 'acme-connected-app-secret' } }),
        },
      },
    },
  );
} finally {
  await stopFake(fake);
}
finish();
