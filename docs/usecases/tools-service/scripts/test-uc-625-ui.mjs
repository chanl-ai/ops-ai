// uc-625 Connect comes back Connected in any window, ui layer: docs/usecases/tools-service/sign-in-return-any-window.md.
// Every app that signs in with OAuth (GitHub, Salesforce and the tests' Person desk) is connected through the Connect
// window against a fake of its system, so no real provider is reached: the plugins repo's fake GitHub, the fake
// Salesforce and the fake multi-auth system. Each app is walked through a stale sign-in window left open, a refused
// sign-in, a sign-in window closed early and tried again, and a sign-in finished in a fresh browser with no storage.
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { createInterface } from 'node:readline';
import { join } from 'node:path';

import { PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

import { leaveConnectWindow, openSignIn, signInButton } from '../../lib/connection_ui.mjs';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const PASSWORD = 'northfield-demo';
const PRIYA = 'p.shah@harborpine.example';
const SHOTS = evidenceDir('625', 'uc');
const PLUGINS = join(process.env.OPS_PLUGINS_REPO || join(ROOT, '..', 'ops-ai-plugins'), 'plugins');
const KINDS = join(ROOT, 'services/tools-service/tests/plugin_kinds');
const LIB = join(ROOT, 'docs/usecases/lib');

/** Starts a fake from its script and resolves with the one JSON line it prints once it serves. */
async function startFake(name, script, args = []) {
  const child = spawn('uv', ['run', '--quiet', '--directory', join(ROOT, 'services/agents-service'), 'python', script, ...args], {
    stdio: ['pipe', 'pipe', 'inherit'],
    env: { ...process.env, PYTHONPATH: LIB },
  });
  const line = await new Promise((resolve, reject) => {
    createInterface({ input: child.stdout }).once('line', resolve);
    child.once('exit', (code) => reject(new Error(`${name} exited with ${code}`)));
  });
  return { name, child, info: JSON.parse(line) };
}

/**
 * Closes a fake's stdin, which the docker-backed ones take as the cue to remove their container, and waits for it to
 * exit; `serves` marks one that serves until stopped and has no container, so it is stopped at once.
 */
async function stopFake(fake) {
  if (!fake || fake.child.exitCode !== null) return;
  const exited = new Promise((resolve) => fake.child.once('exit', resolve));
  if (fake.serves) fake.child.kill('SIGTERM');
  else fake.child.stdin.end();
  const timer = setTimeout(() => fake.child.kill('SIGTERM'), 20_000);
  await exited;
  clearTimeout(timer);
}

const fakes = [];
try {
  const github = await startFake('fake GitHub', join(PLUGINS, 'github/tests/fake_github.py'), ['--dir', mkdtempSync(join(tmpdir(), 'uc625-github-'))]);
  github.serves = true;
  fakes.push(github);
  const multi = await startFake('fake multi-auth', join(LIB, 'fake_multi_auth.py'));
  fakes.push(multi);
  const sf = await startFake('fake Salesforce', join(LIB, 'fake_salesforce.py'));
  fakes.push(sf);

  // One CA file and one name map for tools-service, which reaches all three fakes as outside systems.
  const caDir = mkdtempSync(join(tmpdir(), 'uc625-ca-'));
  const caFile = join(caDir, 'fakes.crt');
  writeFileSync(caFile, [github.info.ca, multi.info.settings.OPS_EGRESS_CA_FILE, sf.info.settings.OPS_EGRESS_CA_FILE].map((f) => readFileSync(f, 'utf8')).join('\n'));
  const resolve = { ...github.info.resolve, ...JSON.parse(multi.info.settings.OPS_EGRESS_RESOLVE), ...JSON.parse(sf.info.settings.OPS_EGRESS_RESOLVE) };
  const hosts = [...github.info.hosts, ...multi.info.hosts, ...sf.info.hosts];
  const ranges = [...new Set([github.info.range, multi.info.range, sf.info.range])];

  /**
   * The apps walked: each plugin, the settings its Connect window is given to reach its fake, how its sign-in page is
   * allowed or refused, and the sentence a refusal shows.
   */
  const APPS = [
    {
      id: 'plugin:opsai.github',
      name: 'GitHub',
      settings: github.info.settings,
      allow: async (popup) => popup.getByRole('button', { name: 'Authorize' }).click({ timeout: 60_000 }),
      ready: (popup) => popup.getByRole('button', { name: 'Authorize' }).waitFor({ timeout: 60_000 }),
      // The fake has GitHub's own Cancel, which sends the person back with error=access_denied.
      refuse: async (popup) => popup.getByRole('button', { name: 'Cancel' }).click(),
      refused: /Access was not given in GitHub/,
    },
    {
      id: 'plugin:opsai.salesforce',
      name: 'Salesforce',
      settings: { login_url: sf.info.login_url },
      place: 'login_url',
      places: ['login.salesforce.com', 'test.salesforce.com', 'Your company'],
      allow: (popup) => mockAllow(popup, 'priya.sf'),
      ready: (popup) => popup.locator('input[name=username]').waitFor({ timeout: 60_000 }),
      refuse: (popup, consoleUrl) => deny(popup, consoleUrl),
      refused: /Access was not given in Salesforce/,
    },
    {
      id: 'plugin:test.person',
      name: 'Person desk',
      settings: {},
      allow: (popup) => mockAllow(popup, 'harbor.ops'),
      ready: (popup) => popup.locator('input[name=username]').waitFor({ timeout: 60_000 }),
      refuse: (popup, consoleUrl) => deny(popup, consoleUrl),
      refused: /Person desk/,
    },
  ];

  /** mock-oauth2-server's sign-in page: the account's name, then its submit. */
  async function mockAllow(popup, user) {
    const name = popup.locator('input[name=username]');
    await name.waitFor({ timeout: 60_000 });
    await name.fill(user);
    await popup.locator('input[type=submit], button[type=submit]').first().click();
  }
  /** mock-oauth2-server has no Deny: the walk sends the window back as a system does when the person refuses. */
  async function deny(popup, consoleUrl) {
    const state = new URL(popup.url()).searchParams.get('state') ?? '';
    await popup.goto(`${consoleUrl}/connections/sign-in/return?error=access_denied&state=${encodeURIComponent(state)}`);
  }

  const tokenFor = async (email) => (await (await fetch(`${platform}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
  const as = (token, team) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
  const call = async (method, path, headers, body) => {
    const r = await fetch(`${tools}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    const json = await r.json().catch(() => null);
    return { status: r.status, data: json?.data };
  };

  /** A fresh 1280 window signed in as `email`, reaching every fake's hosts on this machine's addresses. */
  async function signedIn(browser, consoleUrl, email) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, ignoreHTTPSErrors: true });
    for (const host of hosts) {
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

  /** One check; on a failure the page it was on is kept as `failed-<n>.png` beside the evidence. */
  async function step(name, body, page) {
    try {
      await body();
    } catch (e) {
      await page?.screenshot({ path: join(SHOTS, `failed-${name.split(' ')[0]}.png`) }).catch(() => {});
      check(name, false, `${String(e).slice(0, 300)} at ${page?.url() ?? 'no page'}`);
    }
  }

  /** Opens the Connect window for `app` from the catalog, with its fake's settings under More options. */
  async function connectWindow(page, consoleUrl, app) {
    await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByTestId(`connect-${app.id}`).click({ timeout: 90_000 });
    const win = page.getByTestId('connect-window');
    await win.waitFor({ timeout: 30_000 });
    for (const [name, value] of Object.entries(app.settings)) {
      if (await win.getByTestId(`connect-window-place-${name}`).count()) {
        await setPlace(page, win, name, value);
        continue;
      }
      if (!(await win.getByTestId(`connect-window-setting-${name}`).isVisible())) await win.getByTestId('connect-window-more').click();
      await win.getByTestId(`connect-window-setting-${name}`).fill(value);
    }
    return win;
  }

  /** Where the account signs in, as a person picks it: the company's own address, typed as its host. */
  async function setPlace(page, win, name, value) {
    await win.getByTestId(`connect-window-place-${name}`).click();
    await page.getByTestId(`connect-window-place-${name}-other`).click();
    await win.getByTestId(`connect-window-place-${name}-host`).fill(new URL(value).host);
  }

  /** The sign-in place control's choices as shown, or null when the window has none for `name`. */
  async function placeChoices(page, win, name) {
    const control = win.getByTestId(`connect-window-place-${name}`);
    if (!(await control.isVisible().catch(() => false))) return null;
    await control.click();
    const shown = (await page.getByRole('option').allInnerTexts()).map((t) => t.trim());
    await page.keyboard.press('Escape');
    return shown;
  }

  /** Starts the window's sign-in (Turn on first when the window turns the app on) and resolves with the sign-in window. */
  const authorize = (page) => openSignIn(page);

  /** The app's state as the API reads it, and its page's state badge once the page shows it. */
  async function connectedOnPage(page, consoleUrl, app, headers) {
    await page.waitForURL((u) => u.pathname === `/integrations/apps/${encodeURIComponent(app.id)}`, { timeout: 60_000 }).catch(() => undefined);
    if (!page.url().includes('/integrations/apps/')) await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(app.id)}`, { waitUntil: 'domcontentloaded' });
    const badge = page.getByTestId('app-status');
    await badge.filter({ hasText: 'Connected' }).waitFor({ timeout: 30_000 }).catch(() => undefined);
    const card = ((await call('GET', '/v1/apps', headers)).data ?? []).find((c) => c.id === app.id);
    return { badge: ((await badge.innerText().catch(() => '')) ?? '').trim(), state: card?.appState };
  }

  await withUiStack(
    async (consoleUrl) => {
      mkdirSync(SHOTS, { recursive: true });
      const sam = as(await tokenFor('s.adeyemi@harborpine.example'), 'team_security');
      const priya = as(await tokenFor(PRIYA), 'team_ops');
      for (const host of hosts) await call('POST', '/v1/egress/hosts', sam, { value: host, note: 'uc-625' });
      for (const range of ranges) await call('POST', '/v1/egress/ranges', sam, { value: range, note: 'uc-625' });
      let cards = [];
      for (let i = 0; i < 40 && !APPS.every((a) => cards.some((c) => c.id === a.id && c.plugin?.platformApp)); i++) {
        cards = (await call('GET', '/v1/apps', priya)).data ?? [];
        if (!APPS.every((a) => cards.some((c) => c.id === a.id && c.plugin?.platformApp))) await new Promise((r) => setTimeout(r, 500));
      }
      check('0 set-up: GitHub, Salesforce and Person desk are listed with Ops AI’s own app', APPS.every((a) => cards.some((c) => c.id === a.id && c.plugin?.platformApp)), cards.map((c) => [c.id, Boolean(c.plugin?.platformApp)]));

      const browser = await chromium.launch();
      try {
        const page = await signedIn(browser, consoleUrl, PRIYA);
        await step('51 a member who may not connect is told to ask an admin, by name, on the card and on the app page', async () => {
          const viewer = await signedIn(browser, consoleUrl, 'r.menon@harborpine.example');
          await viewer.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded' });
          const why = viewer.getByTestId(`connect-${APPS[0].id}-why`);
          // The names arrive after the sentence (the team's admins are read on their own), so wait for them.
          await why.filter({ hasText: 'Priya Shah' }).waitFor({ timeout: 30_000 }).catch(() => {});
          const card = ((await why.innerText({ timeout: 60_000 }).catch(() => '')) ?? '').replace(/\s+/g, ' ');
          await viewer.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(APPS[0].id)}`, { waitUntil: 'domcontentloaded' });
          await viewer.getByTestId('app-admin-connects').filter({ hasText: 'Priya Shah' }).waitFor({ timeout: 30_000 }).catch(() => {});
          const header = ((await viewer.getByTestId('app-admin-connects').innerText({ timeout: 60_000 }).catch(() => '')) ?? '').replace(/\s+/g, ' ');
          await viewer.screenshot({ path: join(SHOTS, 'ask-an-admin.png') });
          await viewer.context().close();
          check('51 a member who may not connect is told to ask an admin, by name, on the card and on the app page', [card, header].every((t) => /Ask an admin/.test(t) && /Priya Shah/.test(t)), { card, header });
        }, page);
        await step("54 Salesforce turned on with no sign-in yet: Connect on Ops AI's app asks where to sign in", async () => {
          // Turned on and never signed in, the team account exists, so Connect is connecting it again; Ops AI's app
          // sets no sign-in place, so the window still asks where it signs in.
          const sf = APPS.find((a) => a.place);
          const on = await call('PUT', `/v1/apps/${encodeURIComponent(sf.id)}/team`, priya, { enabled: true });
          await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId(`connect-${sf.id}`).click({ timeout: 90_000 });
          const win = page.getByTestId('connect-window');
          await win.waitFor({ timeout: 30_000 });
          const asked = await win.getByTestId(`connect-window-place-${sf.place}`).isVisible({ timeout: 30_000 }).catch(() => false);
          await page.screenshot({ path: join(SHOTS, 'salesforce-connect-unsigned.png') });
          check("54 Salesforce turned on with no sign-in yet: Connect on Ops AI's app asks where to sign in", on.status === 200 && asked, { on: on.status, asked });
          await page.getByTestId('connect-window-cancel').click().catch(() => {});
        }, page);
        for (const [n, app] of APPS.entries()) {
          const at = (k) => `${(n + 1) * 10 + k}`;

          await step(`${at(1)} ${app.name}: a sign-in window left open from before is never reused; Connect opens one of its own`, async () => {
            // The name every sign-in window once shared; a window of that name still open must stay as it is.
            const [stale] = await Promise.all([page.waitForEvent('popup', { timeout: 30_000 }), page.evaluate(() => void window.open('/connections/connect?app=Stale', 'ops-sign-in', 'popup,width=400,height=400'))]);
            await stale.waitForLoadState('domcontentloaded');
            const before = stale.url();
            const win = await connectWindow(page, consoleUrl, app);
            if (app.place) {
              // Asked in the window's main part, not under More options, with the plugin's own choices.
              const shown = await placeChoices(page, win, app.place);
              check(`${at(6)} ${app.name}: the Connect window asks where you sign in, with the plugin's choices and your company's address`, Boolean(shown) && app.places.every((p) => shown.some((t) => t.includes(p))), { shown });
            }
            const popup = await authorize(page);
            await app.ready(popup);
            const own = popup !== stale && !stale.isClosed() && stale.url() === before;
            check(`${at(1)} ${app.name}: a sign-in window left open from before is never reused; Connect opens one of its own`, own, { before, stale: stale.isClosed() ? 'closed' : stale.url() });
            await stale.close();

            // The same window goes on to the refusal, on the system's page.
            await app.refuse(popup, consoleUrl);
            const error = page.getByTestId('connect-window-error');
            await error.waitFor({ timeout: 30_000 });
            const said = ((await error.innerText()) ?? '').trim();
            const card = await popup.getByTestId('sign-in-denied').innerText({ timeout: 30_000 }).catch(() => '');
            await page.screenshot({ path: join(SHOTS, `${app.name.toLowerCase().replace(/\s+/g, '-')}-refused.png`) });
            check(`${at(2)} ${app.name}: a refused sign-in says in both windows, in one sentence, who acts`, app.refused.test(said) && app.refused.test(card), { said, card: card.replace(/\s+/g, ' ') });
            await popup.close().catch(() => undefined);
            await leaveConnectWindow(page);
            // Turn on saved the team's setting before the refused sign-in, and a refusal never turns it off again; the
            // next step starts from the app off, as an admin first meets it.
            const on = ((await call('GET', '/v1/apps', priya)).data ?? []).find((c) => c.id === app.id);
            if (on?.connectionId) {
              await call('PUT', `/v1/apps/${encodeURIComponent(app.id)}/team`, priya, { enabled: false });
              await call('DELETE', `/v1/apps/${encodeURIComponent(app.id)}/accounts/${on.connectionId}`, priya);
            }
          }, page);

          await step(`${at(3)} ${app.name}: a sign-in window closed early says so, and Try again connects; the app's page reads Connected`, async () => {
            await connectWindow(page, consoleUrl, app);
            const first = await authorize(page);
            await app.ready(first);
            await first.close();
            const error = page.getByTestId('connect-window-error');
            const said = await error.filter({ hasText: 'The window was closed' }).innerText({ timeout: 15_000 }).catch(() => '');
            const button = ((await (await signInButton(page)).innerText()) ?? '').trim();
            await page.screenshot({ path: join(SHOTS, `${app.name.toLowerCase().replace(/\s+/g, '-')}-closed.png`) });
            check(`${at(3)} ${app.name}: a sign-in window closed early says "The window was closed" with Try again`, /The window was closed/.test(said) && button === 'Try again', { said, button });
            if (button !== 'Try again') return;
            const again = await authorize(page);
            await app.allow(again);
            await again.waitForEvent('close', { timeout: 60_000 }).catch(() => undefined);
            const seen = await connectedOnPage(page, consoleUrl, app, priya);
            await page.screenshot({ path: join(SHOTS, `${app.name.toLowerCase().replace(/\s+/g, '-')}-connected.png`) });
            check(`${at(4)} ${app.name}: Try again opens a new window, the fake system allows it, the window closes, and the app's page reads Connected`, seen.badge === 'Connected' && seen.state === 'connected' && again.isClosed(), seen);
            const who = ((await call('GET', `/v1/apps/${encodeURIComponent(app.id)}`, priya)).data?.authConfigs ?? []).flatMap((c) => c.accounts).find((a) => a.default)?.account;
            const header = ((await page.getByTestId('app-connected-as').innerText().catch(() => '')) ?? '').trim();
            check(`${at(7)} ${app.name}: the app's header says Connected as who signed in on the default account`, Boolean(who) && header === `Connected as ${who}`, { header, who });
          }, page);

          await step(`${at(5)} ${app.name}: a sign-in finished in a fresh browser with no storage still reads Connected in the window that started it`, async () => {
            await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(app.id)}`, { waitUntil: 'domcontentloaded' });
            await page.locator('[data-testid^="auth-config-add-"]').first().click({ timeout: 60_000 });
            const win = page.getByTestId('connect-window');
            await win.waitFor({ timeout: 30_000 });
            if (app.place) {
              const host = await win.getByTestId(`connect-window-place-${app.place}-host`).inputValue().catch(() => null);
              check(`${at(8)} ${app.name}: Add account asks where it signs in, starting from the first account's address`, host === new URL(app.settings[app.place]).host, { host });
            }
            if (!(await win.getByTestId('connect-window-name').isVisible())) await win.getByTestId('connect-window-more').click();
            await win.getByTestId('connect-window-name').fill(`${app.name} · elsewhere`);
            const popup = await authorize(page);
            await app.ready(popup).catch(async (e) => {
              throw new Error(`${String(e).split('\n')[0]}; the sign-in window is at ${popup.url()}: ${((await popup.locator('body').innerText().catch(() => '')) ?? '').slice(0, 200)}`);
            });
            const signInAt = popup.url();
            // Another browser: no window ties it to this one, and no storage is shared, so only the API knows the sign-in.
            const other = await signedIn(browser, consoleUrl, PRIYA).catch(() => null);
            if (!other) throw new Error('could not sign in the fresh browser');
            await other.goto(signInAt);
            await app.allow(other);
            const done = other.getByTestId('sign-in-connected');
            const there = await done.innerText({ timeout: 60_000 }).catch(async () => `not connected: ${(await other.locator('body').innerText().catch(() => '')).slice(0, 200)}`);
            // The window that started it learns from the account itself, closes its sign-in window and moves on.
            const here = await page.getByTestId('connect-window').waitFor({ state: 'detached', timeout: 15_000 }).then(() => true, () => false);
            const accounts = ((await call('GET', `/v1/apps/${encodeURIComponent(app.id)}`, priya)).data?.authConfigs ?? []).flatMap((c) => c.accounts);
            const made = accounts.find((a) => a.name === `${app.name} · elsewhere`);
            check(
              `${at(5)} ${app.name}: a sign-in finished in a fresh browser with no storage still reads Connected in the window that started it`,
              /is connected/.test(there) && here && popup.isClosed() && made?.state === 'connected',
              { there: there.replace(/\s+/g, ' ').slice(0, 160), here, popupClosed: popup.isClosed(), made: made && { name: made.name, state: made.state } },
            );
            await other.context().close();
            if (!popup.isClosed()) await popup.close();
          }, page);
        }
        await step('41 a team’s own auth config shows the callback URL to register, on its row and in Edit', async () => {
          const made = (await call('POST', '/v1/app-credentials', priya, { app: 'plugin:opsai.github', name: 'Harbor GitHub app', clientId: 'Iv1.harborown', clientSecret: 'harbor-own-secret-1234' })).data;
          const want = `${consoleUrl}/connections/sign-in/return`;
          await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent('plugin:opsai.github')}`, { waitUntil: 'domcontentloaded' });
          const row = await page.getByTestId('auth-config-callback-Harbor GitHub app').locator('input').inputValue({ timeout: 30_000 }).catch(() => '');
          await page.getByTestId('auth-config-edit-Harbor GitHub app').click({ timeout: 30_000 }).catch(() => undefined);
          const edit = await page.getByTestId('credential-edit-callback').locator('input').inputValue({ timeout: 30_000 }).catch(() => '');
          const copy = await page.getByTestId('credential-edit-callback').getByRole('button').count();
          await page.screenshot({ path: join(SHOTS, 'auth-config-callback.png') });
          await page.keyboard.press('Escape');
          check('41 a team’s own auth config shows the callback URL to register, on its row and in Edit', Boolean(made?.id) && row.includes(want) && edit.includes(want) && copy > 0, { row, edit, copy, want });
        }, page);
        await step('52 Add account on Salesforce has a Test account switch that a test sign-in place turns on, and no screen says sandbox', async () => {
          const sfApp = APPS.find((a) => a.place);
          await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(sfApp.id)}`, { waitUntil: 'domcontentloaded' });
          const pageText = ((await page.locator('main').innerText({ timeout: 60_000 })) ?? '').replace(/\s+/g, ' ');
          await page.locator('[data-testid^="auth-config-add-"]').first().click({ timeout: 60_000 });
          const win = page.getByTestId('connect-window');
          await win.waitFor({ timeout: 30_000 });
          const box = win.getByTestId('connect-window-test-account');
          const before = await box.getAttribute('data-state').catch(() => null);
          await win.getByTestId(`connect-window-place-${sfApp.place}`).click();
          await page.getByTestId(`connect-window-place-${sfApp.place}-test.salesforce.com`).click();
          const after = await box.getAttribute('data-state').catch(() => null);
          const winText = ((await win.innerText()) ?? '').replace(/\s+/g, ' ');
          await page.screenshot({ path: join(SHOTS, 'test-account-switch.png') });
          await win.getByTestId('connect-window-cancel').click();
          check('52 Add account on Salesforce has a Test account switch that a test sign-in place turns on, and no screen says sandbox', before === 'unchecked' && after === 'checked' && !/sandbox/i.test(pageText + winText), { before, after, sandbox: /sandbox/i.test(pageText + winText) });
        }, page);
        await step('53 an app’s Settings show its addresses and call out a test host', async () => {
          await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(APPS[0].id)}`, { waitUntil: 'domcontentloaded' });
          await page.getByTestId('app-tab-settings').click({ timeout: 60_000 });
          const shown = ((await page.getByTestId('app-addresses').innerText({ timeout: 30_000 }).catch(() => '')) ?? '').replace(/\s+/g, ' ');
          const flagged = await page.getByTestId('app-address-test-host').count();
          await page.screenshot({ path: join(SHOTS, 'app-addresses.png') });
          check('53 an app’s Settings show its addresses and call out a test host', shown.includes('api.github.test') && shown.includes('github.test') && flagged > 0, { shown, flagged });
        }, page);
        check('9 no page errors', page.errors.length === 0, page.errors.slice(0, 3));
      } finally {
        await browser.close();
      }
    },
    {
      platform: true,
      tools: {
        env: {
          OPS_EGRESS_CA_FILE: caFile,
          OPS_EGRESS_RESOLVE: JSON.stringify(resolve),
          OPS_PLUGINS: 'true',
          OPS_PLUGIN_PATHS: JSON.stringify([join(PLUGINS, 'github/src/ops_plugin_github'), join(PLUGINS, 'salesforce/src/ops_plugin_salesforce'), join(KINDS, 'kinds_person')]),
          OPS_PLUGIN_CLIENTS: JSON.stringify({
            'opsai.github': { id: github.info.client_id, secret: github.info.client_secret },
            'opsai.salesforce': { id: 'ops-ai-acme', secret: 'acme-connected-app-secret' },
            'test.person': { id: 'multi-app', secret: multi.info.clients['multi-app'] },
          }),
        },
      },
    },
  );
} finally {
  for (const fake of fakes) await stopFake(fake);
}
finish();
