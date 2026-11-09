// uc-628 An admin turns an app on in one window, ui layer: docs/usecases/tools-service/turn-on-in-one-window.md.
// Priya turns Salesforce and GitHub on in the one Turn on window at 1280 and 390, against the fake Salesforce (on its
// My Domain) and the plugins repo's fake GitHub. Turn on saves the team's setting and opens no sign-in window; her own
// sign-in is the optional Connect my account after it. Ravi, a viewer, sees no Connect and who can; and James's first
// chat with the team's assistant asks him for his own Salesforce account. Screenshots go to OPS_USECASE_SHOTS when set.
import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { createInterface } from 'node:readline';
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const agentsUrl = `http://127.0.0.1:${AGENTS_PORT}`;
const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const PASSWORD = 'northfield-demo';
const SHOTS = process.env.OPS_USECASE_SHOTS || evidenceDir('628', 'uc');
const PLUGINS = join(process.env.OPS_PLUGINS_REPO || join(ROOT, '..', 'ops-ai-plugins'), 'plugins');
const LIB = join(ROOT, 'docs/usecases/lib');

async function startFake(name, script, args = []) {
  const child = spawn('uv', ['run', '--quiet', '--directory', join(ROOT, 'services/agents-service'), 'python', script, ...args], { stdio: ['pipe', 'pipe', 'inherit'], env: { ...process.env, PYTHONPATH: LIB } });
  const line = await new Promise((resolve, reject) => {
    createInterface({ input: child.stdout }).once('line', resolve);
    child.once('exit', (code) => reject(new Error(`${name} exited with ${code}`)));
  });
  return { name, child, info: JSON.parse(line) };
}

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
  const github = await startFake('fake GitHub', join(PLUGINS, 'github/tests/fake_github.py'), ['--dir', mkdtempSync(join(tmpdir(), 'uc628-github-'))]);
  github.serves = true;
  fakes.push(github);
  const sf = await startFake('fake Salesforce', join(LIB, 'fake_salesforce.py'));
  fakes.push(sf);
  const caDir = mkdtempSync(join(tmpdir(), 'uc628-ca-'));
  const caFile = join(caDir, 'fakes.crt');
  writeFileSync(caFile, [github.info.ca, sf.info.settings.OPS_EGRESS_CA_FILE].map((f) => readFileSync(f, 'utf8')).join('\n'));
  const resolve = { ...github.info.resolve, ...JSON.parse(sf.info.settings.OPS_EGRESS_RESOLVE) };
  const hosts = [...github.info.hosts, ...sf.info.hosts];
  const ranges = [...new Set([github.info.range, sf.info.range])];

  const APPS = [
    { id: 'plugin:opsai.salesforce', name: 'Salesforce', place: new URL(sf.info.login_url).host, allow: (popup) => mockAllow(popup, 'acme.integration'), ready: (popup) => popup.locator('input[name=username]').waitFor({ timeout: 60_000 }) },
    // The fake GitHub's own addresses, typed under More options as uc-625 does: the real one is github.com.
    { id: 'plugin:opsai.github', name: 'GitHub', settings: github.info.settings, allow: (popup) => popup.getByRole('button', { name: 'Authorize' }).click({ timeout: 60_000 }), ready: (popup) => popup.getByRole('button', { name: 'Authorize' }).waitFor({ timeout: 60_000 }) },
  ];

  async function mockAllow(popup, user) {
    const name = popup.locator('input[name=username]');
    await name.waitFor({ timeout: 60_000 });
    await name.fill(user);
    await popup.locator('input[type=submit], button[type=submit]').first().click();
  }

  const tokenFor = async (email) => (await (await fetch(`${platform}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
  const as = (token, team) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
  const call = async (base, method, path, headers, body) => {
    const r = await fetch(`${base}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    const json = await r.json().catch(() => null);
    return { status: r.status, data: json?.data };
  };

  async function signedIn(browser, consoleUrl, email, width) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, ignoreHTTPSErrors: true });
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
    await page.getByLabel('Work email').fill(email, { timeout: 120_000 });
    await page.getByLabel('Password').fill(PASSWORD);
    await page.getByTestId('login-submit').click();
    await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
    return page;
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
      const sam = as(await tokenFor('s.adeyemi@harborpine.example'), 'team_security');
      const priya = as(await tokenFor('p.shah@harborpine.example'), 'team_ops');
      for (const host of hosts) await call(tools, 'POST', '/v1/egress/hosts', sam, { value: host, note: 'uc-628' });
      for (const range of ranges) await call(tools, 'POST', '/v1/egress/ranges', sam, { value: range, note: 'uc-628' });
      const browser = await chromium.launch();
      const errors = [];
      try {
        for (const width of [1280, 390]) {
          for (const app of APPS) {
            const tag = `${app.name.toLowerCase()}-${width}`;
            // Each width starts from the app off, as an admin first meets it.
            const card = ((await call(tools, 'GET', '/v1/apps', priya)).data ?? []).find((c) => c.id === app.id);
            if (card?.connectionId) {
              await call(tools, 'PUT', `/v1/apps/${encodeURIComponent(app.id)}/team`, priya, { enabled: false });
              await call(tools, 'DELETE', `/v1/apps/${encodeURIComponent(app.id)}/accounts/${card.connectionId}`, priya);
            }
            const page = await signedIn(browser, consoleUrl, 'p.shah@harborpine.example', width);
            await step(`1 ${tag}: the Turn on window asks where you sign in and whose account, with the assistant box ticked`, async () => {
              await page.goto(`${consoleUrl}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
              await page.getByTestId(`connect-${app.id}`).click({ timeout: 90_000 });
              const win = page.getByTestId('connect-window');
              await win.waitFor({ timeout: 30_000 });
              const title = (await win.getByRole('heading').first().innerText()).trim();
              const whose = await win.getByTestId('connect-window-whose').isVisible().catch(() => false);
              const assistant = await win.getByTestId('connect-window-assistant').getAttribute('data-state');
              const test = await win.getByTestId('connect-window-test-account').isVisible().catch(() => false);
              if (app.place) {
                await win.getByTestId('connect-window-place-login_url').click();
                await page.getByTestId('connect-window-place-login_url-other').click();
                await win.getByTestId('connect-window-place-login_url-host').fill(app.place);
              }
              await page.screenshot({ path: join(SHOTS, `turn-on-${tag}.png`), fullPage: true });
              for (const [name, value] of Object.entries(app.settings ?? {})) {
                if (!(await win.getByTestId(`connect-window-setting-${name}`).isVisible())) await win.getByTestId('connect-window-more').click();
                await win.getByTestId(`connect-window-setting-${name}`).fill(value);
              }
              const button = (await page.getByTestId('connect-window-authorize').innerText()).trim();
              check(`1 ${tag}: the Turn on window asks where you sign in and whose account, with the assistant box ticked`, title === `Turn on ${app.name} for Operations` && whose && assistant === 'checked' && !test && button === 'Turn on', { title, whose, assistant, test, button });
              // Turn on saves the team's setting and stops: no sign-in window opens, and the saved state says what
              // members do next.
              const popups = [];
              page.on('popup', (p) => popups.push(p.url()));
              await page.getByTestId('connect-window-authorize').click();
              const result = win.getByTestId('connect-window-result');
              await result.waitFor({ timeout: 60_000 });
              await page.waitForTimeout(3000);
              const saved = (await result.innerText()).replace(/\s+/g, ' ');
              const after = ((await call(tools, 'GET', '/v1/apps', priya)).data ?? []).find((c) => c.id === app.id);
              await page.screenshot({ path: join(SHOTS, `saved-${tag}.png`), fullPage: true });
              check(`2 ${tag}: Turn on saves the team's setting and opens no sign-in window`, popups.length === 0 && Boolean(after?.connectionId) && new RegExp(`Saved\\. ${app.name} is on for Operations`).test(saved) && /\d+ read tools? added/.test(saved) && /Members connect their own account from Connectors › Mine|team’s .* account once someone connects it/.test(saved), { popups, connectionId: after?.connectionId, saved });
              // Connecting her own account is the optional second step.
              const [popup] = await Promise.all([page.waitForEvent('popup', { timeout: 60_000 }), win.getByTestId('connect-window-connect-mine').click()]);
              await app.ready(popup).catch(async (e) => {
                await popup.screenshot({ path: join(SHOTS, `failed-sign-in-page-${tag}.png`) }).catch(() => {});
                throw new Error(`${String(e).split('\n')[0]}; the sign-in window is at ${popup.url()}: ${((await popup.locator('body').innerText().catch(() => '')) ?? '').slice(0, 200)}`);
              });
              await app.allow(popup);
              await popup.waitForEvent('close', { timeout: 60_000 }).catch(() => undefined);
              await win.getByText(/Connected as/).waitFor({ timeout: 60_000 });
              const said = (await result.innerText()).replace(/\s+/g, ' ');
              await page.screenshot({ path: join(SHOTS, `turned-on-${tag}.png`), fullPage: true });
              check(`2b ${tag}: Connect my account signs her in, and the window says who is connected and that the assistant has the read tools`, /Connected as/.test(said) && /\d+ read tools? added/.test(said) && /(given to|already)|Ops Assistant/.test(said) && !/write tool[s]? added/.test(said), said);
              await page.getByTestId('connect-window-done').click();
            }, page);
            errors.push(...page.errors);
            await page.context().close();
          }
          const ravi = await signedIn(browser, consoleUrl, 'r.menon@harborpine.example', width);
          await step(`3 ${width}: a viewer cannot turn an app on: the app's page offers only signing in from Mine`, async () => {
            await ravi.goto(`${consoleUrl}/integrations/apps/${encodeURIComponent(APPS[0].id)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
            const own = ravi.getByTestId('app-own-sign-in');
            await own.waitFor({ timeout: 60_000 });
            const href = await own.getAttribute('href');
            const connect = await ravi.getByTestId('app-connect').count();
            await ravi.screenshot({ path: join(SHOTS, `viewer-${width}.png`), fullPage: true });
            check(`3 ${width}: a viewer cannot turn an app on: the app's page offers only signing in from Mine`, connect === 0 && href === '/integrations/my-accounts', { connect, href });
          }, ravi);
          errors.push(...ravi.errors);
          await ravi.context().close();
        }
        const james = await signedIn(browser, consoleUrl, 'j.richardson@harborpine.example', 1280);
        await step('4 James’s first chat with the team’s assistant asks for his own Salesforce account', async () => {
          const thread = (await call(agentsUrl, 'POST', '/v1/chat/threads', as(await tokenFor('j.richardson@harborpine.example'), 'team_ops'), { kbIds: [] })).data;
          await james.goto(`${consoleUrl}/chat/${thread.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const box = james.getByRole('textbox', { name: 'Message' });
          await box.waitFor({ timeout: 120_000 });
          await box.fill('What is the status of Salesforce case 00044818?');
          await james.getByRole('button', { name: 'Send', exact: true }).click();
          const card = james.getByTestId('connection-required');
          await card.waitFor({ timeout: 120_000 });
          // Connect is offered once the reply has finished streaming; the card shows before it.
          await james.getByTestId('connection-connect').waitFor({ timeout: 120_000 });
          const text = (await card.innerText()).replace(/\s+/g, ' ');
          await james.screenshot({ path: join(SHOTS, 'first-chat-connect-card.png'), fullPage: true });
          check('4 James’s first chat with the team’s assistant asks for his own Salesforce account', /Salesforce/.test(text) && /Connect Salesforce/.test(text), text.slice(0, 300));
        }, james);
        errors.push(...james.errors);
        check('5 no page errors', errors.length === 0, errors.slice(0, 3));
      } finally {
        await browser.close();
      }
    },
    {
      // demo: chat turns run through models-service on the fake OpenAI with the demo's rules, which call
      // salesforce_query for a case's status.
      demo: true,
      platform: true,
      tools: {
        gateway: true,
        env: {
          OPS_EGRESS_CA_FILE: caFile,
          OPS_EGRESS_RESOLVE: JSON.stringify(resolve),
          OPS_PLUGINS: 'true',
          OPS_PLUGIN_PATHS: JSON.stringify([join(PLUGINS, 'github/src/ops_plugin_github'), join(PLUGINS, 'salesforce/src/ops_plugin_salesforce')]),
          OPS_PLUGIN_CLIENTS: JSON.stringify({ 'opsai.github': { id: github.info.client_id, secret: github.info.client_secret }, 'opsai.salesforce': { id: 'ops-ai-acme', secret: 'acme-connected-app-secret' } }),
        },
      },
    },
  );
} finally {
  for (const fake of fakes) await stopFake(fake);
}
finish();
