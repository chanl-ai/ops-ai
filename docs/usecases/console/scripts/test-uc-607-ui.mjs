// uc-607 A team connects apps from one catalog, ui layer: docs/usecases/console/connect-apps.md. Connections is a
// catalog of apps read from GET /v1/apps; a plugin connects in a small window; each app has its own page read from
// GET /v1/apps/{id}, where a person connects their own account and a tool then runs with it. The test plugins of
// services/tools-service/tests/plugin_kinds and the fake system (docs/usecases/lib/fake_multi_auth.py) stand in for
// the system. Screenshots of each screen at 1280, light and dark, go to evidenceDir('607', 'uc').
import { execFileSync, spawn } from 'node:child_process';
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { request } from 'node:https';
import { createInterface } from 'node:readline';
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

import { allowBank } from '../../lib/connection_ui.mjs';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const PASSWORD = 'northfield-demo';
const SHOTS = evidenceDir('607', 'uc');
const LOGIN_HOST = 'login.multi.test';
const KINDS = join(ROOT, 'services/tools-service/tests/plugin_kinds');
const FOLDERS = readdirSync(KINDS).filter((n) => n.startsWith('kinds_')).map((n) => join(KINDS, n));
process.env.OPS_PLUGINS = 'true';
process.env.OPS_PLUGIN_PATHS = JSON.stringify(FOLDERS);

// The fake model: the request asks for Person desk's read tool, and the answer names the account the record was read as.
const OURS = [
  { when: '\\bRead record (?P<id>rec-\\d+)', tool: 'person_get_record', arguments: { id: '{id}' } },
  { after: 'person_get_record', result: 'CONNECTION_NOT_LINKED', text: 'I could not read it: connect your own Person desk account first.' },
  { after: 'person_get_record', result: '"as": ?"(?P<who>[^"]+)"', text: 'Harbor ticket 1042 is open; Person desk answered to {who}.' },
];
const RULES = '.logs/usecase/uc607-model';
const demo = JSON.parse(readFileSync(join(ROOT, 'services/models-service/seed/demo-fake-openai/script.json'), 'utf8'));
mkdirSync(join(ROOT, RULES), { recursive: true });
writeFileSync(join(ROOT, RULES, 'script.json'), JSON.stringify({ ...demo, rules: [...OURS, ...demo.rules] }));

/** The fake system, started from its script; resolves with what it printed. */
async function startFake() {
  const child = spawn('uv', ['run', '--quiet', '--directory', join(ROOT, 'services/agents-service'), 'python', join(ROOT, 'docs/usecases/lib/fake_multi_auth.py')], {
    stdio: ['pipe', 'pipe', 'inherit'],
    env: { ...process.env, PYTHONPATH: join(ROOT, 'docs/usecases/lib') },
  });
  const line = await new Promise((resolve, reject) => {
    createInterface({ input: child.stdout }).once('line', resolve);
    child.once('exit', (code) => reject(new Error(`fake system exited with ${code}`)));
  });
  return { child, info: JSON.parse(line) };
}

/** Closes the fake's stdin and waits for it to exit; then no container it started is left. */
async function stopFake() {
  const exited = new Promise((resolve) => (fake.child.exitCode !== null ? resolve() : fake.child.once('exit', resolve)));
  fake.child.stdin.end();
  const timer = setTimeout(() => fake.child.kill('SIGTERM'), 20_000);
  await exited;
  clearTimeout(timer);
  const left = execFileSync('docker', ['ps', '-q', '--filter', `label=ops.harness.owner=${fake.info.owner}`], { encoding: 'utf8' }).trim();
  check('10 the run leaves no container of its own behind', left === '', left);
}

const fake = await startFake();
const [address, port] = JSON.parse(fake.info.settings.OPS_EGRESS_RESOLVE)[LOGIN_HOST].split(':');

/** The fake's record of the calls it took, read on its own address and checked against its CA. */
const fakeState = () =>
  new Promise((resolve, reject) => {
    request(`${fake.info.control}/state`, { ca: readFileSync(fake.info.ca), servername: LOGIN_HOST }, (res) => {
      let body = '';
      res.on('data', (d) => (body += d));
      res.on('end', () => resolve(JSON.parse(body)));
    })
      .on('error', reject)
      .end();
  });

/** Takes the fake system down (every API answers 503, sign-in still works) or brings it back. */
const fakeDown = (down) =>
  new Promise((resolve, reject) => {
    const req = request(`${fake.info.control}/down`, { method: 'POST', ca: readFileSync(fake.info.ca), servername: LOGIN_HOST }, (res) => {
      res.resume();
      res.on('end', resolve);
    });
    req.on('error', reject);
    req.end(JSON.stringify({ down }));
  });

const tokenFor = async (email) => (await (await fetch(`${platform}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token, team) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
const call = async (base, method, path, headers, body) => {
  const r = await fetch(`${base}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await r.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    // Not JSON: the text is kept for the failure message.
  }
  return { status: r.status, data: json?.data, text: text.slice(0, 400) };
};

/** One story; on a failure the page it was on is kept as `failed-<n>.png` beside the evidence. */
async function step(name, body, page) {
  try {
    await body();
  } catch (e) {
    await page?.screenshot({ path: join(SHOTS, `failed-${name.split(' ')[0]}.png`) }).catch(() => {});
    check(name, false, `${String(e).slice(0, 300)} at ${page?.url() ?? 'no page'}`);
  }
}

/**
 * The screen in light and then dark, as `<name>-1280-light.png` and `-dark.png`; the page is left light. The console's
 * dark theme is its `.dark` class on the root (globals.css), which no setting turns on yet, so the walk sets it.
 */
async function shoot(page, name) {
  // At 1280 and at 375, light and dark, for the built-beside-mock page: output matches the design.
  const wide = page.viewportSize() ?? { width: 1280, height: 900 };
  for (const width of [1280, 375]) {
    await page.setViewportSize({ width, height: width === 375 ? 812 : wide.height });
    for (const scheme of ['light', 'dark']) {
      await page.evaluate((dark) => document.documentElement.classList.toggle('dark', dark), scheme === 'dark');
      await page.waitForTimeout(300);
      await page.screenshot({ path: join(SHOTS, `${name}-${width}-${scheme}.png`) });
    }
  }
  await page.setViewportSize(wide);
  await page.evaluate(() => document.documentElement.classList.remove('dark'));
}

/** Signs `email` in on a fresh 1280 window that reaches the fake's sign-in host on this machine's address. */
async function signedIn(browser, consoleUrl, email, errors) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, ignoreHTTPSErrors: true });
  await context.route(`https://${LOGIN_HOST}/**`, async (route) => {
    const u = new URL(route.request().url());
    const response = await route.fetch({ url: `https://${address}:${port}${u.pathname}${u.search}`, headers: { ...route.request().headers(), host: LOGIN_HOST }, maxRedirects: 0 });
    await route.fulfill({ response });
  });
  const page = await context.newPage();
  page.lists = [];
  page.on('pageerror', (e) => errors.push(`${email}: ${e.message}`));
  page.on('request', (r) => {
    const path = new URL(r.url()).pathname;
    if (r.method() === 'GET' && /^\/v1\/(tool-modules|apps)/.test(path)) page.lists.push(path);
  });
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByTestId('login-submit').click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

/** Allows access in the system's window as `user`, and waits for the window to close. */
async function allow(popup, user, shot) {
  const name = popup.locator('input[name=username]');
  await name.waitFor({ timeout: 60_000 });
  // The system's own sign-in page, for the built-beside-mock page (frame 3).
  if (shot) await popup.screenshot({ path: join(SHOTS, `${shot}-1280-light.png`) }).catch(() => undefined);
  await name.fill(user);
  await popup.locator('input[type=submit], button[type=submit]').first().click();
  await popup.waitForEvent('close', { timeout: 60_000 });
}

