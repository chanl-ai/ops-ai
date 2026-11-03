// uc-607 A team connects apps from one catalog, ui layer: docs/usecases/console/connect-apps.md. Connections is a
// catalog of apps read from GET /v1/systems; a plugin connects in a small window; each app has its own page read from
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
// Several named accounts of one app are behind their install flag; this walk turns it on.
process.env.OPS_FLAGS = 'several_accounts';
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
  // An Apps menu page draws its tabs once the route has rendered; a shot taken before shows an empty tab row.
  // A page left behind by client navigation stays in the DOM hidden, so only a visible tab of this page counts.
  if (/^\/(integrations|tools)(\/|$)/.test(new URL(page.url()).pathname)) {
    const t0 = Date.now();
    const seen = await page.locator('[data-testid^="apps-tab-"]:visible').first().waitFor({ timeout: 10_000 }).then(() => true, () => false);
    if (Date.now() - t0 > 1500 || !seen) console.log(`menu tabs on ${new URL(page.url()).pathname} after ${Date.now() - t0} ms, seen ${seen}`);
  }
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
    if (r.method() === 'GET' && /^\/v1\/(systems|connections|tool-modules|plugins|apps)/.test(path)) page.lists.push(path);
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

      const installed = await call(platform, 'PUT', '/v1/policies/plugins', sam, { value: { 'test.person': { enabled: true, client: { id: 'multi-app' } } } });
      for (const host of fake.info.hosts) await call(tools, 'POST', '/v1/egress/hosts', sam, { value: host, note: 'uc-607' });
      await call(tools, 'POST', '/v1/egress/ranges', sam, { value: fake.info.range, note: 'uc-607' });
      let secret = await call(tools, 'PUT', '/v1/plugins/test.person/app-secret', sam, { clientSecret: fake.info.clients['multi-app'] });
      for (let i = 0; i < 20 && secret.status === 404; i++) await new Promise((r) => setTimeout(r, 1000)), (secret = await call(tools, 'PUT', '/v1/plugins/test.person/app-secret', sam, { clientSecret: fake.info.clients['multi-app'] }));
      let card = null;
      for (let i = 0; i < 40 && !card?.plugin?.platformApp; i++) {
        card = ((await call(tools, 'GET', '/v1/systems', priya)).data ?? []).find((c) => c.id === APP);
        if (!card?.plugin?.platformApp) await new Promise((r) => setTimeout(r, 500));
      }
      const agent = (await call(agents, 'POST', '/v1/agents', priya, { name: 'Ticket desk', role: 'Reads tickets from Person desk' })).data ?? {};
      check('0 set-up: Person desk is on for the install with Ops AI’s own app, and the fake’s hosts are allowed', installed.status === 200 && secret.status === 200 && Boolean(card?.plugin?.platformApp) && Boolean(agent.id), {
        installed: installed.text,
        secret: secret.text,
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
          const shown = await page.locator('[data-testid^="system-"]:not([data-testid$="-status"])').count();
          const count = (await page.getByTestId('apps-count').innerText()).trim();
          check(
            '2 the catalog shows Person desk once with its tools and Connect, read in one call, and search finds it',
            /Person desk/.test(text) && /\b1 tool\b/.test(text) && !/Plugin/.test(text) && (await page.getByRole('heading', { name: 'Apps', exact: true }).count()) > 0 && (await page.getByTestId(`connect-${APP}`).isVisible()) && lists.join() === '/v1/systems' && shown >= 1 && /^\d+ of \d+$/.test(count),
            { text, lists, shown, count },
          );
          await page.getByPlaceholder('Search apps').fill('');
        }, page);

        await step('4 Connect in the Connect window, allow as the team account, and the app’s page lists it as the default', async () => {
          await page.getByTestId(`connect-${APP}`).click();
          const win = page.getByTestId('connect-window');
          await win.waitFor({ timeout: 30_000 });
          const said = (await win.innerText()).replace(/\s+/g, ' ');
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
            '3 one Connect window: Ops AI’s app or your own, the access asked for and Authorize; the sign-in window opens at once on the console’s connect page; a refusal shows in both windows and Authorize works again',
            /Ops AI’s app/.test(said) && /Your own app/.test(said) && /gets access to/.test(said) && /Authorize with Person desk/.test(said) && /More options/.test(said) && folded &&
              new URL(openedAt).pathname === '/connections/connect' && new URL(openedAt).searchParams.get('app') === 'Person desk' &&
              deniedShown && closeOffered && /not given/.test(told) && again,
            { said, folded, openedAt, deniedShown, closeOffered, told, again },
          );
          // The account's name, which later steps pick it by; left empty it would be the app and the team.
          await page.getByTestId('connect-window-more').click();
          const suggested = await page.getByTestId('connect-window-name').getAttribute('placeholder');
          await page.getByTestId('connect-window-name').fill('Person desk');
          const [popup] = await Promise.all([page.waitForEvent('popup', { timeout: 60_000 }), page.getByTestId('connect-window-authorize').click()]);
          await allow(popup, 'harbor.ops', 'allow');
          await page.waitForURL((u) => u.pathname.startsWith('/integrations/apps/'), { timeout: 60_000 });
          await page.getByTestId('app-accounts').waitFor({ timeout: 60_000 });
          await page.getByTestId('app-status').filter({ hasText: 'Connected' }).waitFor({ timeout: 30_000 });
          const accounts = (await page.getByTestId('app-accounts').innerText()).replace(/\s+/g, ' ');
          await shoot(page, 'app-connected-team');
          const conn = ((await call(tools, 'GET', '/v1/systems', priya)).data ?? []).find((c) => c.id === APP);
          const detail = (await call(tools, 'GET', `/v1/connections/${conn?.connectionId}`, priya)).data ?? {};
          check(
            '4 Connect in the Connect window, allow as the team account, and the app’s page lists it as the default',
            suggested === 'Person desk · Operations' && /Cancel/.test(said) && /Person desk/.test(accounts) && /Default/.test(accounts) && detail.environments?.production?.signedIn?.account === 'harbor.ops' && popups.length === 2,
            { said, accounts, signedIn: detail.environments?.production?.signedIn, signIn: detail.signIn, windows: popups.length },
          );
        }, page);

        // The window closes once access is allowed and the account's first test runs after it. A test call that then
        // fails leaves the account Connected and says so beside it, with Reconnect: here Security takes the app's hosts
        // off the allow list, the test is refused at the gateway, and the hosts go back once it is shown.
        await step('29 a test call that fails after the sign-in shows on the account and the catalog card, with Reconnect', async () => {
          const conn = ((await call(tools, 'GET', '/v1/systems', priya)).data ?? []).find((c) => c.id === APP);
          const apiHosts = fake.info.hosts.filter((h) => h !== LOGIN_HOST);
          for (const host of apiHosts) await call(tools, 'POST', '/v1/egress/hosts/remove', sam, { value: host });
          const failed = await call(tools, 'POST', `/v1/connections/${conn?.connectionId}/test`, priya, { environment: 'production', account: 'team' });
          await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(APP)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const row = await page.getByTestId('app-test-failed').waitFor({ timeout: 60_000 }).then(async () => ((await page.getByTestId('app-test-failed').innerText()) ?? '').trim(), () => '');
          const rowReconnect = await page.getByTestId('app-reconnect').isVisible().catch(() => false);
          await shoot(page, 'app-test-failed');
          await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const card = await page.getByTestId(`system-${APP}-test-failed`).waitFor({ timeout: 60_000 }).then(async () => ((await page.getByTestId(`system-${APP}-test-failed`).innerText()) ?? '').trim(), () => '');
          const cardState = await page.getByTestId(`system-${APP}`).getAttribute('data-state');
          await shoot(page, 'catalog-test-failed');
          for (const host of apiHosts) await call(tools, 'POST', '/v1/egress/hosts', sam, { value: host, note: 'uc-607' });
          const passed = await call(tools, 'POST', `/v1/connections/${conn?.connectionId}/test`, priya, { environment: 'production', account: 'team' });
          const after = ((await call(tools, 'GET', '/v1/systems', priya)).data ?? []).find((c) => c.id === APP);
          check(
            '29 a test call that fails after the sign-in shows on the account and the catalog card, with Reconnect',
            /Signed in, but a test call failed/.test(row) && rowReconnect && /Signed in, but a test call failed/.test(card) && cardState === 'test_failed' && after?.state === 'connected' && after?.environments?.production?.health?.status === 'ok',
            { tested: failed.status, row, rowReconnect, card, cardState, retested: passed.status, health: after?.environments?.production?.health },
          );
        }, page);

        // The catalog: the team's connected apps first, then the ones it may connect, each card with its state and one
        // action; a category narrows it, and the whole card opens the app's page.
        await step('31 Apps lists Connected then Available, each card with its state and one action; a category narrows it; the card opens the app’s page', async () => {
          // A second app for the install, not turned on for the team: Person key desk, in the Service desk category.
          const both = { 'test.person': { enabled: true, client: { id: 'multi-app' } }, 'test.person-key': { enabled: true } };
          await call(platform, 'PUT', '/v1/policies/plugins', sam, { value: both });
          for (let i = 0; i < 30 && !((await call(tools, 'GET', '/v1/systems', priya)).data ?? []).some((c) => c.id === 'plugin:test.person-key'); i++) await page.waitForTimeout(1000);
          await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId('apps-connected').waitFor({ timeout: 60_000 });
          await page.getByTestId('apps-available').waitFor({ timeout: 60_000 });
          const connectedHas = (await page.getByTestId('apps-connected').getByTestId(`system-${APP}`).count()) === 1;
          const ours = page.getByTestId(`system-${APP}`);
          const ourState = await ours.getAttribute('data-state');
          const ourText = ((await ours.innerText()) ?? '').replace(/\s+/g, ' ');
          const oneAction = (await ours.getByTestId(`open-${APP}`).count()) === 1 && (await ours.getByTestId(`connect-${APP}`).count()) === 0;
          const available = page.getByTestId('apps-available');
          const others = await available.locator('[data-testid^="system-"][data-state]').evaluateAll((els) => els.map((e) => [e.getAttribute('data-testid'), e.getAttribute('data-state')]));
          const othersConnect = await available.locator('button[data-testid^="connect-"]').count();
          const heads = (await page.locator('main section h2').allInnerTexts()).map((t) => t.trim());
          await shoot(page, 'catalog-sections');
          const total = (await page.getByTestId('apps-count').innerText()).trim();
          await page.getByTestId('filter-category-Service desk').click();
          const narrowed = (await page.getByTestId('apps-count').innerText()).trim();
          const narrowedCards = await page.locator('[data-testid^="system-"][data-state]').count();
          await shoot(page, 'catalog-category');
          await page.getByTestId('filter-category-Service desk').click();
          const href = await page.getByTestId(`card-link-${APP}`).getAttribute('href');
          // A click anywhere on the card, away from its name, opens the app's page.
          await ours.click({ position: { x: 24, y: 110 } });
          const opened = await page.waitForURL((u) => u.pathname === `/integrations/apps/${encodeURIComponent(APP)}` || u.pathname === `/integrations/apps/${APP}`, { timeout: 30_000 }).then(() => true, () => false);
          await call(platform, 'PUT', '/v1/policies/plugins', sam, { value: { 'test.person': both['test.person'] } });
          check(
            '31 Apps lists Connected then Available, each card with its state and one action; a category narrows it; the card opens the app’s page',
            heads[0]?.startsWith('Connected') && heads[1]?.startsWith('Available') && connectedHas && ourState === 'connected' && /Connected · 1 tool/.test(ourText) && oneAction &&
              others.length >= 1 && others.every(([, st]) => st === 'not_installed' || st === 'needs_sign_in') && othersConnect >= 1 &&
              narrowedCards === 1 && /^1 of \d+$/.test(narrowed) && href === `/integrations/apps/${encodeURIComponent(APP)}` && opened,
            { heads, connectedHas, ourState, ourText, oneAction, others, othersConnect, total, narrowed, narrowedCards, href, opened },
          );
        }, page);

        const james = await signedIn(browser, consoleUrl, 'j.richardson@harborpine.example', errors);
        await step('6 James presses Connect my account, allows access as himself, and the page reads Connected as james.person', async () => {
          await james.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(APP)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const button = james.getByTestId('app-connect-me');
          await button.waitFor({ timeout: 90_000 });
          await shoot(james, 'app-connect-my-account');
          const [popup] = await Promise.all([james.waitForEvent('popup', { timeout: 60_000 }), button.click()]);
          await allow(popup, 'james.person');
          // The person's own row is always drawn; it reads Connected as them once the page refetches after the sign-in.
          const me = james.getByTestId('app-me');
          await me.getByText(/Connected as/).waitFor({ timeout: 60_000 }).catch(() => {});
          const said = (await me.innerText()).replace(/\s+/g, ' ');
          await shoot(james, 'app-connected-as');
          check('6 James presses Connect my account, allows access as himself, and the page reads Connected as james.person', /Connected as james\.person/.test(said), { said });
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

        // The tool's own page has the same log as a Logs tab, fixed to this tool.
        await step('33 the tool’s page has General and Logs tabs, and Logs lists its calls with whom each ran as', async () => {
          const card = ((await call(tools, 'GET', '/v1/systems', priya)).data ?? []).find((c) => c.id === APP);
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
            '33 the tool’s page has General and Logs tabs, and Logs lists its calls with whom each ran as',
            tabs.join() === 'General,Logs' && /Read a record/.test(rows) && /j\.richardson@harborpine\.example/.test(rows) && /Succeeded/.test(rows),
            { tabs, moduleId, rows: rows.slice(0, 300) },
          );
        }, james);

        await step('7b the Apps menu: tabs Apps, Credentials, My accounts and Tools; the old My connections, Secrets and call log addresses land in it', async () => {
          await james.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await james.getByTestId('systems-grid').waitFor({ timeout: 60_000 });
          const tabs = (await james.getByTestId(/^apps-tab-/).allInnerTexts()).map((t) => t.trim());
          const menu = await james.getByRole('link', { name: 'Apps', exact: true }).count();
          const chips = (await james.getByTestId('apps-tags').innerText()).replace(/\s+/g, ' ');
          await shoot(james, 'catalog');
          await james.getByTestId('filter-available').click();
          await shoot(james, 'catalog-available');
          await james.getByTestId('filter-available').click();
          await james.goto(`${consoleUrl}/settings/account/connections`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await james.waitForURL((u) => u.pathname === '/integrations/my-accounts', { timeout: 60_000 });
          await james.getByTestId('my-connections').waitFor({ timeout: 60_000 });
          const mine = ((await james.locator('main').innerText()) ?? '').replace(/\s+/g, ' ');
          await shoot(james, 'mine');
          // The Disconnect window, opened and closed again without disconnecting.
          await james.locator('[data-testid^="disconnect-"]').first().click();
          await james.getByRole('dialog').waitFor({ timeout: 30_000 });
          await shoot(james, 'mine-disconnect');
          await james.keyboard.press('Escape');
          // The old call log address keeps its filter: a link that searched for a tool lands on the same search.
          await james.goto(`${consoleUrl}/logs/tool-calls?q=person_get_record`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const moved = await james.waitForURL((u) => u.pathname === '/tools/calls' && u.searchParams.get('q') === 'person_get_record', { timeout: 60_000 }).then(() => true, () => false);
          const callTabs = (await james.getByTestId(/^apps-tab-/).allInnerTexts().catch(() => [])).map((t) => t.trim());
          await shoot(james, 'itools-logs');
          await james.goto(`${consoleUrl}/tools`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await james.getByTestId('tool-calls-link').waitFor({ timeout: 60_000 });
          await shoot(james, 'itools');
          // The Apps menu tabs show on Tools and Credentials for a builder too, as on every Apps page. A tab counts only
          // when nothing covers it: on a page taller than the window the tab row once collapsed under the content.
          const shownTabs = () => james.evaluate(() => [...document.querySelectorAll('[data-testid^=apps-tab-]')].filter((e) => {
            if (!e.checkVisibility()) return false;
            const r = e.getBoundingClientRect();
            return e.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2));
          }).length);
          const menuOnTools = await shownTabs();
          const toolsHeader = menuOnTools ? '' : ((await james.locator('main').innerHTML().catch(() => '')) ?? '').slice(0, 1500);
          // Credentials: App credentials draws its list, its empty state or its error, never a blank; the old Secrets
          // address opens the Secrets tab with its list.
          await james.goto(`${consoleUrl}/integrations/credentials`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const credsState = await Promise.race([
            james.getByTestId('app-credentials-panel').waitFor({ timeout: 60_000 }).then(() => 'list'),
            james.getByText(/Couldn’t load the app credentials|app credentials/i).first().waitFor({ timeout: 60_000 }).then(() => 'error or empty'),
          ]).catch(() => 'blank');
          await shoot(james, 'creds');
          await james.goto(`${consoleUrl}/settings/security/secrets`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const secretsMoved = await james.waitForURL((u) => u.pathname === '/integrations/credentials' && u.searchParams.get('tab') === 'secrets', { timeout: 60_000 }).then(() => true, () => false);
          const secretsShown = await james.getByTestId('secrets-panel').waitFor({ timeout: 60_000 }).then(() => true, () => false);
          const menuOnCredentials = await shownTabs();
          await shoot(james, 'creds-secrets');
          check(
            '7b the Apps menu: tabs Apps, Credentials, My accounts and Tools; the old My connections, Secrets and call log addresses land in it',
            tabs.join() === 'Apps,Credentials,My accounts,Tools' && menu >= 1 && /Connected only/.test(chips) && /Available only/.test(chips) &&
              /My accounts/.test(mine) && /Person desk/.test(mine) && !/Settings \/ My accounts/.test(mine) && !/sample data/.test(mine) && moved && callTabs.join() === tabs.join() &&
              credsState !== 'blank' && secretsMoved && secretsShown && menuOnTools === 4 && menuOnCredentials === 4,
            { tabs, menu, chips, mine: mine.slice(0, 400), moved, callTabs, credsState, secretsMoved, secretsShown, menuOnTools, menuOnCredentials, toolsHeader },
          );
        }, james);

        // 7c. What the PM walk on the live stack found (2026-11-01), each checked where it shows. James is a builder, not
        // an admin: the grid says why he cannot connect, and his pages read as the Apps design.
        await step('7c the grid and app page agree on Connected; errors offer Try again; no old words, no 404s, dark follows the system, tabs scroll', async () => {
          const out = {};
          // Connected on the grid reads the app's state, as the app page does.
          await james.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await james.getByTestId('systems-grid').waitFor({ timeout: 60_000 });
          const cards = (await call(tools, 'GET', '/v1/systems', priya)).data ?? [];
          out.disagree = [];
          for (const c of cards.filter((x) => x.kind !== 'builtin')) {
            const shown = await james.getByTestId(`system-${c.id}`).getAttribute('data-state');
            const envs = Object.values(c.environments ?? {});
            const on = c.plugin ? c.plugin.teamOn !== false && Boolean(c.connectionId) : Boolean(c.connectionId) || envs.some((e) => e?.set);
            const failed = envs.some((e) => e?.health?.status === 'failed' && e.health.account === 'team');
            const want = !on ? 'not_installed' : c.state === 'connected' ? (failed ? 'test_failed' : 'connected') : c.state ? 'needs_sign_in' : envs.some((e) => e?.health?.status === 'ok') ? 'connected' : 'needs_sign_in';
            if (shown !== want) out.disagree.push({ id: c.id, state: c.state, shown, want });
          }
          // Connect off for a non-admin says why.
          out.connectOff = await james.locator('main button[data-testid^="connect-"]:disabled').count();
          out.connectWhy = await james.locator('main [data-testid^="connect-"][data-testid$="-why"]').count();
          // A list that fails offers Try again at once, not a skeleton.
          const failing = await james.context().newPage();
          await failing.route('**/v1/systems', (r) => r.fulfill({ status: 500, contentType: 'application/json', body: '{"success":false,"error":{"message":"boom"}}' }));
          await failing.route('**/v1/app-credentials', (r) => r.fulfill({ status: 500, contentType: 'application/json', body: '{"success":false,"error":{"message":"boom"}}' }));
          await failing.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          out.appsRetry = await failing.getByRole('button', { name: /Try again|Retrying/ }).first().waitFor({ timeout: 8_000 }).then(() => true, () => false);
          await failing.goto(`${consoleUrl}/integrations/credentials`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          out.credsRetry = await failing.getByRole('button', { name: /Try again|Retrying/ }).first().waitFor({ timeout: 8_000 }).then(() => true, () => false);
          await failing.close();
          // Tools and a tool page carry none of the retired words.
          await james.goto(`${consoleUrl}/tools`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await james.getByTestId('tool-calls-link').waitFor({ timeout: 60_000 });
          await james.locator('main tbody tr').first().waitFor({ timeout: 60_000 });
          const toolsText = ((await james.locator('main').innerText()) ?? '').replace(/\s+/g, ' ');
          out.oldWords = ['Owner Plugins', 'no connection', 'Module', 'connection’s sign-in'].filter((w) => toolsText.includes(w));
          // The app page asks for no update review while its flag is off, so it logs no 404.
          const notFound = [];
          const seen = (r) => r.status() === 404 && r.url().includes('/team/update') && notFound.push(r.url());
          james.on('response', seen);
          await james.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(APP)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await james.getByTestId('app-tools').waitFor({ timeout: 60_000 });
          await james.waitForTimeout(1500);
          james.off('response', seen);
          out.updateNotFound = notFound.length;
          // At 375 the app page's tab row scrolls rather than clipping Settings.
          await james.setViewportSize({ width: 375, height: 812 });
          out.tabsScroll = await james.getByTestId('app-tabs-row').evaluate((e) => getComputedStyle(e).overflowX !== 'visible' && e.scrollWidth >= e.clientWidth);
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
            out.disagree.length === 0 && out.connectWhy === out.connectOff && out.appsRetry && out.credsRetry && out.oldWords.length === 0 && out.updateNotFound === 0 && out.tabsScroll && out.settingsReached === 'active' && out.dark,
            out,
          );
        }, james);

        await step('8 each Built in app opens the page that manages it', async () => {
          await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId(`system-${APP}`).waitFor({ timeout: 90_000 });
          const cards = ((await call(tools, 'GET', '/v1/systems', priya)).data ?? []).filter((c) => c.kind === 'builtin');
          const opened = {};
          for (const c of cards) opened[c.id] = await page.getByTestId(`card-link-${c.id}`).getAttribute('href');
          await page.getByRole('button', { name: 'Built in', exact: true }).click().catch(() => {});
          await page.waitForTimeout(300);
          await shoot(page, 'catalog-built-in');
          check(
            '8 each Built in app opens the page that manages it',
            cards.length >= 1 && cards.every((c) => opened[c.id] === c.href && c.href.startsWith('/')),
            { cards: cards.map((c) => [c.id, c.href, c.toolsCount]), opened },
          );
        }, page);

        await step('9 the app page has the frame’s Accounts and tabs; Tools by title, Secrets with no secret, Settings with the switch and each environment', async () => {
          await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(APP)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId('app-tools').getByText('Read a record').waitFor({ timeout: 60_000 });
          await shoot(page, 'app-tools');
          // The frame's words (Apps (final) group 4): the tabs in order, the Accounts line, and no kind tag on the page.
          const tabs = (await page.getByTestId(/^app-tab-/).allInnerTexts()).map((t) => t.trim());
          const head = ((await page.locator('main').innerText()) ?? '').replace(/\s+/g, ' ');
          await page.getByTestId('app-tab-resources').click();
          await page.getByTestId('app-skills-none').waitFor({ timeout: 30_000 });
          await shoot(page, 'app-resources');
          await page.getByTestId('app-tab-secrets').click();
          const secrets = (await page.getByTestId('app-secrets').innerText()).replace(/\s+/g, ' ');
          await shoot(page, 'app-secrets');
          await page.getByTestId('app-tab-settings').click();
          await page.getByTestId('app-envs').waitFor({ timeout: 30_000 });
          const everyone = await page.getByTestId('app-everyone').getAttribute('aria-checked');
          const envs = (await page.getByTestId('app-envs').innerText()).replace(/\s+/g, ' ');
          await page.getByTestId('app-own-row').click();
          await page.getByTestId('app-credentials').waitFor({ timeout: 30_000 });
          await shoot(page, 'app-settings');
          const html = await page.content();
          check(
            '9 the app page has the frame’s Accounts and tabs; Tools by title, Secrets with no secret, Settings with the switch and each environment',
            tabs.join() === 'Tools,Resources,Secrets,Logs,Settings' && /Calls use the default account unless a step names another/.test(head) && !/\bPlugin\b/.test(head) &&
              /harbor\.ops/.test(secrets) && /App credential/.test(secrets) && everyone === 'true' && /Production/.test(envs) && /Test/.test(envs) && !html.includes(fake.info.clients['multi-app']),
            { tabs, secrets, everyone, envs },
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

        // 9b. A test the service refuses before sending (a 400) says why on the environment's row, not only "Not tested yet".
        await step('9b a refused environment test shows its reason on the row', async () => {
          await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(APP)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId('app-tab-settings').click();
          await page.getByTestId('app-envs').waitFor({ timeout: 60_000 });
          await page.route('**/v1/connections/*/test', (r) => r.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ success: false, error: { code: 'test_refused', message: 'The app refused the test: invalid_grant' } }) }), { times: 1 });
          await page.getByTestId('app-test-production').click();
          const why = page.getByTestId('app-env-error-production');
          const said = await why.waitFor({ timeout: 30_000 }).then(async () => ((await why.innerText()) ?? '').trim(), () => '');
          check('9b a refused environment test shows its reason on the row', /invalid_grant/.test(said), said);
        }, page);

        await step('11 Priya connects another account named EU desk and allows it as the EU team account; both are listed, the first the default', async () => {
          await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(APP)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId('app-connect-another').click();
          // Another account opens the same Connect window, its name field showing.
          const dialog = page.getByTestId('connect-window');
          await dialog.waitFor({ timeout: 30_000 });
          await dialog.getByTestId('connect-window-name').fill('EU desk');
          await shoot(page, 'another-account');
          const [popup] = await Promise.all([page.waitForEvent('popup', { timeout: 60_000 }), dialog.getByTestId('connect-window-authorize').click()]);
          await allow(popup, 'harbor.eu');
          await page.getByTestId('account-EU desk').waitFor({ timeout: 60_000 });
          await page.waitForTimeout(800);
          const rows = (await page.getByTestId('app-accounts').innerText()).replace(/\s+/g, ' ');
          await shoot(page, 'app-accounts');
          const page_ = (await call(tools, 'GET', `/v1/apps/${encodeURIComponent(APP)}`, priya)).data ?? {};
          const accounts = (page_.accounts ?? []).map((a) => [a.name, a.default, a.status]);
          check(
            '11 Priya connects another account named EU desk and allows it as the EU team account; both are listed, the first the default',
            accounts.length === 2 && accounts[0][1] === true && accounts[1][0] === 'EU desk' && accounts[1][1] === false && /EU desk/.test(rows),
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
          await james.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(APP)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const connect = james.getByTestId('account-connect-EU desk');
          await connect.waitFor({ timeout: 60_000 });
          const [popup] = await Promise.all([james.waitForEvent('popup', { timeout: 60_000 }), connect.click()]);
          await allow(popup, 'james.eu');
          await james.getByTestId('account-pin-Person desk').waitFor({ timeout: 60_000 });
          await shoot(james, 'app-accounts-mine');
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
          await james.getByTestId('account-pin-Person desk').click();
          await james.getByTestId('account-pin-EU desk').waitFor({ timeout: 60_000 });
          const pinned = await ask();
          check(
            '13 James connects his own EU desk account; his chat then reads with his newest, and Make my default puts it back on Person desk',
            newest.length >= 1 && newest.every((w) => w === 'james.eu') && pinned.length >= 1 && pinned.every((w) => w === 'james.person'),
            { newest, pinned },
          );
        }, james);

        await step('13a Priya’s Credentials list Person desk’s OAuth app as Ops AI’s app, from GET /v1/app-credentials', async () => {
          const listed = page.waitForResponse((r) => r.request().method() === 'GET' && r.url().includes('/v1/app-credentials'), { timeout: 60_000 });
          await page.goto(`${consoleUrl}/integrations/credentials`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const res = await listed;
          const panel = page.getByTestId('app-credentials-panel');
          await panel.getByText('Person desk').first().waitFor({ timeout: 60_000 });
          const text = ((await panel.innerText()) ?? '').replace(/\s+/g, ' ');
          await shoot(page, 'creds');
          check('13a Priya’s Credentials list Person desk’s OAuth app as Ops AI’s app, from GET /v1/app-credentials', res.status() === 200 && /Person desk/.test(text) && /Ops AI’s app/.test(text), { status: res.status(), text: text.slice(0, 300) });
        }, page);

        // Apps (final) frame 11: a run that acts for a person who has not connected their own account waits on a Human
        // Task, not a failure. Priya may run it as the team account (connections.run), and it goes on.
        await step('13c a run Priya starts waits on a Human Task with Connect my account and Run as the team account, and goes on as the team account', async () => {
          await stack.startWorker();
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
          const runBoth = onRun && (await page.getByTestId('run-connect-task').getByTestId('connect-wait-me').isVisible()) && (await page.getByTestId('run-connect-task').getByTestId('connect-wait-team').isVisible());
          await shoot(page, 'run-person-run-page');
          check('34 the run page shows the task it waits on, with Connect my account and Run as the team account', onRun && runBoth && /Person desk/.test(runSays), { onRun, runBoth, runSays: runSays.slice(0, 200) });
          const listed = (await call(agents, 'GET', '/reviews?pageSize=100', priya)).data;
          const task = ((Array.isArray(listed) ? listed : listed?.data) ?? []).find((r) => r.runId === runId) ?? {};
          await page.goto(`${consoleUrl}/reviews?review=${encodeURIComponent(task.id ?? '')}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const wait = page.getByTestId('connect-wait');
          const shown = await wait.waitFor({ timeout: 60_000 }).then(() => true, () => false);
          // The panel's header carries the task's title; the wait below it says what connecting does.
          const said = shown ? ((await page.getByTestId('decision-panel').innerText()) ?? '').replace(/\s+/g, ' ') : '';
          const both = shown && (await page.getByTestId('connect-wait-me').isVisible()) && (await page.getByTestId('connect-wait-team').isVisible());
          await shoot(page, 'run-person');
          const asTeam = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().includes('/team-account'), { timeout: 60_000 }).catch(() => null);
          if (both) await page.getByTestId('connect-wait-team').click();
          const res = await asTeam;
          run = await runNow();
          for (let i = 0; i < 60 && run.status !== 'succeeded' && run.status !== 'failed'; i++) await new Promise((r) => setTimeout(r, 1000)), (run = await runNow());
          check(
            '13c a run Priya starts waits on a Human Task with Connect my account and Run as the team account, and goes on as the team account',
            task.kind === 'connect_account' && /Connect your Person desk account to continue/.test(said) && both && res?.status() === 200 && run.status === 'succeeded',
            { started: started.status, runStatus: run.status, runError: run.error, task: { id: task.id, kind: task.kind, connect: task.connect }, said: said.slice(0, 200), both, asTeam: res?.status() },
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
          const put = page.waitForResponse((r) => r.request().method() === 'PUT' && r.url().endsWith(`/v1/plugins/${APP.replace(/^plugin:/, '')}/team`), { timeout: 60_000 });
          await page.getByTestId('app-off-confirm').click();
          const res = await put;
          // Off for the team: the catalog offers Connect for it again.
          await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const offered = await page.getByTestId(`connect-${APP}`).waitFor({ timeout: 60_000 }).then(() => true, () => false);
          // Connect on an app turned off opens the one Connect window, continuing with the app credential it had.
          await page.getByTestId(`connect-${APP}`).click();
          const smallAgain = await page.getByTestId('connect-window-reuse').waitFor({ timeout: 30_000 }).then(async () => /Continuing with/.test(await page.getByTestId('connect-window-reuse').innerText()), () => false);
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
      tools: { env: { ...fake.info.settings, OPS_PLUGINS: 'true', OPS_PLUGIN_PATHS: JSON.stringify(FOLDERS) } },
    },
  );
} finally {
  await stopFake();
}

// ---- Moved from uc-580 (retired): an environment set up, tested and edited from the app page's Settings ----
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
/** Presses an environment section's Test in the Connect window and reads its answer. */
async function windowTest(page, env) {
  const window_ = page.getByTestId('connect-dialog');
  const section = window_.getByTestId(`env-${env}`);
  const answered = page.waitForResponse((r) => r.request().method() === 'POST' && /\/connections\/[^/]+\/test$/.test(r.url()), { timeout: 60_000 });
  await section.getByTestId(`test-${env}`).click();
  await answered;
  await page.waitForFunction((e) => document.querySelector(`[data-testid="env-${e}"] [data-testid="test-${e}"]`)?.disabled === false, env, { timeout: 30_000 });
  const health = section.getByTestId(`health-${env}`);
  await health.waitFor({ timeout: 30_000 });
  return { status: await health.getAttribute('data-status'), said: ((await health.innerText()) ?? '').replace(/\s+/g, ' ') };
}
/** An environment row on the app page's Settings: its state and what it says. */
async function envRow(page, env) {
  const row = page.getByTestId(`app-env-${env}`);
  await row.waitFor({ timeout: 60_000 });
  return { status: await row.getAttribute('data-status'), said: ((await page.getByTestId('app-envs').innerText()) ?? '').replace(/\s+/g, ' ') };
}
const openSettings = async (page, consoleUrl, appId) => {
  await page.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(appId)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByTestId('app-tab-settings').click();
  await page.getByTestId('app-envs').waitFor({ timeout: 60_000 });
};
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
        const section = window_.getByTestId('env-production');
        await section.locator('#production-baseUrl').fill(bank);
        if (!(await section.locator('#production-testPath').isVisible())) await section.getByRole('button', { name: 'More settings' }).click();
        await section.locator('#production-testPath').fill('/auth/api-key');
        await section.locator('#production-key').fill(WRONG_KEY);
        const refused = await windowTest(page, 'production');
        await section.locator('#production-key').fill(BANK_KEY);
        const working = await windowTest(page, 'production');
        const sealed = await section.locator('#production-key').getAttribute('placeholder');
        await shoot(page, 'custom-app-window');
        await window_.getByTestId('connect-submit').click();
        await window_.waitFor({ state: 'detached', timeout: 30_000 });
        const card = ((await call(tools, 'GET', '/v1/systems', priya)).data ?? []).find((c) => c.name === 'Bank API');
        check(
          '14 Add custom app: a refused key tests Failed with the 401, the right one Working with 200, and Save keeps it sealed',
          /\b401\b/.test(refused.said) && refused.status !== 'ok' && working.status === 'ok' && /\b200\b/.test(working.said) && /Sealed/.test(sealed ?? '') && card?.environments?.production?.health?.status === 'ok',
          { refused, working, sealed, production: card?.environments?.production },
        );
        page.bankApp = card?.id;
      }, page);

      await step("15 the app's Settings shows Production working; Edit opens the window sealed, a changed key reads 401, the right one 200", async () => {
        await openSettings(page, consoleUrl, page.bankApp ?? 'none');
        const before = await envRow(page, 'production');
        await shoot(page, 'app-settings-environments');
        await page.getByTestId('app-edit-production').click();
        const window_ = page.getByTestId('connect-dialog');
        await window_.waitFor({ timeout: 30_000 });
        const section = window_.getByTestId('env-production');
        const sealed = await section.locator('#production-key').getAttribute('placeholder');
        await section.locator('#production-key').fill(WRONG_KEY);
        const changed = await windowTest(page, 'production');
        await section.locator('#production-key').fill(BANK_KEY);
        const back = await windowTest(page, 'production');
        await window_.getByTestId('connect-submit').click();
        await window_.waitFor({ state: 'detached', timeout: 30_000 });
        await page.getByTestId('app-test-production').click();
        await page.waitForFunction(() => document.querySelector('[data-testid="app-env-production"]')?.getAttribute('data-status') === 'ok', null, { timeout: 30_000 }).catch(() => {});
        const after = await envRow(page, 'production');
        check(
          "15 the app's Settings shows Production working; Edit opens the window sealed, a changed key reads 401, the right one 200",
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
      const installed = await call(platform, 'PUT', '/v1/policies/plugins', sam, { value: { 'test.entra': { enabled: true } } });
      for (const host of entraFake.hosts) await call(tools, 'POST', '/v1/egress/hosts', sam, { value: host, note: 'uc-607' });
      await call(tools, 'POST', '/v1/egress/ranges', sam, { value: entraFake.range, note: 'uc-607' });
      const browser = await chromium.launch();
      try {
        const page = await adminPage(browser, consoleUrl, 'p.shah@harborpine.example');
        for (let i = 0; i < 20 && !((await call(tools, 'GET', '/v1/systems', priya)).data ?? []).some((c) => c.pluginId === 'test.entra'); i++) await page.waitForTimeout(1000);
        await step("17 a certificate app connects in the window, and its Settings show the certificate's thumbprint and expiry, never its key", async () => {
          await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId('connect-plugin:test.entra').click();
          const window_ = page.getByTestId('connect-dialog');
          await window_.waitFor({ timeout: 30_000 });
          const section = window_.getByTestId('env-production');
          await section.locator('#production-clientId').waitFor({ timeout: 30_000 });
          await section.locator('#production-clientId').fill(entraFake.entra.clientId);
          await section.getByRole('button', { name: 'More settings' }).click();
          await section.locator('#production-clientAuth').click();
          await page.getByRole('option', { name: 'private_key_jwt' }).click();
          await section.locator('#production-signingCertificate').fill(entraFake.entra.cert);
          await section.getByTestId('production-signingKey-file').setInputFiles({ name: 'signing.key', mimeType: 'application/x-pem-file', buffer: Buffer.from(entraFake.entra.key) });
          await page.waitForFunction(() => document.querySelector('#production-signingKey')?.value?.includes('PRIVATE KEY'), null, { timeout: 15_000 }).catch(() => {});
          const tested = await windowTest(page, 'production');
          await window_.getByTestId('connect-submit').click();
          await window_.waitFor({ state: 'detached', timeout: 30_000 });
          const entra = ((await call(tools, 'GET', '/v1/systems', priya)).data ?? []).find((c) => c.pluginId === 'test.entra');
          await openSettings(page, consoleUrl, entra?.id ?? 'plugin:test.entra');
          const line = page.getByTestId('app-certificate-production');
          await line.waitFor({ timeout: 60_000 }).catch(() => {});
          const said = ((await line.count()) ? await line.innerText() : '').replace(/\s+/g, ' ');
          await shoot(page, 'app-settings-certificate');
          const html = await page.content();
          check(
            "17 a certificate app connects in the window, and its Settings show the certificate's thumbprint and expiry, never its key",
            installed.status === 200 && tested.status === 'ok' && /Signing certificate [0-9A-Za-z:_-]{16,} expires /.test(said) && !html.includes('PRIVATE KEY'),
            { installed: installed.status, tested, said },
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

// Salesforce's own app per environment against the fake Salesforce, whose sandbox signs in at its own address and lands on
// its own instance: production in the Connect window, then Test from Settings › Set up test.
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
      const installed = await call(platform, 'PUT', '/v1/policies/plugins', sam, { value: { 'opsai.salesforce': { enabled: true } } });
      for (const host of sf.hosts) await call(tools, 'POST', '/v1/egress/hosts', sam, { value: host, note: 'uc-607' });
      await call(tools, 'POST', '/v1/egress/ranges', sam, { value: sf.range, note: 'uc-607' });
      const toLogin = (context) =>
        context.route(`https://${SF_LOGIN}/**`, async (route) => {
          const u = new URL(route.request().url());
          const response = await route.fetch({ url: `https://${sfAddress}:${sfPort}${u.pathname}${u.search}`, headers: { ...route.request().headers(), host: SF_LOGIN }, maxRedirects: 0 });
          await route.fulfill({ response });
        });
      const browser = await chromium.launch();
      try {
        const page = await adminPage(browser, consoleUrl, 'p.shah@harborpine.example', toLogin);
        for (let i = 0; i < 20 && !((await call(tools, 'GET', '/v1/systems', priya)).data ?? []).some((c) => c.pluginId === 'opsai.salesforce'); i++) await page.waitForTimeout(1000);
        /** Fills one environment's own app in the window and signs in from its Test; the window then saves. */
        const ownApp = async (env, values, user) => {
          const window_ = page.getByTestId('connect-dialog');
          await window_.waitFor({ timeout: 30_000 });
          if (await window_.locator('#app-own').count()) await window_.locator('#app-own').click();
          const section = window_.getByTestId(`env-${env}`);
          await section.locator(`#${env}-clientId`).waitFor({ timeout: 30_000 });
          for (const [name, value] of Object.entries(values)) await section.locator(`#${env}-${name}`).fill(value);
          const tested = page.waitForResponse((r) => r.request().method() === 'POST' && /\/connections\/[^/]+\/test$/.test(r.url()), { timeout: 90_000 });
          const [popup] = await Promise.all([page.waitForEvent('popup', { timeout: 60_000 }), section.getByTestId(`test-${env}`).click()]);
          const name = popup.locator('input[name=username]');
          await name.waitFor({ timeout: 60_000 });
          await name.fill(user);
          await popup.locator('input[type=submit], button[type=submit]').first().click();
          await popup.waitForEvent('close', { timeout: 60_000 }).catch(() => {});
          await tested.catch(() => {});
          await page.waitForFunction((e) => document.querySelector(`[data-testid="health-${e}"]`)?.getAttribute('data-status'), env, { timeout: 30_000 }).catch(() => {});
          const status = await section.getByTestId(`health-${env}`).getAttribute('data-status').catch(() => null);
          await window_.getByTestId('connect-submit').click();
          await window_.waitFor({ state: 'detached', timeout: 30_000 }).catch(() => {});
          return status;
        };
        /** Production from the catalog's Connect window: the team's own app, the sign-in address, Authorize and allow. */
        const ownWindow = async (values, user) => {
          const window_ = page.getByTestId('connect-window');
          await window_.waitFor({ timeout: 30_000 });
          await window_.getByTestId('connect-window-app-own').click();
          // Authorize with the client fields empty: each says what it needs in place, and no sign-in window opens.
          let opened = false;
          const onPopup = () => (opened = true);
          page.on('popup', onPopup);
          await window_.getByTestId('connect-window-authorize').click();
          const idError = await window_.getByTestId('connect-window-client-id-error').innerText({ timeout: 10_000 }).catch(() => '');
          const secretError = await window_.getByTestId('connect-window-client-secret-error').innerText({ timeout: 10_000 }).catch(() => '');
          await page.waitForTimeout(500);
          page.off('popup', onPopup);
          await shoot(page, 'connect-required');
          check('32 an empty required field shows its error in place, and Authorize opens no sign-in window', /Enter the client ID/.test(idError) && /Enter the client secret/.test(secretError) && !opened, { idError, secretError, opened });
          await window_.getByTestId('connect-window-client-id').fill(values.clientId);
          await window_.getByTestId('connect-window-client-secret').fill(values.clientSecret);
          await window_.getByTestId('connect-window-more').click();
          await window_.getByTestId('connect-window-setting-login_url').fill(values.login_url);
          const [popup] = await Promise.all([page.waitForEvent('popup', { timeout: 60_000 }), window_.getByTestId('connect-window-authorize').click()]);
          const name = popup.locator('input[name=username]');
          await name.waitFor({ timeout: 60_000 });
          await name.fill(user);
          await popup.locator('input[type=submit], button[type=submit]').first().click();
          await popup.waitForEvent('close', { timeout: 60_000 }).catch(() => {});
          await page.waitForURL((u) => u.pathname.startsWith('/integrations/apps/'), { timeout: 60_000 });
          // The window closes on sign-in; the account's first test runs after it, in the background.
          let health = null;
          for (let i = 0; i < 30 && !health; i++) {
            const card = ((await call(tools, 'GET', '/v1/systems', priya)).data ?? []).find((c) => c.pluginId === 'opsai.salesforce');
            health = card?.environments?.production?.health?.status ?? null;
            if (!health) await page.waitForTimeout(1000);
          }
          return health;
        };
        const loginUrl = sf.authorize_url.replace(/\/authorize$/, '');
        await step("19 Salesforce's own app per environment: production in the window, the sandbox from Settings, each on its own instance", async () => {
          await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId('connect-plugin:opsai.salesforce').click();
          const live = await ownWindow({ clientId: 'ops-ai-acme', clientSecret: 'acme-connected-app-secret', login_url: loginUrl }, 'priya.live');
          await openSettings(page, consoleUrl, 'plugin:opsai.salesforce');
          await page.getByTestId('app-setup-test').click();
          const sandbox = await ownApp('test', { clientId: 'acme-sandbox-app', clientSecret: 'acme-sandbox-secret', login_url: sf.sandbox_login }, 'priya.sandbox');
          await openSettings(page, consoleUrl, 'plugin:opsai.salesforce');
          const rows = { production: await envRow(page, 'production'), test: await envRow(page, 'test') };
          await shoot(page, 'app-settings-salesforce-envs');
          const card = ((await call(tools, 'GET', '/v1/systems', priya)).data ?? []).find((c) => c.pluginId === 'opsai.salesforce');
          const detail = (await call(tools, 'GET', `/v1/connections/${card?.connectionId}`, priya)).data ?? {};
          const bases = Object.fromEntries(Object.entries(detail.environments ?? {}).map(([e, v]) => [e, v?.settings?.baseUrl]));
          check(
            "19 Salesforce's own app per environment: production in the window, the sandbox from Settings, each on its own instance",
            // The sign-in address typed on the first Connect is the one production signs in at.
            installed.status === 200 && live === 'ok' && sandbox === 'ok' && rows.production.status === 'ok' && rows.test.status === 'ok' && bases.test === sf.sandbox_base && bases.production === sf.api_base &&
              String(detail.environments?.production?.settings?.authorizeUrl ?? '').startsWith(loginUrl),
            { live, sandbox, rows, bases, authorizeUrl: detail.environments?.production?.settings?.authorizeUrl },
          );
        }, page);
        await step('30 Settings › Edit starts its saved fields blank, and saving without typing keeps every saved value', async () => {
          const card = ((await call(tools, 'GET', '/v1/systems', priya)).data ?? []).find((c) => c.pluginId === 'opsai.salesforce');
          const before = (await call(tools, 'GET', `/v1/connections/${card?.connectionId}`, priya)).data ?? {};
          await openSettings(page, consoleUrl, 'plugin:opsai.salesforce');
          await page.getByTestId('app-edit-production').click();
          const dialog = page.getByTestId('connect-dialog');
          await dialog.waitFor({ timeout: 30_000 });
          const field = await dialog.locator('#production-login_url').inputValue().catch(() => 'missing');
          const said = ((await dialog.innerText()) ?? '').replace(/\s+/g, ' ');
          await shoot(page, 'app-settings-edit-kept');
          await dialog.getByTestId('connect-submit').click();
          const closed = await dialog.waitFor({ state: 'detached', timeout: 60_000 }).then(() => true, () => false);
          const after = (await call(tools, 'GET', `/v1/connections/${card?.connectionId}`, priya)).data ?? {};
          const kept = (e) => JSON.stringify(Object.fromEntries(Object.entries(e?.environments?.production?.settings ?? {}).filter(([k]) => k !== 'scopes')));
          check(
            '30 Settings › Edit starts its saved fields blank, and saving without typing keeps every saved value',
            field === '' && /Blank keeps the saved value/.test(said) && closed && kept(after) === kept(before),
            { field, closed, before: kept(before), after: kept(after) },
          );
        }, page);
        await step("21 when Salesforce refuses the team account's refresh, its account reads Expired with Reconnect, and signing in again makes it work", async () => {
          await sfControl('mode', { failNext: 401, refuseRefresh: true });
          await openSettings(page, consoleUrl, 'plugin:opsai.salesforce');
          const failed = page.waitForResponse((r) => r.request().method() === 'POST' && /\/connections\/[^/]+\/test$/.test(r.url()), { timeout: 60_000 });
          await page.getByTestId('app-test-production').click();
          await failed.catch(() => {});
          await sfControl('mode', {});
          await page.reload({ waitUntil: 'domcontentloaded' });
          const button = page.getByTestId('app-reconnect');
          await button.waitFor({ timeout: 60_000 }).catch(async (e) => {
            // What the Accounts section and the card say instead, so a red run says why.
            const card = ((await call(tools, 'GET', '/v1/systems', priya)).data ?? []).find((c) => c.pluginId === 'opsai.salesforce');
            console.log('accounts:', ((await page.locator('main').innerText().catch(() => '')) ?? '').replace(/\s+/g, ' ').slice(0, 500), 'card:', JSON.stringify({ state: card?.state, status: card?.status }));
            throw e;
          });
          const accounts = ((await page.getByTestId('app-accounts').innerText()) ?? '').replace(/\s+/g, ' ');
          await shoot(page, 'app-account-expired');
          const [again] = await Promise.all([page.waitForEvent('popup', { timeout: 60_000 }), button.click()]);
          const name = again.locator('input[name=username]');
          await name.waitFor({ timeout: 60_000 });
          await name.fill('priya.live');
          await again.locator('input[type=submit], button[type=submit]').first().click();
          await again.waitForEvent('close', { timeout: 60_000 }).catch(() => {});
          await openSettings(page, consoleUrl, 'plugin:opsai.salesforce');
          const retest = page.waitForResponse((r) => r.request().method() === 'POST' && /\/connections\/[^/]+\/test$/.test(r.url()), { timeout: 60_000 });
          await page.getByTestId('app-test-production').click();
          await retest.catch(() => {});
          const card = ((await call(tools, 'GET', '/v1/systems', priya)).data ?? []).find((c) => c.pluginId === 'opsai.salesforce');
          const after = (await call(tools, 'GET', `/v1/connections/${card?.connectionId}`, priya)).data ?? {};
          check(
            "21 when Salesforce refuses the team account's refresh, its account reads Expired with Reconnect, and signing in again makes it work",
            /Expired/.test(accounts) && after.status === 'healthy' && after.environments?.production?.health?.status === 'ok',
            { accounts: accounts.slice(0, 200), status: after.status, health: after.environments?.production?.health },
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
