// uc-674 An app's page shows one state and its next action, ui layer: docs/usecases/tools-service/app-page-one-state.md.
// The install loads GitHub and Salesforce, with Ops AI's own app for Salesforce only, so GitHub has nothing to sign in
// through until a team adds an auth config. Sam (Security admin) adds one from GitHub's page and turns it on; Priya
// (Operations admin) turns Salesforce off and on again; a member of each team and both admins open each app's page and
// an app the install does not hold. Every page is read for errors: page errors, console errors and failed /v1 calls.
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const agents = `http://127.0.0.1:${AGENTS_PORT}`;
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
    const turnedOn = await on.json();
    // The team's assistant gets Salesforce's read tools, as the Turn on window's box gives them, so the chat picker
    // lists Salesforce once it is on.
    const given = await fetch(`${agents}/v1/team-assistant/app-tools`, { method: 'POST', headers: priya, body: JSON.stringify({ moduleIds: turnedOn.data?.moduleIds ?? [] }) });
    check('0 Salesforce is on for Operations, its read tools given to the assistant, before the walk', on.status === 200 && given.status < 300, { on: on.status, given: given.status });
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
          shown === 'Needs an auth config' && add && settings.state === 'needs_auth_config' && settings.text.includes('GitHub is off, with no auth config yet') && errs().length === 0,
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

      // One state, three places: after a change on the app page, Mine and the chat picker read the same words.
      await step('8 Turned off on its page, Salesforce reads the same state on Mine and in the chat picker; on again, Mine matches the page', async () => {
        const mineLabel = async () => {
          await priyaPage.goto(`${consoleUrl}/integrations/my-accounts`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const b = priyaPage.getByTestId(`connector-state-${SF}`);
          await b.waitFor({ timeout: 60_000 });
          return (await b.innerText()).trim();
        };
        const pickerLabel = async () => {
          await priyaPage.goto(`${consoleUrl}/chat`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await priyaPage.getByTestId('connectors-picker').click({ timeout: 60_000 });
          const row = priyaPage.locator(`[data-testid$="-${SF}"][data-state]`).first();
          await row.waitFor({ timeout: 30_000 });
          const label = await row.getAttribute('data-state');
          await priyaPage.keyboard.press('Escape');
          return label;
        };
        await open(priyaPage, consoleUrl, SF);
        await settingsState(priyaPage);
        await priyaPage.getByTestId('app-off').click();
        await priyaPage.getByTestId('app-off-confirm').click();
        await priyaPage.getByTestId('app-settings-turn-on').waitFor({ timeout: 30_000 });
        const off = { page: await badge(priyaPage), mine: await mineLabel(), chat: await pickerLabel() };
        await open(priyaPage, consoleUrl, SF);
        await settingsState(priyaPage);
        await priyaPage.getByTestId('app-settings-turn-on').click();
        await priyaPage.getByTestId('app-off').waitFor({ timeout: 30_000 });
        // Read straight after Turn on, with no reload: every surface was refreshed by the change.
        const on = { page: await badge(priyaPage), mine: await mineLabel(), chat: await pickerLabel() };
        await priyaPage.screenshot({ path: join(SHOTS, 'mine-after-turn-on.png') });
        check('8 Turned off on its page, Salesforce reads the same state on Mine and in the chat picker; on again, Mine matches the page',
          off.page === 'Available' && off.mine === off.page && off.chat === off.page && on.page !== 'Available' && on.mine === on.page && on.chat === on.page,
          { off, on });
      }, priyaPage);

      await step('4 An app the install does not hold says so, with no failed call', async () => {
        const errs = await open(priyaPage, consoleUrl, GONE);
        const alert = (await priyaPage.getByTestId('app-removed').innerText()).replace(/\s+/g, ' ');
        const shown = await badge(priyaPage);
        await priyaPage.screenshot({ path: join(SHOTS, 'not-installed.png') });
        check('4 An app the install does not hold says so, with no failed call',
          shown === 'Not installed' && alert.includes('isn’t installed') && alert.includes('runs Ops AI at your company') && errs().length === 0,
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
      // Someone who cannot set an app up reads one line on Mine and has no Settings tab on its page.
      await step('9 A viewer reads one line on Mine (not set up, ask an admin) and the app page has no Settings tab', async () => {
        await ravi.goto(`${consoleUrl}/integrations/my-accounts`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const card = ravi.getByTestId(`connector-${GH}`);
        await card.waitFor({ timeout: 60_000 });
        const text = (await card.innerText()).replace(/\s+/g, ' ');
        const badgeText = (await ravi.getByTestId(`connector-state-${GH}`).innerText()).trim();
        await ravi.screenshot({ path: join(SHOTS, 'mine-viewer.png') });
        await open(ravi, consoleUrl, GH);
        const settingsTab = await ravi.getByTestId('app-tab-settings').count();
        check('9 A viewer reads one line on Mine (not set up, ask an admin) and the app page has no Settings tab',
          badgeText === 'Not set up for your team yet' && /Ask an admin/.test(text) && !/Needs an auth config|No account connected|admin turns it on|sets it up first/.test(text) && settingsTab === 0,
          { badgeText, text, settingsTab });
      }, ravi);

      // Words follow the reader's role and say whose state they are.
      await step('10 Each role reads its own words: the picker, who to ask, whose state, and a missing app’s page', async () => {
        const picker = async (page) => {
          await page.goto(`${consoleUrl}/chat`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId('connectors-picker').click({ timeout: 60_000 });
          const row = page.getByTestId(`connector-off-${GH}`);
          await row.waitFor({ timeout: 30_000 });
          const seen = { text: (await row.innerText()).replace(/\s+/g, ' '), action: await page.getByTestId(`connector-off-action-${GH}`).count() };
          await page.keyboard.press('Escape');
          return seen;
        };
        const adminPicker = await picker(priyaPage);
        const viewerPicker = await picker(ravi);
        // Who a viewer asks: someone granted in the team, never an admin of every team.
        await ravi.goto(`${consoleUrl}/integrations/my-accounts`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await ravi.getByTestId(`connector-ask-${GH}`).waitFor({ timeout: 60_000 });
        const ask = (await ravi.getByTestId(`connector-ask-${GH}`).innerText()).trim();
        // Whose state: on an app each person signs in to, the header is the reader's and the team's row says so.
        const errs = await open(nadia, consoleUrl, GH);
        const whose = (await nadia.getByTestId('app-status-whose').innerText()).replace(/\s+/g, ' ').trim();
        const row = (await nadia.locator('[data-testid^="account-state-"]').first().locator('xpath=..').innerText()).replace(/\s+/g, ' ');
        // A missing app's page: no resources asked for, one line; the admin reads who installs apps and how.
        const gone = await open(priyaPage, consoleUrl, GONE);
        await priyaPage.getByTestId('app-tab-resources').click();
        const line = await priyaPage.getByTestId('app-resources-not-installed').innerText({ timeout: 30_000 });
        const how = await priyaPage.getByTestId('app-removed-how').count();
        await priyaPage.waitForTimeout(1000);
        await open(ravi, consoleUrl, GONE);
        const viewerHow = await ravi.getByTestId('app-removed-how').count();
        await priyaPage.screenshot({ path: join(SHOTS, 'missing-app-resources.png') });
        check('10 Each role reads its own words: the picker, who to ask, whose state, and a missing app’s page',
          adminPicker.action === 1 && !/ask an admin/i.test(adminPicker.text) && viewerPicker.action === 0 && /ask an admin/i.test(viewerPicker.text) &&
            /Ask an admin: (James Richardson|Priya Shah)/.test(ask) && !/Dev Admin/.test(ask) &&
            /^You:/.test(whose) && /Team account:/.test(row) && errs().length === 0 &&
            /isn’t installed/.test(line) && how === 1 && viewerHow === 0 && gone().length === 0,
          { adminPicker, viewerPicker, ask, whose, row, line, how, viewerHow, errors: [...errs(), ...gone()] });
      }, priyaPage);

      // The picker is a fixed width at every screen width, so a row's reason has to wrap under the name, not beside it.
      await step('11 Every app name in the chat picker reads in full, as a member and an admin, at 1440 and 390', async () => {
        const read = async (page, who, width) => {
          await page.setViewportSize({ width, height: 900 });
          await page.goto(`${consoleUrl}/chat`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId('connectors-picker').click({ timeout: 60_000 });
          await page.getByTestId(`connector-off-${GH}`).waitFor({ timeout: 30_000 });
          // The list fades and zooms in; read and shoot it once it has settled.
          await page.getByTestId('connectors-picker-list').evaluate((el) => Promise.all(el.getAnimations({ subtree: true }).map((a) => a.finished)));
          const rows = await page.getByTestId('connectors-picker-list').locator('[data-testid^="connector-"][data-state]').evaluateAll((els) =>
            els.map((el) => {
              const name = el.querySelector('span.truncate');
              return { name: name?.textContent ?? '', cut: !name || name.scrollWidth > name.clientWidth, ask: /ask an admin/i.test(el.textContent ?? '') };
            }),
          );
          await page.screenshot({ path: join(SHOTS, `picker-${who}-${width}.png`) });
          await page.keyboard.press('Escape');
          return rows;
        };
        const seen = {};
        for (const [who, page] of [['member', ravi], ['admin', priyaPage]]) for (const width of [1440, 390]) seen[`${who}-${width}`] = await read(page, who, width);
        await ravi.setViewportSize({ width: 1280, height: 900 });
        await priyaPage.setViewportSize({ width: 1280, height: 900 });
        const cut = Object.entries(seen).flatMap(([k, rows]) => rows.filter((r) => r.cut).map((r) => `${k}: ${r.name}`));
        check('11 Every app name in the chat picker reads in full, as a member and an admin, at 1440 and 390',
          Object.values(seen).every((rows) => rows.length > 0) && seen['member-1440'].some((r) => r.ask) && cut.length === 0,
          { cut, seen });
      }, ravi);

      // Auth configs are a builder's and an admin's: a viewer's page has no Auth configs tab and no Auth config column.
      // An admin's Accounts tab shows the column only when opened from a config's account count (the drilldown), so
      // the plain list keeps its room for the state and the row's actions.
      await step('7 A viewer sees no auth config, by tab, column or name; an admin sees the tab, and the column from a config’s count', async () => {
        const columnCount = (page) => page.getByRole('columnheader', { name: 'Auth config' }).count();
        const configsOf = async (page) => {
          await open(page, consoleUrl, SF);
          await page.getByTestId('app-tab-accounts').click();
          await page.waitForTimeout(800);
          return { tab: await page.getByTestId('app-tab-auth').count(), column: await columnCount(page), named: (await page.locator('main').innerText()).includes('Ops AI’s app') };
        };
        const viewer = await configsOf(ravi);
        const admin = await configsOf(priyaPage);
        // The drilldown: Auth configs › a config's account count opens Accounts filtered to it, with the column.
        await priyaPage.getByTestId('app-tab-auth').click();
        await priyaPage.locator('[data-testid^="auth-config-accounts-"]:enabled').first().click({ timeout: 30_000 });
        await priyaPage.waitForTimeout(800);
        admin.drilldownColumn = await columnCount(priyaPage);
        check('7 A viewer sees no auth config, by tab, column or name; an admin sees the tab, and the column from a config’s count',
          viewer.tab === 0 && viewer.column === 0 && !viewer.named && admin.tab === 1 && admin.column === 0 && admin.drilldownColumn === 1,
          { viewer, admin });
      }, ravi);
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
        OPS_PLUGINS: 'true',
        OPS_PLUGIN_PATHS: JSON.stringify([join(PLUGINS, 'github/src/ops_plugin_github'), join(PLUGINS, 'salesforce/src/ops_plugin_salesforce')]),
        // Ops AI's own app for Salesforce only: GitHub signs in through a team's auth config or not at all.
        OPS_PLUGIN_CLIENTS: JSON.stringify({ 'opsai.salesforce': { id: 'ops-ai-acme', secret: 'acme-connected-app-secret' } }),
      },
    },
  },
);
finish();