const APP = 'plugin:test.person';
try {
  await withUiStack(
    async (consoleUrl, stack) => {
      mkdirSync(SHOTS, { recursive: true });
      const sam = as(await tokenFor('s.adeyemi@harborpine.example'), 'team_security');
      const priya = as(await tokenFor('p.shah@harborpine.example'), 'team_ops');
      const maya = as(await tokenFor('m.okafor@harborpine.example'), 'team_ops');

      for (const host of fake.info.hosts) await call(tools, 'POST', '/v1/egress/hosts', sam, { value: host, note: 'uc-607' });
      await call(tools, 'POST', '/v1/egress/ranges', sam, { value: fake.info.range, note: 'uc-607' });
      let card = null;
      for (let i = 0; i < 40 && !card?.plugin?.platformApp; i++) {
        card = ((await call(tools, 'GET', '/v1/apps', priya)).data ?? []).find((c) => c.id === APP);
        if (!card?.plugin?.platformApp) await new Promise((r) => setTimeout(r, 500));
      }
      const agent = (await call(agents, 'POST', '/v1/agents', priya, { name: 'Ticket desk', role: 'Reads tickets from Person desk' })).data ?? {};
      check('0 set-up: Person desk is listed with Ops AI’s own app, and the fake’s hosts are allowed', Boolean(card?.plugin?.platformApp) && Boolean(agent.id), {
        card,
      });

      const browser = await chromium.launch();
      const errors = [];
      try {
        const page = await signedIn(browser, consoleUrl, 'p.shah@harborpine.example', errors);
        const popups = [];
        page.on('popup', (p) => popups.push(p));

        await step('2 the catalog shows Person desk once with its tools and Connect, read in one call, and search finds it', async () => {
          page.lists = [];
          await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const cardEl = page.getByTestId(`system-${APP}`);
          await cardEl.waitFor({ timeout: 90_000 });
          const text = (await cardEl.innerText()).replace(/\s+/g, ' ');
          await page.waitForTimeout(500);
          await shoot(page, 'catalog');
          const lists = [...new Set(page.lists)];
          await page.getByPlaceholder('Search apps').fill('person');
          await page.waitForTimeout(400);
          const shown = await page.locator('[data-testid^="system-"][data-state]').count();
          const kept = await page.getByTestId(`system-${APP}`).count();
          check(
            '2 the catalog shows Person desk once with its tools and Connect, read in one call, and search finds it',
            /Person desk/.test(text) && /\b1 tool\b/.test(text) && !/Plugin/.test(text) && (await page.getByRole('heading', { name: 'Apps', exact: true }).count()) > 0 && (await page.getByTestId(`connect-${APP}`).isVisible()) && lists.join() === '/v1/apps' && shown >= 1 && kept === 1,
            { text, lists, shown, kept },
          );
          await page.getByPlaceholder('Search apps').fill('');
        }, page);

        await step('4 Connect in the Connect window, allow as the team account, and the app’s page lists it as the default', async () => {
          await page.getByTestId(`connect-${APP}`).click();
          const win = page.getByTestId('connect-window');
          await win.waitFor({ timeout: 30_000 });
          const said = (await win.innerText()).replace(/\s+/g, ' ');
          const button = ((await page.getByTestId('connect-window-authorize').innerText()) ?? '').trim();
          // The window's default path: the app credential and the access asked for, then Authorize; the account's name and
          // whose account it is wait under More options.
          const folded = !(await page.getByTestId('connect-window-name').isVisible());
          await shoot(page, 'connect-small');
          // A refused sign-in first. The system sends the person back with error=access_denied, as a real one does when
          // they press Deny; the fake has no Deny button, so the walk sends the window to that address itself.
          const states = [];
          page.context().on('request', (r) => {
            const u = new URL(r.url());
            if (u.hostname === LOGIN_HOST && u.searchParams.get('state')) states.push(u.searchParams.get('state'));
          });
          const [first] = await Promise.all([page.waitForEvent('popup', { timeout: 60_000 }), page.getByTestId('connect-window-authorize').click()]);
          const openedAt = first.url();
          await first.locator('input[name=username]').waitFor({ timeout: 60_000 });
          // Sent from inside the window, as the system's redirect is: a navigation typed into the window would drop its
          // opener, which a redirect keeps.
          const deniedAt = `${consoleUrl}/connections/sign-in/return?error=access_denied&state=${encodeURIComponent(states.at(-1) ?? '')}`;
          await first.evaluate((to) => window.location.assign(to), deniedAt);
          const deniedShown = await first.getByTestId('sign-in-denied').waitFor({ timeout: 60_000 }).then(() => true, () => false);
          const closeOffered = await first.getByTestId('sign-in-close').isVisible().catch(() => false);
          const told = await page.getByTestId('connect-window-error').waitFor({ timeout: 30_000 }).then(async () => ((await page.getByTestId('connect-window-error').innerText()) ?? '').trim(), () => '');
          // Authorize comes back once the window has removed what the refused attempt made.
          const again = await page.waitForFunction(() => !document.querySelector('[data-testid="connect-window-authorize"]')?.hasAttribute('disabled'), null, { timeout: 30_000 }).then(() => true, () => false);
          await shoot(page, 'connect-refused');
          await first.close();
          check(
            '3 one Connect window: the auth config, test or team account and Connect; the sign-in window opens at once on the console’s connect page; a refusal shows in both windows and Connect works again',
            // What the account may do is shown once, in the auth config's details, so the window asks only how to sign in.
            // Turning an app on asks once whose account tools use; the button turns it on with the sign-in.
            /Auth config/.test(said) && /Add your own app/.test(said) && /Whose account do tools use\?/.test(said) && /Team account/.test(said) && button === 'Sign in and turn on' && !/Authorize with/.test(said) && /More options/.test(said) && folded &&
              new URL(openedAt).pathname === '/connections/connect' && new URL(openedAt).searchParams.get('app') === 'Person desk' &&
              deniedShown && closeOffered && /not given/.test(told) && again,
            { said, button, folded, openedAt, deniedShown, closeOffered, told, again },
          );
          // The account's name, which later steps pick it by; left empty it would be the app and the team.
          await page.getByTestId('connect-window-more').click();
          const suggested = await page.getByTestId('connect-window-name').getAttribute('placeholder');
          await page.getByTestId('connect-window-name').fill('Person desk');
          const [popup] = await Promise.all([page.waitForEvent('popup', { timeout: 60_000 }), page.getByTestId('connect-window-authorize').click()]);
          await allow(popup, 'harbor.ops', 'allow');
          // Turned on, the window says so and Done opens the app's page.
          await page.getByTestId('connect-window-done').click({ timeout: 60_000 });
          await page.waitForURL((u) => u.pathname.startsWith('/integrations/apps/'), { timeout: 60_000 });
          // The app's page opens on its Accounts tab, the one list of every account that signs in to it.
          await page.getByTestId('account-state-Person desk').waitFor({ timeout: 60_000 });
          await page.getByTestId('app-status').filter({ hasText: 'Connected' }).waitFor({ timeout: 30_000 });
          const accounts = (await page.getByRole('tabpanel').innerText()).replace(/\s+/g, ' ');
          await shoot(page, 'app-connected-team');
          const conn = ((await call(tools, 'GET', '/v1/apps', priya)).data ?? []).find((c) => c.id === APP);
          const detail = (await call(tools, 'GET', `/v1/apps/${APP}/accounts/${conn?.connectionId}`, priya)).data ?? {};
          check(
            '4 Connect in the Connect window, allow as the team account, and the app’s page lists it as the default',
            suggested === 'Person desk · Operations' && /Cancel/.test(said) && /Person desk/.test(accounts) && /Default/.test(accounts) && detail.signedIn?.account === 'harbor.ops' && popups.length === 2,
            { said, accounts, signedIn: detail.signedIn, signIn: detail.signIn, windows: popups.length },
          );
        }, page);

        // The window closes once access is allowed and the account's first test runs after it. A test call that then
        // fails leaves the account Connected and says so beside it, with Reconnect: here Security takes the app's hosts
        // off the allow list, the test is refused at the gateway, and the hosts go back once it is shown.
        await step('40 a test call that fails after the sign-in shows on the account and the catalog card, with Reconnect', async () => {
          const conn = ((await call(tools, 'GET', '/v1/apps', priya)).data ?? []).find((c) => c.id === APP);
          // An app always reaches its own hosts, so the system itself goes down after the sign-in.
          await fakeDown(true);
          const failed = await call(tools, 'POST', `/v1/apps/${APP}/accounts/${conn?.connectionId}/test`, priya, { account: 'team' });
          await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(APP)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const failedRow = page.getByTestId('account-test-failed-Person desk');
          const row = await failedRow.waitFor({ timeout: 60_000 }).then(async () => ((await failedRow.innerText()) ?? '').trim(), () => '');
          const rowReconnect = await page.getByTestId('account-reconnect-Person desk').isVisible().catch(() => false);
          await shoot(page, 'app-test-failed');
          await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const card = await page.getByTestId(`system-${APP}-test-failed`).waitFor({ timeout: 60_000 }).then(async () => ((await page.getByTestId(`system-${APP}-test-failed`).innerText()) ?? '').trim(), () => '');
          const cardState = await page.getByTestId(`system-${APP}`).getAttribute('data-state');
          await shoot(page, 'catalog-test-failed');
          await fakeDown(false);
          const passed = await call(tools, 'POST', `/v1/apps/${APP}/accounts/${conn?.connectionId}/test`, priya, { account: 'team' });
          const after = ((await call(tools, 'GET', '/v1/apps', priya)).data ?? []).find((c) => c.id === APP);
          check(
            '40 a test call that fails after the sign-in shows on the account and the catalog card, with Reconnect',
            /Signed in, but a test call failed/.test(row) && rowReconnect && /Signed in, but a test call failed/.test(card) && cardState === 'test_failed' && after?.state === 'connected' && passed.data?.health?.status === 'ok',
            { tested: failed.status, failedHealth: failed.data?.health, row, rowReconnect, card, cardState, retested: passed.status, health: passed.data?.health },
          );
        }, page);

        // The catalog: the team's connected apps first, then the ones it may connect, each card with its state and one
        // action; a category narrows it, and the whole card opens the app's page.
        await step('42 Apps lists Connected then Available, each card with its state and one action; a category narrows it; the card opens the app’s page', async () => {
          // A second installed app, not turned on for the team: Person key desk, in the Service desk category.
          // Step 40's passing re-test went to the API, not through the console, so the reads the console saved before it
          // (for 30 seconds) are dropped first, as signing out does.
          await page.evaluate(() => new Promise((done) => {
            const open = indexedDB.open('ops-console');
            open.onsuccess = () => {
              const db = open.result;
              if (!db.objectStoreNames.contains('queries')) return done(null);
              const tx = db.transaction('queries', 'readwrite');
              tx.objectStore('queries').clear();
              tx.oncomplete = tx.onerror = () => done(null);
            };
            open.onerror = () => done(null);
          }));
          await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId('systems-grid').waitFor({ timeout: 60_000 });
          // The Connected view holds the app that is signed in, with no button and its accounts named.
          await page.getByTestId('view-tab-connected').click();
          const ours = page.getByTestId(`system-${APP}`);
          await ours.waitFor({ timeout: 60_000 });
          const connectedHas = (await page.locator('[data-testid^="system-"][data-state]').evaluateAll((els) => els.map((e) => e.getAttribute('data-state')))).every((st) => ['connected', 'test_failed', 'removed'].includes(st));
          const ourState = await ours.getAttribute('data-state');
          const ourText = ((await ours.innerText()) ?? '').replace(/\s+/g, ' ');
          const oneAction = (await ours.locator('button').count()) === 0;
          await shoot(page, 'catalog-connected');
          // The Available view holds the rest, each with Connect.
          await page.getByTestId('view-tab-available').click();
          await page.waitForTimeout(300);
          const others = await page.locator('[data-testid^="system-"][data-state]').evaluateAll((els) => els.map((e) => [e.getAttribute('data-testid'), e.getAttribute('data-state')]));
          const othersConnect = await page.locator('main button[data-testid^="connect-"]').count();
          await shoot(page, 'catalog-available');
          // The Category filter narrows the whole list to one app.
          await page.getByTestId('view-tab-all').click();
          await page.getByRole('button', { name: 'Category' }).click();
          await page.getByTestId('facet-option-Service desk').click();
          await page.getByTestId('facet-apply').click();
          await page.waitForTimeout(300);
          const narrowedCards = await page.locator('[data-testid^="system-"][data-state]').count();
          await shoot(page, 'catalog-category');
          await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await ours.waitFor({ timeout: 60_000 });
          const href = await page.getByTestId(`card-link-${APP}`).getAttribute('href');
          // A click anywhere on the card, away from its name, opens the app's page.
          await ours.click({ position: { x: 24, y: 110 } });
          const opened = await page.waitForURL((u) => u.pathname === `/integrations/apps/${encodeURIComponent(APP)}` || u.pathname === `/integrations/apps/${APP}`, { timeout: 30_000 }).then(() => true, () => false);
          check(
            '42 Apps lists Connected then Available, each card with its state and one action; a category narrows it; the card opens the app’s page',
            connectedHas && ourState === 'connected' && /Connected · \d+ accounts?/.test(ourText) && oneAction &&
              others.length >= 1 && others.every(([, st]) => st === 'not_installed' || st === 'needs_sign_in') && othersConnect >= 1 &&
              narrowedCards === 1 && href === `/integrations/apps/${encodeURIComponent(APP)}` && opened,
            { connectedHas, ourState, ourText, oneAction, others, othersConnect, narrowedCards, href, opened },
          );
        }, page);

        const james = await signedIn(browser, consoleUrl, 'j.richardson@harborpine.example', errors);
        await step('6 James presses Connect on My accounts, allows access as himself, and his account reads james.person, Connected', async () => {
          // A person's own account is connected on My accounts, one row per account they may sign in to themselves.
          const team = ((await call(tools, 'GET', '/v1/apps', priya)).data ?? []).find((c) => c.id === APP)?.connectionId;
          await james.goto(`${consoleUrl}/integrations/my-accounts`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const button = james.getByTestId(`connect-${team}`);
          await button.waitFor({ timeout: 90_000 });
          await shoot(james, 'app-connect-my-account');
          const [popup] = await Promise.all([james.waitForEvent('popup', { timeout: 60_000 }), button.click()]);
          await allow(popup, 'james.person');
          // The row reads who signed in once the page refetches after the sign-in.
          const row = james.locator('tr', { has: james.getByTestId(`my-account-${team}`) });
          await row.getByText(/james\.person/).first().waitFor({ timeout: 60_000 }).catch(() => {});
          const said = ((await row.innerText().catch(() => '')) ?? '').replace(/\s+/g, ' ');
          await shoot(james, 'app-connected-as');
          check(
            '6 James presses Connect on My accounts, allows access as himself, and his account reads james.person, Connected',
            /james\.person/.test(said) && /Connected/.test(said) && (await james.getByTestId(`connect-${team}`).count()) === 0,
            { said },
          );
        }, james);

        await step('7 a tool the agent calls runs with James’s account, and the app’s Logs list it by its title', async () => {
          const toolIds = ['person_get_record'];
          const patched = await call(agents, 'PATCH', `/v1/agents/${agent.id}`, priya, { toolIds });
          const asked = await call(agents, 'POST', `/v1/agents/${agent.id}/publish-requests`, priya, { version: patched.data?.version, note: 'uc-607' });
          const live = asked.data?.status === 'pending' ? await call(agents, 'POST', `/v1/publish-requests/${asked.data.id}/decision`, maya, { decision: 'approved' }) : asked;
          await james.goto(`${consoleUrl}/chat?agent=${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const box = james.getByLabel('Message');
          await box.waitFor({ timeout: 120_000 });
          await james.getByTestId('home-agent').filter({ hasText: 'Ticket desk' }).waitFor({ timeout: 60_000 });
          // Only the reads the chat makes: the connect step's own test read the record as the team account.
          const before = (await fakeState()).calls.length;
          await box.fill('Read record rec-1042.');
          await james.getByRole('button', { name: 'Send' }).click();
          await james.getByText('Person desk answered to james.person').waitFor({ timeout: 90_000 });
          const reads = (await fakeState()).calls.slice(before).filter((c) => c.method === 'person' && c.accepted).map((c) => c.as);
          await james.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(APP)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await james.getByTestId('app-tab-logs').click();
          const usage = james.getByTestId('app-logs');
          await usage.getByText('Read a record').first().waitFor({ timeout: 60_000 });
          const rows = (await usage.innerText()).replace(/\s+/g, ' ');
          await shoot(james, 'app-usage');
          check(
            '7 a tool the agent calls runs with James’s account, and the app’s Logs list it by its title',
            patched.status === 200 && live.status < 300 && reads.length >= 1 && reads.every((w) => w === 'james.person') && /Read a record/.test(rows) && /\bAs\b/.test(rows) && /j\.richardson@harborpine\.example/.test(rows) && /Succeeded/.test(rows),
            { patched: patched.text, live: live.status, reads, rows: rows.slice(0, 300) },
          );
        }, james);

        // Tools lists single tools, joined by the API: each with its app, kind, status and who uses it.
        // The team's assistant holds an app's read tools once the app is on, so the row may name it first and Ticket desk
        // behind "+1"; the tool's page lists both.
        await step('46 Tools lists Read a record as one row with its app, kind, status and Used by Ticket desk; its page says the same', async () => {
          await james.goto(`${consoleUrl}/tools`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          // The installed plugins' tools fill more than a page, so the row is found as a person finds it: by search.
          await james.getByPlaceholder('Search tools or apps…').fill('Read a record');
          const row = james.getByTestId('tool-row-person_get_record');
          await row.waitFor({ timeout: 60_000 }).catch(async (e) => {
            const shown = ((await james.locator('main table').innerText().catch(() => '')) ?? '').replace(/\s+/g, ' ').slice(0, 800);
            throw new Error(`${e.message} The table read: ${shown}`);
          });
          const line = ((await james.locator('tr', { has: row }).innerText()) ?? '').replace(/\s+/g, ' ');
          const tabs = (await james.getByTestId(/^tools-tab-/).allInnerTexts()).map((t) => t.trim());
          await shoot(james, 'tools-single');
          await row.click();
          await james.waitForURL((u) => u.pathname.endsWith('/operations/person_get_record'), { timeout: 60_000 });
          const usedBy = await james.locator('#tool-used-by').getByText('Ticket desk').first().waitFor({ timeout: 60_000 }).catch(() => {}).then(async () => ((await james.locator('#tool-used-by').innerText()) ?? '').replace(/\s+/g, ' '), () => '');
          check(
            '46 Tools lists Read a record as one row with its app, kind, status and Used by Ticket desk; its page says the same',
            tabs.join() === 'All tools,App tools,Custom tools,Logs' && /Read a record/.test(line) && /Person desk/.test(line) && /App tool/.test(line) && /Ready/.test(line) && /Ticket desk|\+\d/.test(line) && /Ticket desk/.test(usedBy),
            { tabs, line, usedBy },
          );
        }, james);

        // The tool's own page has the same log as a Logs tab, fixed to this tool.
        await step('44 the tool’s page has General and Logs tabs, and Logs lists its calls with whom each ran as', async () => {
          const card = ((await call(tools, 'GET', '/v1/apps', priya)).data ?? []).find((c) => c.id === APP);
          const moduleId = card?.moduleIds?.[0] ?? '';
          await james.goto(`${consoleUrl}/tools/${encodeURIComponent(moduleId)}/operations/person_get_record`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await james.getByTestId('tool-tab-logs').click();
          await james.waitForURL((u) => u.pathname.endsWith('/operations/person_get_record/logs'), { timeout: 60_000 });
          const log = james.getByTestId('tool-calls');
          await log.getByText('Read a record').first().waitFor({ timeout: 60_000 });
          const rows = ((await log.innerText()) ?? '').replace(/\s+/g, ' ');
          const tabs = (await james.getByTestId(/^tool-tab-/).allInnerTexts()).map((t) => t.trim());
          await shoot(james, 'tool-logs');
          check(
            '44 the tool’s page has General and Logs tabs, and Logs lists its calls with whom each ran as',
            tabs.join() === 'General,Logs' && /Read a record/.test(rows) && /j\.richardson@harborpine\.example/.test(rows) && /Succeeded/.test(rows),
            { tabs, moduleId, rows: rows.slice(0, 300) },
          );
        }, james);

        await step('7b the Apps menu: Apps, Secrets and Tools in the sidebar with My accounts in its top rows, no tab row; the old My connections, Secrets and call log addresses land in it', async () => {
          await james.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await james.getByTestId('systems-grid').waitFor({ timeout: 60_000 });
          // The four places are sidebar items under Data Hub, side by side; no page repeats them as a tab row.
          const sidebar = (await james.locator('[data-sidebar="menu-button"]').allInnerTexts()).map((t) => t.trim());
          const at = sidebar.indexOf('Apps');
          const menu = sidebar.slice(at, at + 3).join();
          const myAccountsOnTop = sidebar.indexOf('My accounts') > -1 && sidebar.indexOf('My accounts') < sidebar.indexOf('Knowledge bases');
          const tabRows = () => james.locator('[data-testid^="apps-tab-"]').count();
          const tabsOnApps = await tabRows();
          const views = (await james.getByRole('tablist', { name: 'App views' }).innerText()).replace(/\s+/g, ' ');
          await shoot(james, 'catalog');
          await james.getByTestId('view-tab-available').click();
          await shoot(james, 'catalog-available');
          await james.getByTestId('view-tab-all').click();
          await james.goto(`${consoleUrl}/settings/account/connections`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await james.waitForURL((u) => u.pathname === '/integrations/my-accounts', { timeout: 60_000 });
          await james.getByTestId('my-connections').waitFor({ timeout: 60_000 });
          const mine = ((await james.locator('main').innerText()) ?? '').replace(/\s+/g, ' ');
          await shoot(james, 'mine');
          // The Disconnect window, opened and closed again without disconnecting.
          await james.locator('[data-testid^="my-account-menu-"]').first().click();
          await james.locator('[data-testid^="disconnect-"]').first().click();
          await james.getByRole('dialog').waitFor({ timeout: 30_000 });
          await shoot(james, 'mine-disconnect');
          await james.keyboard.press('Escape');
          // The old call log address keeps its filter: a link that searched for a tool lands on the same search.
          await james.goto(`${consoleUrl}/logs/tool-calls?q=person_get_record`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const moved = await james.waitForURL((u) => u.pathname === '/tools/calls' && u.searchParams.get('q') === 'person_get_record', { timeout: 60_000 }).then(() => true, () => false);
          const tabsOnCalls = await tabRows();
          await shoot(james, 'itools-logs');
          await james.goto(`${consoleUrl}/tools`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await james.getByTestId('tools-tab-logs').waitFor({ timeout: 60_000 });
          await shoot(james, 'itools');
          const tabsOnTools = await tabRows();
          // Credentials: App credentials draws its list, its empty state or its error, never a blank; the old Secrets
          // address opens the Secrets tab with its list.
          await james.goto(`${consoleUrl}/integrations/credentials`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          // Secrets: its list, its empty state or its error, never a blank.
          const credsState = await Promise.race([
            james.getByTestId('secrets-panel').waitFor({ timeout: 60_000 }).then(() => 'list'),
            james.getByText(/Couldn’t load the secrets/i).first().waitFor({ timeout: 60_000 }).then(() => 'error'),
          ]).catch(() => 'blank');
          await shoot(james, 'creds');
          await james.goto(`${consoleUrl}/settings/security/secrets`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const secretsMoved = await james.waitForURL((u) => u.pathname === '/integrations/credentials', { timeout: 60_000 }).then(() => true, () => false);
          const secretsShown = await james.getByTestId('secrets-panel').waitFor({ timeout: 60_000 }).then(() => true, () => false);
          const tabsOnCredentials = await tabRows();
          await shoot(james, 'creds-secrets');
          check(
            '7b the Apps menu: Apps, Secrets and Tools in the sidebar with My accounts in its top rows, no tab row; the old My connections, Secrets and call log addresses land in it',
            menu === 'Apps,Secrets,Tools' && myAccountsOnTop && /Connected/.test(views) && /Available/.test(views) &&
              /My accounts/.test(mine) && /Person desk/.test(mine) && !/Settings \/ My accounts/.test(mine) && !/sample data/.test(mine) && moved &&
              credsState !== 'blank' && secretsMoved && secretsShown && tabsOnApps + tabsOnCalls + tabsOnTools + tabsOnCredentials === 0,
            { sidebar, menu, myAccountsOnTop, views, mine: mine.slice(0, 400), moved, credsState, secretsMoved, secretsShown, tabsOnApps, tabsOnCalls, tabsOnTools, tabsOnCredentials },
          );
        }, james);

        // 7c. What the PM walk on the live stack found (2026-11-01), each checked where it shows. James is a builder, not
        // an admin: the grid says why he cannot connect, and his pages read as the Apps design.
        await step('7c the grid and app page agree on Connected; errors offer Try again; no old words, no 404s, dark follows the system, tabs scroll', async () => {
          const out = {};
          // Connected on the grid reads the app's state, as the app page does.
          await james.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await james.getByTestId('systems-grid').waitFor({ timeout: 60_000 });
          const cards = (await call(tools, 'GET', '/v1/apps', priya)).data ?? [];
          out.disagree = [];
          // The grid pages its cards, so each app is found as a person finds it: by search.
          for (const c of cards.filter((x) => x.kind !== 'builtin')) {
            await james.getByPlaceholder('Search apps').fill(c.name);
            const shown = await james.getByTestId(`system-${c.id}`).getAttribute('data-state');
            // The card's state is the API's one word for the app, which the app page reads too.
            const want = c.appState;
            if (shown !== want) out.disagree.push({ id: c.id, state: c.state, shown, want });
          }
          await james.getByPlaceholder('Search apps').fill('');
          // No dead Connect button: each card James may not connect says why instead. Whether he may is his role's
          // (builders manage apps since D59), read from his own answer.
          const his = (await call(tools, 'GET', '/v1/apps', as(await tokenFor('j.richardson@harborpine.example'), 'team_ops'))).data ?? [];
          out.blocked = his.filter((c) => !c.mayManage && c.kind !== 'builtin' && c.appState !== 'connected' && c.appState !== 'removed').length;
          out.connectOff = await james.locator('main button[data-testid^="connect-"]:disabled').count();
          // Counted once the cleared search has drawn the whole list again.
          await james.locator('main [data-testid^="connect-"][data-testid$="-why"]').first().waitFor({ timeout: 15_000 }).catch(() => undefined);
          out.connectWhy = await james.locator('main [data-testid^="connect-"][data-testid$="-why"]').count();
          // A list that fails offers Try again at once, not a skeleton. A browser of its own, so no saved answer from
          // James's earlier visits stands in for the failed read.
          const failing = await signedIn(browser, consoleUrl, 'j.richardson@harborpine.example', []);
          await failing.route('**/v1/apps', (r) => r.fulfill({ status: 500, contentType: 'application/json', body: '{"success":false,"error":{"message":"boom"}}' }));
          await failing.route(/\/v1\/secrets(\?|$)/, (r) => r.fulfill({ status: 500, contentType: 'application/json', body: '{"success":false,"error":{"message":"boom"}}' }));
          await failing.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          out.appsRetry = await failing.getByRole('button', { name: /Try again|Retrying/ }).first().waitFor({ timeout: 20_000 }).then(() => true, () => false);
          await failing.goto(`${consoleUrl}/integrations/credentials`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          out.credsRetry = await failing.getByRole('button', { name: /Try again|Retrying/ }).first().waitFor({ timeout: 8_000 }).then(() => true, () => false);
          await failing.context().close();
          // Tools and a tool page carry none of the retired words.
          await james.goto(`${consoleUrl}/tools`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await james.getByTestId('tools-tab-logs').waitFor({ timeout: 60_000 });
          await james.locator('main tbody tr').first().waitFor({ timeout: 60_000 });
          const toolsText = ((await james.locator('main').innerText()) ?? '').replace(/\s+/g, ' ');
          out.oldWords = ['Owner Plugins', 'no connection', 'Module', 'connection’s sign-in'].filter((w) => toolsText.includes(w));
          // The app page asks for no update review while its flag is off, so it logs no 404.
          const notFound = [];
          const seen = (r) => r.status() === 404 && r.url().includes('/team/update') && notFound.push(r.url());
          james.on('response', seen);
          await james.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(APP)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await james.getByTestId('app-tab-tools').click({ timeout: 60_000 });
          await james.getByTestId('app-tools').waitFor({ timeout: 60_000 });
          await james.waitForTimeout(1500);
          james.off('response', seen);
          out.updateNotFound = notFound.length;
          // At 375 the app page's tab row scrolls rather than clipping Settings.
          await james.setViewportSize({ width: 375, height: 812 });
          out.tabsScroll = await james.getByTestId('app-tabs-row').evaluate((e) => {
            const box = e.getBoundingClientRect();
            const list = e.querySelector('[role="tablist"]')?.getBoundingClientRect();
            return box.right <= window.innerWidth && Boolean(list) && list.width > box.width && document.documentElement.scrollWidth <= window.innerWidth;
          });
          await james.getByTestId('app-tab-settings').scrollIntoViewIfNeeded();
          await james.getByTestId('app-tab-settings').click();
          out.settingsReached = await james.getByTestId('app-tab-settings').getAttribute('data-state');
          await james.setViewportSize({ width: 1280, height: 900 });
          // The console follows the system's dark setting.
          const dark = await james.context().browser().newContext({ colorScheme: 'dark', viewport: { width: 1280, height: 900 } });
          const dp = await dark.newPage();
          await dp.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          out.dark = await dp.evaluate(() => document.documentElement.classList.contains('dark'));
          await dark.close();
          check(
            '7c the grid and app page agree on Connected; errors offer Try again; no old words, no 404s, dark follows the system, tabs scroll',
            out.disagree.length === 0 && out.connectOff === 0 && (out.blocked === 0 || out.connectWhy >= 1) && out.appsRetry && out.credsRetry && out.oldWords.length === 0 && out.updateNotFound === 0 && out.tabsScroll && out.settingsReached === 'active' && out.dark,
            out,
          );
        }, james);

        await step('8 each Built in app opens the page that manages it', async () => {
          // The Apps grid leaves the built-in apps out (they have their own menu); include=builtin lists them with the
          // page each one opens, and that page loads.
          const cards = ((await call(tools, 'GET', '/v1/apps?include=builtin', priya)).data ?? []).filter((c) => c.kind === 'builtin');
          const opened = {};
          for (const c of cards) {
            if (!String(c.href ?? '').startsWith('/')) { opened[c.id] = false; continue; }
            const res = await page.goto(`${consoleUrl}${c.href}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
            const missing = await page.getByText(/page could not be found|^404$/i).count();
            opened[c.id] = (res?.status() ?? 0) < 400 && missing === 0;
          }
          await shoot(page, 'built-in-page');
          check(
            '8 each Built in app opens the page that manages it',
            cards.length >= 1 && cards.every((c) => opened[c.id] === true),
            { cards: cards.map((c) => [c.id, c.href, c.toolsCount]), opened },
          );
        }, page);

        await step('9 the app page opens on Accounts with the tabs; Tools by title, Ops AI’s config with no Edit or Delete, Settings with the personal accounts switch', async () => {
          await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(APP)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          // The page opens on its accounts, each with its state; the default one reads Connected.
          await page.getByTestId('account-state-Person desk').waitFor({ timeout: 60_000 });
          const account = await keysRow(page, 'Person desk');
          const head = ((await page.locator('main').innerText()) ?? '').replace(/\s+/g, ' ');
          await page.getByTestId('app-tab-tools').click();
          await page.getByTestId('app-tools').getByText('Read a record').waitFor({ timeout: 60_000 });
          await shoot(page, 'app-tools');
          // The tabs in order, each named without its count.
          const tabs = (await page.getByTestId(/^app-tab-/).allInnerTexts()).map((t) => t.split('·')[0].trim());
          await page.getByTestId('app-tab-resources').click();
          await page.getByTestId('app-skills-none').waitFor({ timeout: 30_000 });
          await shoot(page, 'app-resources');
          await page.getByTestId('app-tab-auth').click();
          const credentials = (await page.getByTestId('app-auth-configs').innerText()).replace(/\s+/g, ' ');
          // Ops AI's own config is never edited or deleted.
          const builtInEditable = (await page.getByTestId('auth-config-edit-Ops AI').count()) + (await page.getByTestId('auth-config-delete-Ops AI').count());
          await shoot(page, 'app-auth-configs');
          await page.getByTestId('app-tab-settings').click();
          await page.getByTestId('app-settings').waitFor({ timeout: 30_000 });
          const everyone = await page.getByTestId('app-everyone').getAttribute('aria-checked');
          await shoot(page, 'app-settings');
          const html = await page.content();
          check(
            '9 the app page opens on Accounts with the tabs; Tools by title, Ops AI’s config with no Edit or Delete, Settings with the personal accounts switch',
            tabs.join() === 'Accounts,Tools,Auth configs,Resources,Logs,Settings' && !/\bPlugin\b/.test(head) && account.status === 'ok' && /Default/.test(account.said) &&
              /Ops AI/.test(credentials) && /Built in/.test(credentials) && builtInEditable === 0 && everyone === 'true' && !html.includes(fake.info.clients['multi-app']),
            { tabs, account, credentials, everyone },
          );
        }, page);

        // A second named account of the app, a call naming it, and a person's own default among their accounts.
        const tenant = (await call(platform, 'GET', '/v1/me', priya)).data?.tenantId;
        /** A gateway call as agents-service makes it for a run in team_ops with nobody behind it, naming `account`. */
        const asAgents = (account) =>
          JSON.parse(
            execFileSync('uv', ['run', '--quiet', '--project', ROOT, 'python', join(ROOT, 'docs/usecases/lib/agents_call.py'), tools, String(tenant), 'team_ops', 'person_get_record', '{"id": "rec-1042"}', ...(account ? [account] : [])], {
              encoding: 'utf8',
              env: { ...process.env, PYTHONPATH: join(ROOT, 'docs/usecases/lib') },
            }),
          );

        // 9b. A test the service refuses before sending (a 400) says why where it was asked, not only "Not tested yet".
        await step('9b a refused test says its reason when Test now is pressed', async () => {
          await openAccounts(page, consoleUrl, APP);
          await page.route('**/v1/apps/*/accounts/*/test', (r) => r.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ success: false, error: { code: 'test_refused', message: 'The app refused the test: invalid_grant' } }) }), { times: 1 });
          await testNow(page, 'Person desk');
          const why = page.locator('[data-sonner-toast]').filter({ hasText: 'invalid_grant' });
          const said = await why.first().waitFor({ timeout: 30_000 }).then(async () => ((await why.first().innerText()) ?? '').replace(/\s+/g, ' '), () => '');
          check('9b a refused test says its reason when Test now is pressed', /invalid_grant/.test(said), said);
        }, page);

        await step('11 Priya connects another account named EU desk and allows it as the EU team account; both are listed, the first the default', async () => {
          await openAccounts(page, consoleUrl, APP);
          // Another account is the header's one Connect again; its name is under More options.
          await page.getByTestId('app-connect').click();
          const dialog = page.getByTestId('connect-window');
          await dialog.waitFor({ timeout: 30_000 });
          // Another account's window shows its name field at once; the first one folds it under More options.
          if (!(await dialog.getByTestId('connect-window-name').isVisible())) await dialog.getByTestId('connect-window-more').click();
          await dialog.getByTestId('connect-window-name').fill('EU desk');
          await shoot(page, 'another-account');
          const [popup] = await Promise.all([page.waitForEvent('popup', { timeout: 60_000 }), dialog.getByTestId('connect-window-authorize').click()]);
          await allow(popup, 'harbor.eu');
          await page.getByTestId('account-EU desk').waitFor({ timeout: 60_000 });
          await page.waitForTimeout(800);
          const rows = (await page.getByRole('tabpanel').innerText()).replace(/\s+/g, ' ');
          await shoot(page, 'app-accounts');
          const page_ = (await call(tools, 'GET', `/v1/apps/${encodeURIComponent(APP)}`, priya)).data ?? {};
          const accounts = (page_.accounts ?? []).filter((a) => a.kind !== 'person').map((a) => [a.name, a.default, a.status]);
          check(
            '11 Priya connects another account named EU desk and allows it as the EU team account; both are listed, the first the default',
            accounts.length === 2 && accounts.find((a) => a[0] === 'EU desk')?.[1] === false && accounts.filter((a) => a[1]).length === 1 && /EU desk/.test(rows),
            { accounts, rows: rows.slice(0, 300) },
          );
        }, page);

        await step('12 a call naming EU desk runs with the EU account, a call naming no account with the default, and an unknown name is refused', async () => {
          const before = (await fakeState()).calls.length;
          const named = asAgents('EU desk');
          const plain = asAgents(null);
          const unknown = asAgents('Nowhere desk');
          const reads = (await fakeState()).calls.slice(before).filter((c) => c.method === 'person' && c.accepted).map((c) => c.as);
          check(
            '12 a call naming EU desk runs with the EU account, a call naming no account with the default, and an unknown name is refused',
            named.status === 200 && plain.status === 200 && reads.join() === 'harbor.eu,harbor.ops' && unknown.status === 404 && unknown.body?.error?.code === 'ACCOUNT_NOT_FOUND',
            { named: named.status, plain: plain.status, reads, unknown: [unknown.status, unknown.body?.error?.code] },
          );
        }, page);

        await step('13 James connects his own EU desk account; his chat then reads with his newest, and Make my default puts it back on Person desk', async () => {
          const eu = ((await call(tools, 'GET', `/v1/apps/${encodeURIComponent(APP)}`, priya)).data?.accounts ?? []).find((a) => a.kind !== 'person' && a.name === 'EU desk')?.id;
          await james.goto(`${consoleUrl}/integrations/my-accounts`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const connect = james.getByTestId(`connect-${eu}`);
          await connect.waitFor({ timeout: 60_000 });
          const [popup] = await Promise.all([james.waitForEvent('popup', { timeout: 60_000 }), connect.click()]);
          await allow(popup, 'james.eu');
          // Which of a person's own sign-ins their calls use is the account menu's Make my default, on the app's page.
          await openAccounts(james, consoleUrl, APP);
          await james.getByTestId('account-menu-Person desk').click();
          await james.getByTestId('account-action-Make my default-Person desk').waitFor({ timeout: 60_000 });
          await shoot(james, 'app-make-my-default');
          await james.keyboard.press('Escape');
          const ask = async () => {
            await james.goto(`${consoleUrl}/chat?agent=${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
            const box = james.getByLabel('Message');
            await box.waitFor({ timeout: 120_000 });
            const before = (await fakeState()).calls.length;
            await box.fill('Read record rec-1042.');
            await james.getByRole('button', { name: 'Send' }).click();
            await james.getByText(/Person desk answered to james\./).last().waitFor({ timeout: 90_000 });
            return (await fakeState()).calls.slice(before).filter((c) => c.method === 'person' && c.accepted).map((c) => c.as);
          };
          const newest = await ask();
          await james.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(APP)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await james.getByTestId('account-menu-Person desk').click();
          // The chat read after it is the proof; the pin's answer is waited for so the read does not race it.
          const pin = james.waitForResponse((r) => r.request().method() !== 'GET' && /\/v1\/apps\/[^?]+\/accounts\//.test(r.url()), { timeout: 60_000 }).catch(() => null);
          await james.getByTestId('account-action-Make my default-Person desk').click();
          await pin;
          const pinned = await ask();
          check(
            '13 James connects his own EU desk account; his chat then reads with his newest, and Make my default puts it back on Person desk',
            newest.length >= 1 && newest.every((w) => w === 'james.eu') && pinned.length >= 1 && pinned.every((w) => w === 'james.person'),
            { newest, pinned },
          );
        }, james);

        await step('13a Person desk’s Auth configs tab lists Ops AI’s built-in config with the accounts that use it, from the app’s page read', async () => {
          await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(APP)}?tab=auth`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const panel = page.getByTestId('app-auth-configs');
          await panel.getByText('Built in').first().waitFor({ timeout: 60_000 });
          const text = ((await panel.innerText()) ?? '').replace(/\s+/g, ' ');
          await shoot(page, 'creds');
          check('13a Person desk’s Auth configs tab lists Ops AI’s built-in config with the accounts that use it, from the app’s page read', /Ops AI/.test(text) && /Built in/.test(text) && /\d+ accounts?/.test(text), { text: text.slice(0, 300) });
        }, page);

        // Apps (final) frame 11: a run that acts for a person who has not connected their own account waits on a Human
        // Task, not a failure. Priya may run it as the team account (connections.run), and it goes on.
        await step('13c a run Priya starts waits on a Human Task with Connect my account, and goes on as her once she connects from it', async () => {
          await stack.startWorker();
          // A run acting for a person waits only while no team account stands in for them: each person signs in, with
          // no team backup (Settings' switch keeps the team's as backup, so the API sets this one).
          const teamAccount = ((await call(tools, 'GET', '/v1/apps', priya)).data ?? []).find((c) => c.id === APP)?.connectionId;
          const held = (await call(tools, 'GET', `/v1/apps/${encodeURIComponent(APP)}/accounts/${teamAccount}`, priya)).data ?? {};
          const personal = await call(tools, 'PATCH', `/v1/apps/${encodeURIComponent(APP)}/accounts/${teamAccount}`, priya, { revision: held.revision, signIn: 'person', teamBackup: false });
          const flow = `uc607_${Math.random().toString(36).slice(2, 8)}`;
          const node = (id, type, parameters = {}) => ({ id, type, typeVersion: 1, name: id, parameters });
          const definition = {
            schemaVersion: 2,
            id: flow,
            name: 'Read a desk record',
            nodes: [node('start', 'ops.trigger.request'), node('read', 'ops.action.tool', { operation: 'person_get_record', input: { id: 'rec-1042' } }), node('done', 'ops.flow.end', { outcome: 'read', output: '$.nodes.read.out' }), node('failed', 'ops.flow.end', { outcome: 'not_read', result: 'failed' })],
            connections: [
              { from: { node: 'start', port: 'payload' }, to: { node: 'read', port: 'in' } },
              { from: { node: 'read', port: 'ok' }, to: { node: 'done', port: 'in' } },
              { from: { node: 'read', port: 'error' }, to: { node: 'failed', port: 'in' } },
              { from: { node: 'read', port: 'refused' }, to: { node: 'failed', port: 'in' } },
            ],
          };
          await call(agents, 'POST', '/v1/workflows/definitions', priya, { definition });
          await call(agents, 'POST', `/v1/workflows/definitions/${flow}/publish-requests`, priya, {});
          const started = await call(agents, 'POST', '/v1/runs', priya, { workflowId: flow, input: {} });
          const runId = String(started.data?.id ?? started.data?.runId ?? '');
          const runNow = async () => (await call(agents, 'GET', `/v1/runs/${runId}`, priya)).data ?? {};
          let run = await runNow();
          for (let i = 0; i < 60 && !['waiting', 'succeeded', 'failed'].includes(run.status); i++) await new Promise((r) => setTimeout(r, 1000)), (run = await runNow());
          // The run's own page shows the task it waits on, with the same two actions.
          await page.goto(`${consoleUrl}/workflows/runs/${encodeURIComponent(runId)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const onRun = await page.getByTestId('run-connect-task').waitFor({ timeout: 60_000 }).then(() => true, () => false);
          const runSays = onRun ? ((await page.getByTestId('run-connect-task').innerText()) ?? '').replace(/\s+/g, ' ') : '';
          // No team account stands in for a person here, so Connect my account is the one way on.
          const runMe = onRun && (await page.getByTestId('run-connect-task').getByTestId('connect-wait-me').isVisible());
          const runTeam = onRun && (await page.getByTestId('run-connect-task').getByTestId('connect-wait-team').count()) > 0;
          await shoot(page, 'run-person-run-page');
          check('45 the run page shows the task it waits on, with Connect my account and no team account to fall back on', onRun && runMe && !runTeam && /Person desk/.test(runSays), { onRun, runMe, runTeam, runSays: runSays.slice(0, 200) });
          const listed = (await call(agents, 'GET', '/reviews?pageSize=100', priya)).data;
          const task = ((Array.isArray(listed) ? listed : listed?.data) ?? []).find((r) => r.runId === runId) ?? {};
          await page.goto(`${consoleUrl}/reviews?review=${encodeURIComponent(task.id ?? '')}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const wait = page.getByTestId('connect-wait');
          const shown = await wait.waitFor({ timeout: 60_000 }).then(() => true, () => false);
          // The panel's header carries the task's title; the wait below it says what connecting does.
          const said = shown ? ((await page.getByTestId('decision-panel').innerText()) ?? '').replace(/\s+/g, ' ') : '';
          const me = shown && (await page.getByTestId('connect-wait-me').isVisible());
          await shoot(page, 'run-person');
          const before = (await fakeState()).calls.length;
          if (me) {
            const [popup] = await Promise.all([page.waitForEvent('popup', { timeout: 60_000 }), page.getByTestId('connect-wait-me').click()]);
            await allow(popup, 'priya.person');
          }
          run = await runNow();
          for (let i = 0; i < 60 && run.status !== 'succeeded' && run.status !== 'failed'; i++) await new Promise((r) => setTimeout(r, 1000)), (run = await runNow());
          const reads = (await fakeState()).calls.slice(before).filter((c) => c.method === 'person' && c.accepted).map((c) => c.as);
          check(
            '13c a run Priya starts waits on a Human Task with Connect my account, and goes on as her once she connects from it',
            personal.status === 200 && task.kind === 'connect_account' && /Connect your Person desk account to continue/.test(said) && me && run.status === 'succeeded' && reads.includes('priya.person'),
            { personal: personal.status, started: started.status, runStatus: run.status, runError: run.error, task: { id: task.id, kind: task.kind, connect: task.connect }, said: said.slice(0, 200), me, reads },
          );
        }, page);

        await step('13b Priya turns the app off: the window names the agent using its tools first, and the catalog then offers Connect, continuing with its app credential', async () => {
          // openSettings is defined below the stack, so this first stack opens Settings itself.
          await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(APP)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId('app-tab-settings').click();
          await page.getByTestId('app-off').click();
          const users = page.getByTestId('app-off-users');
          await users.getByText('Ticket desk').waitFor({ timeout: 60_000 });
          const named = ((await users.innerText()) ?? '').replace(/\s+/g, ' ');
          await shoot(page, 'app-off');
          const put = page.waitForResponse((r) => r.request().method() === 'PUT' && /\/v1\/apps\/plugin(%3A|:)test\.person\/team$/.test(r.url()), { timeout: 60_000 });
          await page.getByTestId('app-off-confirm').click();
          const res = await put;
          // Off for the team: the catalog offers Connect for it again.
          await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const offered = await page.getByTestId(`connect-${APP}`).waitFor({ timeout: 60_000 }).then(() => true, () => false);
          // Connect on an app turned off opens the one Connect window, on the app credential it had (Ops AI's app here).
          await page.getByTestId(`connect-${APP}`).click();
          const smallAgain = await page.getByTestId('connect-window-app').waitFor({ timeout: 30_000 }).then(async () => /Ops AI’s app/.test(await page.getByTestId('connect-window-app').innerText()), () => false);
          await page.keyboard.press('Escape');
          check(
            '13b Priya turns the app off: the window names the agent using its tools first, and the catalog then offers Connect, continuing with its app credential',
            /Ticket desk/.test(named) && /Agent/.test(named) && res.status() === 200 && offered && smallAgain,
            { named, status: res.status(), offered, smallAgain },
          );
        }, page);

        check('no page errors', errors.length === 0, errors.slice(0, 3));
      } finally {
        await browser.close();
      }
    },
    {
      demo: true,
      fakeModelRules: RULES,
      // Ops AI's own app for Person desk is the install's, from its config, as a deployment sets it.
      tools: { env: { ...fake.info.settings, OPS_PLUGINS: 'true', OPS_PLUGIN_PATHS: JSON.stringify(FOLDERS), OPS_PLUGIN_CLIENTS: JSON.stringify({ 'test.person': { id: 'multi-app', secret: fake.info.clients['multi-app'] } }) } },
    },
  );
} finally {
  await stopFake();
}

// ---- Moved from uc-580 (retired): an account's keys set up, tested and edited from the app page's Settings ----
/** Signs `email` in on a fresh 1280 window; `prepare` routes a fake sign-in host before the first page opens. */
async function adminPage(browser, consoleUrl, email, prepare = null) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, ignoreHTTPSErrors: true });
  if (prepare) await prepare(context);
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
/** Presses the account's Test in the connect window and reads its answer. */
async function windowTest(page) {
  const window_ = page.getByTestId('connect-dialog');
  const section = window_.getByTestId('account-fields');
  const answered = page.waitForResponse((r) => r.request().method() === 'POST' && /\/accounts\/[^/]+\/test$/.test(r.url()), { timeout: 60_000 });
  await section.getByTestId('account-test').click();
  await answered;
  await page.waitForFunction(() => document.querySelector('[data-testid="account-fields"] [data-testid="account-test"]')?.disabled === false, null, { timeout: 30_000 });
  const health = section.getByTestId('account-health');
  await health.waitFor({ timeout: 30_000 });
  return { status: await health.getAttribute('data-status'), said: ((await health.innerText()) ?? '').replace(/\s+/g, ' ') };
}
/**
 * An account's row on the app's Accounts tab, the first when no name is given: ok when it reads Connected with no
 * failed test, else its state, or failed; with the row's words and the account's name.
 */
