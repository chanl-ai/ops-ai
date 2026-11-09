// uc-674 An app's page shows one state and its next action, ui layer: docs/usecases/tools-service/app-page-one-state.md.
// The install loads GitHub and Salesforce, with Ops AI's own app for Salesforce only, so GitHub has nothing to sign in
// through until a team adds an auth config. Sam (Security admin) adds one from GitHub's page and turns it on; Priya
// (Operations admin) turns Salesforce off and on again; a member of each team and both admins open each app's page and
// an app the install does not hold. Every page is read for errors: page errors, console errors and failed /v1 calls.
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const PASSWORD = 'northfield-demo';
const SHOTS = process.env.OPS_USECASE_SHOTS || evidenceDir('674', 'uc');
const PLUGINS = join(process.env.OPS_PLUGINS_REPO || join(ROOT, '..', 'ops-ai-plugins'), 'plugins');
const GH = 'plugin:opsai.github';
const SF = 'plugin:opsai.salesforce';
const GONE = 'plugin:acme.ticketdesk';

const tokenFor = async (email) => (await (await fetch(`${platform}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token, team) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });

/** A signed-in page that records every error: thrown, logged, and each /v1 call that failed. */
async function signedIn(browser, consoleUrl, email, team) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  // The team the console works as is kept per tab (lib/api/team-context.ts); Priya belongs to several.
  await context.addInitScript((t) => sessionStorage.setItem('ops-team', t), team);
  const page = await context.newPage();
  page.errors = [];
  page.on('pageerror', (e) => page.errors.push(`pageerror ${e.message}`));
  page.on('console', (m) => m.type() === 'error' && page.errors.push(`console ${m.text().slice(0, 200)}`));
  page.on('response', (r) => r.status() >= 400 && new URL(r.url()).pathname.startsWith('/v1/') && page.errors.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Work email').fill(email, { timeout: 120_000 });
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByTestId('login-submit').click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

const appUrl = (consoleUrl, id) => `${consoleUrl}/integrations/apps/${encodeURIComponent(id)}`;

/** Opens an app's page and waits for it to settle; the errors it raised are those since `from`. */
async function open(page, consoleUrl, id) {
  const from = page.errors.length;
  await page.goto(appUrl(consoleUrl, id), { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByTestId('app-tabs-row').or(page.getByTestId('app-removed')).first().waitFor({ timeout: 90_000 });
  await page.waitForLoadState('networkidle', { timeout: 30_000 }).catch(() => {});
  await page.waitForTimeout(1500);
  return () => page.errors.slice(from);
}

const badge = async (page) => (await page.getByTestId('app-status').innerText({ timeout: 30_000 })).trim();
async function settingsState(page) {
  await page.getByTestId('app-tab-settings').click();
  const row = page.getByTestId('app-on-for-team');
  await row.waitFor({ timeout: 30_000 });
  return { state: await row.getAttribute('data-state'), text: (await row.innerText()).replace(/\s+/g, ' ') };
}

async function step(name, body, page) {
  try {
    await body();
  } catch (e) {
    await page?.screenshot({ path: join(SHOTS, `failed-${name.replace(/\W+/g, '-').slice(0, 40)}.png`) }).catch(() => {});
    check(name, false, `${String(e).slice(0, 300)} at ${page?.url() ?? 'no page'}`);
  }
}

await withUiStack(
  async (consoleUrl) => {
    mkdirSync(SHOTS, { recursive: true });
    const priya = as(await tokenFor('p.shah@harborpine.example'), 'team_ops');
    const on = await fetch(`${tools}/v1/apps/${encodeURIComponent(SF)}/team`, { method: 'PUT', headers: priya, body: JSON.stringify({ enabled: true, signIn: 'person_or_team', settings: { login_url: 'https://login.salesforce.com/services/oauth2' } }) });
    check('0 Salesforce is on for Operations before the walk', on.status === 200, await on.text());
    const browser = await chromium.launch();
    const counts = {};
    try {
      const sam = await signedIn(browser, consoleUrl, 's.adeyemi@harborpine.example', 'team_security');
      await step('1 GitHub with no auth config says to add one, and its page makes no failed call', async () => {
        const errs = await open(sam, consoleUrl, GH);
        const shown = await badge(sam);
        const add = await sam.getByTestId('add-auth-config').isVisible();
        const settings = await settingsState(sam);
        await sam.screenshot({ path: join(SHOTS, 'github-needs-auth-config.png') });
        check('1 GitHub with no auth config says to add one, and its page makes no failed call',
          shown === 'Needs an auth config' && add && settings.state === 'needs_auth_config' && settings.text.includes('Add an auth config for GitHub first.') && errs().length === 0,
          { shown, add, settings, errors: errs() });
      }, sam);

      await step('2 Adding the auth config signs nobody in; Turn on then saves and both header and Settings read on', async () => {
        const errs = await open(sam, consoleUrl, GH);
        const pages = sam.context().pages().length;
        await sam.getByTestId('add-auth-config').click();
        await sam.getByTestId('new-credential-client-id').fill('gh-team-client');
        await sam.getByTestId('new-credential-client-secret').fill('gh-team-secret');
        await sam.getByTestId('new-credential-create').click();
        await sam.getByTestId('new-credential').waitFor({ state: 'hidden', timeout: 30_000 });
        await sam.getByTestId('app-connect').waitFor({ timeout: 30_000 });
        const afterAdd = await badge(sam);
        await sam.getByTestId('app-connect').click();
        await sam.getByTestId('connect-window').waitFor({ timeout: 30_000 });
        await sam.getByTestId('connect-window-authorize').click();
        await sam.getByTestId('connect-window-done').waitFor({ timeout: 60_000 });
        await sam.getByTestId('connect-window-done').click();
        await sam.getByTestId('connect-window').waitFor({ state: 'hidden', timeout: 30_000 });
        await sam.waitForTimeout(1500);
        const shown = await badge(sam);
        const settings = await settingsState(sam);
        await sam.screenshot({ path: join(SHOTS, 'github-turned-on.png') });
        check('2 Adding the auth config signs nobody in; Turn on then saves and both header and Settings read on',
          afterAdd === 'Available' && shown === 'Needs sign-in' && settings.state === 'needs_sign_in' && settings.text.includes('GitHub is on') && sam.context().pages().length === pages && errs().length === 0,
          { afterAdd, shown, settings, popups: sam.context().pages().length - pages, errors: errs() });
      }, sam);

      const priyaPage = await signedIn(browser, consoleUrl, 'p.shah@harborpine.example', 'team_ops');
      await step('3 Turned off, Salesforce reads off in the header and Settings; Turn on puts both back on', async () => {
        const errs = await open(priyaPage, consoleUrl, SF);
        const before = await settingsState(priyaPage);
        await priyaPage.getByTestId('app-off').click();
        await priyaPage.getByTestId('app-off-confirm').click();
        await priyaPage.getByTestId('app-settings-turn-on').waitFor({ timeout: 30_000 });
        const offBadge = await badge(priyaPage);
        const off = await settingsState(priyaPage);
        const headerTurnOn = await priyaPage.getByTestId('app-connect').isVisible();
        await priyaPage.screenshot({ path: join(SHOTS, 'salesforce-off.png') });
        const pages = priyaPage.context().pages().length;
        await priyaPage.getByTestId('app-settings-turn-on').click();
        await priyaPage.getByTestId('app-off').waitFor({ timeout: 30_000 });
        const onBadge = await badge(priyaPage);
        const back = await settingsState(priyaPage);
        check('3 Turned off, Salesforce reads off in the header and Settings; Turn on puts both back on',
          before.text.includes('Salesforce is on') && offBadge === 'Available' && off.state === 'off' && off.text.includes('Salesforce is off') && headerTurnOn &&
            onBadge !== 'Available' && back.text.includes('Salesforce is on') && back.state === before.state && priyaPage.context().pages().length === pages && errs().length === 0,
          { before, offBadge, off, headerTurnOn, onBadge, back, errors: errs() });
      }, priyaPage);

      await step('4 An app the install does not hold says so, with no failed call', async () => {
        const errs = await open(priyaPage, consoleUrl, GONE);
        const alert = (await priyaPage.getByTestId('app-removed').innerText()).replace(/\s+/g, ' ');
        const shown = await badge(priyaPage);
        await priyaPage.screenshot({ path: join(SHOTS, 'not-installed.png') });
        check('4 An app the install does not hold says so, with no failed call',
          shown === 'Not installed' && alert.includes('isn’t installed') && alert.includes('Your operator installs apps') && errs().length === 0,
          { shown, alert, errors: errs() });
      }, priyaPage);

      // Every app page, as an admin and a member of each team: zero errors on each.
      const nadia = await signedIn(browser, consoleUrl, 'n.petrov@harborpine.example', 'team_security');
      const ravi = await signedIn(browser, consoleUrl, 'r.menon@harborpine.example', 'team_ops');
      for (const [who, page] of [['Sam, Security admin', sam], ['Nadia, Security member', nadia], ['Priya, Operations admin', priyaPage], ['Ravi, Operations member', ravi]]) {
        for (const id of [GH, SF, GONE]) {
          await step(`5 ${who} opens ${id}`, async () => {
            const errs = await open(page, consoleUrl, id);
            counts[`${who} · ${id}`] = errs().length;
            if (errs().length) counts[`${who} · ${id} · errors`] = errs();
          }, page);
        }
      }
      console.log(`console errors per page: ${JSON.stringify(counts)}`);
      const pagesWithErrors = Object.entries(counts).filter(([k, v]) => !k.endsWith('errors') && v !== 0);
      check('5 Every app page shows zero console errors as an admin and as a member', Object.keys(counts).length >= 12 && pagesWithErrors.length === 0, counts);
      const member = await (async () => {
        await open(nadia, consoleUrl, GH);
        return { badge: await badge(nadia), ask: await nadia.getByTestId('app-admin-connects').isVisible().catch(() => false), own: await nadia.getByTestId('app-own-sign-in').isVisible().catch(() => false) };
      })();
      check('6 A member reads their own state: GitHub needs their sign-in and offers Sign in from Mine, not the admin actions', member.badge === 'Needs sign-in' && member.own, member);
    } finally {
      await browser.close();
    }
  },
  {
    platform: true,
    tools: {
      env: {
        OPS_PLUGINS: 'true',
        OPS_PLUGIN_PATHS: JSON.stringify([join(PLUGINS, 'github/src/ops_plugin_github'), join(PLUGINS, 'salesforce/src/ops_plugin_salesforce')]),
        // Ops AI's own app for Salesforce only: GitHub signs in through a team's auth config or not at all.
        OPS_PLUGIN_CLIENTS: JSON.stringify({ 'opsai.salesforce': { id: 'ops-ai-acme', secret: 'acme-connected-app-secret' } }),
      },
    },
  },
);
finish();