async function keysRow(page, name) {
  const state = name ? page.getByTestId(`account-state-${name}`) : page.locator('[data-testid^="account-state-"]').first();
  await state.waitFor({ timeout: 60_000 });
  const id = (await state.getAttribute('data-testid')) ?? '';
  const shown = id.replace(/^account-state-/, '');
  const said = ((await page.locator('tr', { has: page.getByTestId(id) }).innerText()) ?? '').replace(/\s+/g, ' ');
  const failed = (await page.getByTestId(`account-test-failed-${shown}`).count()) > 0;
  const st = await state.getAttribute('data-state');
  return { name: shown, status: failed ? 'failed' : st === 'connected' ? 'ok' : st, said };
}
/** The app's page on its Accounts tab, where each account's state, Test now and Reconnect are. */
async function openAccounts(page, consoleUrl, appId) {
  await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(appId)}?tab=accounts`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.locator('[data-testid^="account-state-"]').first().waitFor({ timeout: 60_000 });
}
/** Test now from an account's row menu; returns once the test call has answered and the row has had a moment to redraw. */
async function testNow(page, name) {
  const answered = page.waitForResponse((r) => r.request().method() === 'POST' && /\/accounts\/[^/]+\/test$/.test(r.url()), { timeout: 60_000 }).catch(() => null);
  await page.getByTestId(`account-menu-${name}`).click();
  await page.getByTestId(`account-action-Test now-${name}`).click();
  await answered;
  await page.waitForTimeout(1000);
}
/** The app's Settings tab: personal accounts, how it signs in, on for the team, and deleting it. */
async function openSettings(page, consoleUrl, appId) {
  await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(appId)}?tab=settings`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByTestId('app-settings').waitFor({ timeout: 60_000 });
}
/** One account of an app, by its app's id and its own. */
const accountOf = async (headers, appId, accountId) => (await call(tools, 'GET', `/v1/apps/${encodeURIComponent(appId)}/accounts/${accountId}`, headers)).data ?? {};
const BANK_KEY = 'test-bank-key';
const WRONG_KEY = 'not-the-bank-key';

// A custom app with a key, against the bank stand-in: Add custom app, a refused key, the right one, then Edit on Settings.
await withUiStack(
  async (consoleUrl, stack) => {
    await allowBank(stack.bank);
    const bank = `https://${stack.bank.host}`;
    const priya = as(await tokenFor('p.shah@harborpine.example'), 'team_ops');
    const browser = await chromium.launch();
    try {
      const page = await adminPage(browser, consoleUrl, 'p.shah@harborpine.example');
      await step('14 Add custom app: a refused key tests Failed with the 401, the right one Working with 200, and Save keeps it sealed', async () => {
        await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('connect-system').click();
        const window_ = page.getByTestId('connect-dialog');
        await window_.waitFor({ timeout: 30_000 });
        await window_.getByLabel('App name').fill('Bank API');
        const section = window_.getByTestId('account-fields');
        await section.locator('#account-baseUrl').fill(bank);
        if (!(await section.locator('#account-testPath').isVisible())) await section.getByRole('button', { name: 'More settings' }).click();
        await section.locator('#account-testPath').fill('/auth/api-key');
        await section.locator('#account-key').fill(WRONG_KEY);
        const refused = await windowTest(page);
        await section.locator('#account-key').fill(BANK_KEY);
        const working = await windowTest(page);
        const sealed = await section.locator('#account-key').getAttribute('placeholder');
        await shoot(page, 'custom-app-window');
        await window_.getByTestId('connect-submit').click();
        await window_.waitFor({ state: 'detached', timeout: 30_000 });
        const card = ((await call(tools, 'GET', '/v1/apps', priya)).data ?? []).find((c) => c.name === 'Bank API');
        const account = card ? await accountOf(priya, card.id, card.connectionId) : {};
        check(
          '14 Add custom app: a refused key tests Failed with the 401, the right one Working with 200, and Save keeps it sealed',
          /\b401\b/.test(refused.said) && refused.status !== 'ok' && working.status === 'ok' && /\b200\b/.test(working.said) && /Sealed/.test(sealed ?? '') && account.health?.status === 'ok',
          { refused, working, sealed, health: account.health },
        );
        page.bankApp = card?.id;
      }, page);

      await step("15 the app's account reads working; Settings › Edit settings opens the window sealed, a changed key reads 401, the right one 200", async () => {
        await openAccounts(page, consoleUrl, page.bankApp ?? 'none');
        const before = await keysRow(page);
        await shoot(page, 'app-settings-keys');
        await page.getByTestId('app-tab-settings').click();
        await page.getByTestId('app-edit').click();
        const window_ = page.getByTestId('connect-dialog');
        await window_.waitFor({ timeout: 30_000 });
        const section = window_.getByTestId('account-fields');
        const sealed = await section.locator('#account-key').getAttribute('placeholder');
        await section.locator('#account-key').fill(WRONG_KEY);
        const changed = await windowTest(page);
        await section.locator('#account-key').fill(BANK_KEY);
        const back = await windowTest(page);
        await window_.getByTestId('connect-submit').click();
        await window_.waitFor({ state: 'detached', timeout: 30_000 });
        await page.getByTestId('app-tab-accounts').click();
        await testNow(page, before.name);
        const after = await keysRow(page, before.name);
        check(
          "15 the app's account reads working; Settings › Edit settings opens the window sealed, a changed key reads 401, the right one 200",
          before.status === 'ok' && /Sealed/.test(sealed ?? '') && /\b401\b/.test(changed.said) && back.status === 'ok' && after.status === 'ok',
          { before, sealed, changed, back, after },
        );
      }, page);
      check('16 no page errors with the custom app', page.errors.length === 0, page.errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: { bank: 'core' } },
);

// A certificate-signed Entra app (the signed_entra test plugin) against the fake token endpoint that checks each signed
// assertion as Entra does: the certificate pasted as PEM, its key read from a file; Settings shows its thumbprint.
const entraProc = spawn('uv', ['run', '--quiet', '--directory', join(ROOT, 'services/agents-service'), 'python', join(ROOT, 'docs/usecases/lib/fake_token_endpoint.py')], {
  stdio: ['pipe', 'pipe', 'inherit'],
  env: { ...process.env, PYTHONPATH: join(ROOT, 'docs/usecases/lib') },
});
const entraFake = JSON.parse(
  await new Promise((resolve, reject) => {
    createInterface({ input: entraProc.stdout }).once('line', resolve);
    entraProc.once('exit', (code) => reject(new Error(`fake token endpoint exited with ${code}`)));
  }),
);
try {
  await withUiStack(
    async (consoleUrl) => {
      const sam = as(await tokenFor('s.adeyemi@harborpine.example'), 'team_security');
      const priya = as(await tokenFor('p.shah@harborpine.example'), 'team_ops');
      for (const host of entraFake.hosts) await call(tools, 'POST', '/v1/egress/hosts', sam, { value: host, note: 'uc-607' });
      await call(tools, 'POST', '/v1/egress/ranges', sam, { value: entraFake.range, note: 'uc-607' });
      const browser = await chromium.launch();
      try {
        const page = await adminPage(browser, consoleUrl, 'p.shah@harborpine.example');
        for (let i = 0; i < 20 && !((await call(tools, 'GET', '/v1/apps', priya)).data ?? []).some((c) => c.pluginId === 'test.entra'); i++) await page.waitForTimeout(1000);
        await step("17 a certificate app connects in the window, its account reads working, and its page never shows the key", async () => {
          await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          // The app's own client is made under Credentials (no secret: it signs an assertion), then picked here.
          const entraCredential = (await call(tools, 'POST', '/v1/app-credentials', priya, { app: 'plugin:test.entra', clientId: entraFake.entra.clientId })).data?.id;
          await page.getByTestId('connect-plugin:test.entra').click();
          const window_ = page.getByTestId('connect-dialog');
          await window_.waitFor({ timeout: 30_000 });
          await window_.getByTestId('plugin-app').click({ timeout: 30_000 });
          await page.getByTestId(`plugin-app-option-${entraCredential}`).click();
          const section = window_.getByTestId('account-fields');
          await section.waitFor({ timeout: 30_000 });
          await section.getByRole('button', { name: 'More settings' }).click();
          await section.locator('#account-clientAuth').click();
          await page.getByRole('option', { name: 'private_key_jwt' }).click();
          await section.locator('#account-signingCertificate').fill(entraFake.entra.cert);
          await section.getByTestId('account-signingKey-file').setInputFiles({ name: 'signing.key', mimeType: 'application/x-pem-file', buffer: Buffer.from(entraFake.entra.key) });
          await page.waitForFunction(() => document.querySelector('#account-signingKey')?.value?.includes('PRIVATE KEY'), null, { timeout: 15_000 }).catch(() => {});
          const tested = await windowTest(page);
          await window_.getByTestId('connect-submit').click();
          await window_.waitFor({ state: 'detached', timeout: 30_000 });
          const entra = ((await call(tools, 'GET', '/v1/apps', priya)).data ?? []).find((c) => c.pluginId === 'test.entra');
          await openAccounts(page, consoleUrl, entra?.id ?? 'plugin:test.entra');
          const account = await keysRow(page);
          await shoot(page, 'app-settings-certificate');
          const html = await page.content();
          // The same test again from the API, after the window saved the account: which of the two fails tells the
          // window's request apart from the stack's reach to the sign-in host.
          const again = entra?.connectionId ? await call(tools, 'POST', `/v1/apps/plugin:test.entra/accounts/${entra.connectionId}/test`, priya, { account: 'team' }) : null;
          const apiHealth = again?.data?.health ?? null;
          check(
            "17 a certificate app connects in the window, its account reads working, and its page never shows the key",
            tested.status === 'ok' && account.status === 'ok' && !html.includes('PRIVATE KEY'),
            { tested, account, apiHealth },
          );
        }, page);
        check('18 no page errors with the certificate app', page.errors.length === 0, page.errors.slice(0, 3));
      } finally {
        await browser.close();
      }
    },
    { platform: true, tools: { env: { ...entraFake.settings, OPS_PLUGINS: 'true', OPS_PLUGIN_PATHS: JSON.stringify([join(ROOT, 'services/tools-service/tests/plugin_signed/signed_entra')]) } } },
  );
} finally {
  entraProc.stdin.end();
  const exited = new Promise((resolve) => (entraProc.exitCode !== null ? resolve() : entraProc.once('exit', resolve)));
  const timer = setTimeout(() => entraProc.kill('SIGTERM'), 20_000);
  await exited;
  clearTimeout(timer);
}

// Salesforce's own app on each account against the fake Salesforce, whose sandbox signs in at its own address and lands
// on its own instance: the live account in the Connect window, then a sandbox account added from the app page.
const SF_LOGIN = 'login.salesforce.test';
const SALESFORCE = join(ROOT, '..', 'ops-ai-plugins/plugins/salesforce/src/ops_plugin_salesforce');
const sfProc = spawn('uv', ['run', '--quiet', '--directory', join(ROOT, 'services/agents-service'), 'python', join(ROOT, 'docs/usecases/lib/fake_salesforce.py')], {
  stdio: ['pipe', 'pipe', 'inherit'],
  env: { ...process.env, PYTHONPATH: join(ROOT, 'docs/usecases/lib') },
});
const sf = JSON.parse(
  await new Promise((resolve, reject) => {
    createInterface({ input: sfProc.stdout }).once('line', resolve);
    sfProc.once('exit', (code) => reject(new Error(`fake Salesforce exited with ${code}`)));
  }),
);
const [sfAddress, sfPort] = JSON.parse(sf.settings.OPS_EGRESS_RESOLVE)[SF_LOGIN].split(':');
/** The fake's controls, on its own address and checked against its CA under the sign-in host its certificate names. */
const sfControl = (path, body) =>
  new Promise((resolve, reject) => {
    const data = body === undefined ? undefined : JSON.stringify(body);
    const headers = { Host: SF_LOGIN, ...(data ? { 'Content-Type': 'application/json' } : {}) };
    const req = request({ host: sfAddress, port: Number(sfPort), path: `/_control/${path}`, method: data ? 'POST' : 'GET', headers, ca: readFileSync(sf.ca), servername: SF_LOGIN }, (res) => {
      let text = '';
      res.on('data', (d) => (text += d));
      res.on('end', () => resolve(JSON.parse(text || '{}')));
    });
    req.on('error', reject);
    req.end(data);
  });
try {
  await withUiStack(
    async (consoleUrl) => {
      const sam = as(await tokenFor('s.adeyemi@harborpine.example'), 'team_security');
      const priya = as(await tokenFor('p.shah@harborpine.example'), 'team_ops');
      for (const host of sf.hosts) await call(tools, 'POST', '/v1/egress/hosts', sam, { value: host, note: 'uc-607' });
      await call(tools, 'POST', '/v1/egress/ranges', sam, { value: sf.range, note: 'uc-607' });
      // Every host of the fake, the org's own address (My Domain) among them, reaches it on this machine's address.
      const toLogin = (context) =>
        Promise.all(
          sf.hosts.map((host) =>
            context.route(`https://${host}/**`, async (route) => {
              const u = new URL(route.request().url());
              const response = await route.fetch({ url: `https://${sfAddress}:${sfPort}${u.pathname}${u.search}`, headers: { ...route.request().headers(), host }, maxRedirects: 0 });
              await route.fulfill({ response });
            }),
          ),
        );
      const browser = await chromium.launch();
      try {
        const page = await adminPage(browser, consoleUrl, 'p.shah@harborpine.example', toLogin);
        for (let i = 0; i < 20 && !((await call(tools, 'GET', '/v1/apps', priya)).data ?? []).some((c) => c.pluginId === 'opsai.salesforce'); i++) await page.waitForTimeout(1000);
        const SF = 'plugin:opsai.salesforce';
        /** The app's team accounts, each with its last test, as its Accounts tab reads them. */
        const sfAccounts = async () => ((await call(tools, 'GET', `/v1/apps/${encodeURIComponent(SF)}`, priya)).data?.accounts ?? []).filter((a) => a.kind !== 'person');
        /** The team's own client, made under Credentials with no account and the org's sign-in address, as the Connect window then offers it. */
        const credentialFor = async (clientId, clientSecret, login_url) =>
          (await call(tools, 'POST', '/v1/app-credentials', priya, { app: SF, name: `Salesforce ${clientId}`, clientId, clientSecret, settings: { login_url } })).data?.id;
        /**
         * The team's own app picked in the Connect window, its sign-in address and Authorize, allowed as `user`. The
         * first connect also checks that Authorize with no app credential picked says so and opens no sign-in window;
         * a sandbox account opens the same window from the app page. Answers the account's first test, which runs
         * after the sign-in, in the background.
         */
        const ownWindow = async (values, user, { sandbox = false } = {}) => {
          const window_ = page.getByTestId('connect-window');
          await window_.waitFor({ timeout: 30_000 });
          const picker = window_.getByTestId('connect-window-app');
          if (!sandbox) {
            // No client is typed in the window: it is picked from the team's app credentials, with a link to add one.
            const typed = await window_.getByTestId('connect-window-client-id').count();
            // Add your own app opens the new auth config window in place.
            const add = (await window_.getByTestId('connect-window-app-add').count()) > 0;
            let opened = false;
            const onPopup = () => (opened = true);
            const unpicked = /Pick an auth config/.test(await picker.innerText());
            page.on('popup', onPopup);
            if (unpicked) await window_.getByTestId('connect-window-authorize').click();
            const error = unpicked ? await window_.getByTestId('connect-window-error').innerText({ timeout: 10_000 }).catch(() => '') : '';
            await page.waitForTimeout(500);
            page.off('popup', onPopup);
            await shoot(page, 'connect-required');
            check('43 the Connect window types no client: it picks an auth config, offers to add one in place, and Authorize with none picked says so and opens no sign-in window', typed === 0 && add && (!unpicked || (/Pick the auth config/.test(error) && !opened)), { typed, add, unpicked, error, opened });
          }
          await picker.click();
          await page.getByTestId(`connect-window-app-option-${values.credential}`).click();
          // Where the account signs in is the auth config's: the window shows it, with no field to change it here.
          const shown = ((await window_.getByTestId('connect-window-config-place').innerText({ timeout: 10_000 }).catch(() => '')) ?? '').replace(/\s+/g, ' ');
          const asked = await window_.getByTestId('connect-window-place-login_url').count();
          check(`19 the Connect window shows where ${user} signs in, read from the auth config, and asks nothing about it`, shown.includes(`Signs in at ${values.login_url}`) && asked === 0, { shown, asked });
          if (sandbox) await shoot(page, 'connect-sandbox');
          const [popup] = await Promise.all([page.waitForEvent('popup', { timeout: 60_000 }), window_.getByTestId('connect-window-authorize').click()]);
          const name = popup.locator('input[name=username]');
          await name.waitFor({ timeout: 60_000 });
          await name.fill(user);
          await popup.locator('input[type=submit], button[type=submit]').first().click();
          await popup.waitForEvent('close', { timeout: 60_000 }).catch(() => {});
          await page.waitForURL((u) => u.pathname.startsWith('/integrations/apps/'), { timeout: 60_000 });
          let health = null;
          for (let i = 0; i < 30 && !health; i++) {
            const account = (await sfAccounts()).find((x) => Boolean(x.sandbox) === sandbox);
            health = account?.health?.status ?? null;
            if (!health) await page.waitForTimeout(1000);
          }
          return health;
        };
        // The org's own address (My Domain), one of the places the plugin lets a person sign in.
        const loginUrl = sf.login_url;
        await step("19 Salesforce's own app on each account: the live one in the Connect window, a sandbox account from the app page, each on its own instance", async () => {
          // Both clients are made under Credentials first, so the window's list has them when it opens.
          const liveCredential = await credentialFor('ops-ai-acme', 'acme-connected-app-secret', loginUrl);
          const sandboxCredential = await credentialFor('acme-sandbox-app', 'acme-sandbox-secret', sf.sandbox_login_url);
          await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId('connect-plugin:opsai.salesforce').click();
          const live = await ownWindow({ credential: liveCredential, login_url: loginUrl }, 'priya.live');
          // A test account is the same Connect from the app's header, with Test account ticked; its name is suggested.
          await openAccounts(page, consoleUrl, SF);
          await page.getByTestId('app-connect').click({ timeout: 60_000 });
          await page.getByTestId('connect-window').waitFor({ timeout: 30_000 });
          await page.getByTestId('connect-window-test-account').click();
          // Another account's window shows its name field at once; the first one folds it under More options.
          if (!(await page.getByTestId('connect-window-name').isVisible())) await page.getByTestId('connect-window-more').click();
          const suggested = await page.getByTestId('connect-window-name').getAttribute('placeholder').catch(() => null);
          const sandbox = await ownWindow({ credential: sandboxCredential, login_url: sf.sandbox_login_url }, 'priya.sandbox', { sandbox: true });
          await openAccounts(page, consoleUrl, SF);
          const rows = ((await page.getByRole('tabpanel').innerText()) ?? '').replace(/\s+/g, ' ');
          const badge = await page.locator('[data-testid^="account-sandbox-"]').count();
          await shoot(page, 'app-salesforce-sandbox');
          const accounts = await sfAccounts();
          const details = await Promise.all(accounts.map((x) => accountOf(priya, SF, x.id)));
          const liveOne = details.find((d) => !d.sandbox) ?? {};
          const sandboxOne = details.find((d) => d.sandbox) ?? {};
          const bases = { live: liveOne.settings?.baseUrl, sandbox: sandboxOne.settings?.baseUrl };
          check(
            "19 Salesforce's own app on each account: the live one in the Connect window, a sandbox account from the app page, each on its own instance",
            // The sign-in address typed on the first Connect is the one the live account signs in at.
            live === 'ok' && sandbox === 'ok' && suggested === 'Salesforce test account' && accounts.length === 2 && accounts.filter((a) => a.default).length === 1 && !accounts.find((a) => a.default)?.sandbox && badge === 1 && /Salesforce test account/.test(rows) &&
              bases.sandbox === sf.sandbox_base && bases.live === sf.api_base && String(liveOne.settings?.authorizeUrl ?? '').startsWith(loginUrl),
            { live, sandbox, suggested, rows: rows.slice(0, 300), badge, bases, authorizeUrl: liveOne.settings?.authorizeUrl },
          );
        }, page);
        await step("41 Settings › Edit asks nothing the auth config holds, and saving without typing keeps every saved value", async () => {
          const card = ((await call(tools, 'GET', '/v1/apps', priya)).data ?? []).find((c) => c.pluginId === 'opsai.salesforce');
          const before = await accountOf(priya, SF, card?.connectionId);
          await openSettings(page, consoleUrl, SF);
          await page.getByTestId('app-edit').click();
          const dialog = page.getByTestId('connect-dialog');
          await dialog.waitFor({ timeout: 30_000 });
          await dialog.getByTestId('connect-submit').waitFor({ timeout: 30_000 });
          const field = (await dialog.locator('#account-login_url').count()) ? await dialog.locator('#account-login_url').inputValue() : 'missing';
          const said = ((await dialog.innerText()) ?? '').replace(/\s+/g, ' ');
          await shoot(page, 'app-settings-edit-kept');
          await dialog.getByTestId('connect-submit').click();
          const closed = await dialog.waitFor({ state: 'detached', timeout: 60_000 }).then(() => true, () => false);
          const after = await accountOf(priya, SF, card?.connectionId);
          const kept = (e) => JSON.stringify(Object.fromEntries(Object.entries({ ...(e?.settings ?? {}), ...(e?.pluginSettings ?? {}) }).filter(([k]) => k !== 'scopes')));
          check(
            "41 Settings › Edit asks nothing the auth config holds, and saving without typing keeps every saved value",
            // Where the account signs in is its auth config's, edited there, so this window has no field for it.
            field === 'missing' && closed && kept(after) === kept(before),
            { field, said: said.slice(0, 200), closed, before: kept(before), after: kept(after) },
          );
        }, page);
        await step("21 when Salesforce refuses the team account's refresh, its account reads Expired with Reconnect, and signing in again makes it work", async () => {
          await sfControl('mode', { failNext: 401, refuseRefresh: true });
          const live = (await sfAccounts()).find((a) => a.default)?.name ?? '';
          await openAccounts(page, consoleUrl, SF);
          await testNow(page, live);
          await sfControl('mode', {});
          await page.reload({ waitUntil: 'domcontentloaded' });
          const button = page.getByTestId(`account-reconnect-${live}`);
          await button.waitFor({ timeout: 60_000 }).catch(async (e) => {
            // What the Accounts section and the card say instead, so a red run says why.
            const card = ((await call(tools, 'GET', '/v1/apps', priya)).data ?? []).find((c) => c.pluginId === 'opsai.salesforce');
            console.log('accounts:', ((await page.locator('main').innerText().catch(() => '')) ?? '').replace(/\s+/g, ' ').slice(0, 500), 'card:', JSON.stringify({ state: card?.state, status: card?.status }));
            throw e;
          });
          const accounts = ((await page.getByRole('tabpanel').innerText()) ?? '').replace(/\s+/g, ' ');
          await shoot(page, 'app-account-expired');
          // The catalog card says the same: an expired sign-in offers Reconnect, not Connect.
          await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByPlaceholder('Search apps').fill('Salesforce');
          const cardReconnect = await page.getByTestId(`reconnect-${SF}`).waitFor({ timeout: 30_000 }).then(() => true, () => false);
          await openAccounts(page, consoleUrl, SF);
          await button.waitFor({ timeout: 60_000 });
          const [again] = await Promise.all([page.waitForEvent('popup', { timeout: 60_000 }), button.click()]);
          const name = again.locator('input[name=username]');
          await name.waitFor({ timeout: 60_000 });
          await name.fill('priya.live');
          await again.locator('input[type=submit], button[type=submit]').first().click();
          await again.waitForEvent('close', { timeout: 60_000 }).catch(() => {});
          await openAccounts(page, consoleUrl, SF);
          await testNow(page, live);
          const card = ((await call(tools, 'GET', '/v1/apps', priya)).data ?? []).find((c) => c.pluginId === 'opsai.salesforce');
          const after = await accountOf(priya, SF, card?.connectionId);
          check(
            "21 when Salesforce refuses the team account's refresh, its account reads Expired with Reconnect, and signing in again makes it work",
            /Expired/.test(accounts) && cardReconnect && after.status === 'healthy' && after.health?.status === 'ok',
            { accounts: accounts.slice(0, 200), cardReconnect, status: after.status, health: after.health },
          );
        }, page);
        check('20 no page errors with Salesforce', page.errors.length === 0, page.errors.slice(0, 3));
      } finally {
        await browser.close();
      }
    },
    { platform: true, tools: { env: { ...sf.settings, OPS_PLUGINS: 'true', OPS_PLUGIN_PATHS: JSON.stringify([SALESFORCE]) } } },
  );
} finally {
  sfProc.stdin.end();
  const exited = new Promise((resolve) => (sfProc.exitCode !== null ? resolve() : sfProc.once('exit', resolve)));
  const timer = setTimeout(() => sfProc.kill('SIGTERM'), 20_000);
  await exited;
  clearTimeout(timer);
}
finish();
