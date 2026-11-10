// uc-697 A chat uses the account picked for it, and a new chat starts on the default, ui layer:
// docs/usecases/agents-service/a-chat-uses-the-account-picked-for-it.md. Salesforce has two team accounts on the fake
// Salesforce (Retail org, the team default, and EU org, at two My Domains), both signed in. Maya opens a chat with an
// agent holding salesforce_query: the picker says Retail org; she changes it to EU org and asks; the fake records the
// query on the EU org's host and the chat's connectors answer names EU org. Screenshots go to OPS_USECASE_SHOTS when
// set (the evidence folder otherwise), at 1440 and 390.
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync } from 'node:fs';
import { request } from 'node:https';
import { createInterface } from 'node:readline';
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const PASSWORD = 'northfield-demo';
const PRIYA = 'p.shah@harborpine.example';
const MAYA = 'm.okafor@harborpine.example';
const SHOTS = process.env.OPS_USECASE_SHOTS || evidenceDir('697', 'uc');
const SALESFORCE = join(process.env.OPS_PLUGINS_REPO || join(ROOT, '..', 'ops-ai-plugins'), 'plugins/salesforce/src/ops_plugin_salesforce');
const LIB = join(ROOT, 'docs/usecases/lib');
const APP = 'plugin:opsai.salesforce';
const QUERY = "SELECT Id, CaseNumber, Status FROM Case WHERE CaseNumber = '00044818'";

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

/**
 * One https request to the fake on its private address, naming `host` (the login host when none), checked against the
 * run's own certificate authority, which tools-service trusts the same way.
 */
function fakeRequest(url, { method = 'GET', host, body, headers = {} } = {}) {
  const name = host ?? fake.info.hosts[0];
  const u = new URL(url);
  return new Promise((resolve, reject) => {
    const r = request(
      { hostname: u.hostname, port: u.port, path: u.pathname + u.search, method, ca: readFileSync(fake.info.ca), servername: name, headers: { Host: name, ...(body ? { 'Content-Length': Buffer.byteLength(body) } : {}), ...headers } },
      (res) => {
        let text = '';
        res.on('data', (c) => (text += c));
        res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, text }));
      },
    );
    r.on('error', reject);
    if (body) r.write(body);
    r.end();
  });
}

let fake;
try {
  fake = await startFake();
  const sf = fake.info;
  const resolveMap = JSON.parse(sf.settings.OPS_EGRESS_RESOLVE);
  const tokenFor = async (email) => (await (await fetch(`${platform}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
  const as = (token, team) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
  const call = async (base, method, path, headers, body) => {
    const r = await fetch(`${base}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    const json = await r.json().catch(() => null);
    return { status: r.status, data: json?.data, text: JSON.stringify(json).slice(0, 300) };
  };
  /** The fake's org host of every query it answered since `since` calls. */
  const fakeCalls = async () => JSON.parse((await fakeRequest(sf.control)).text).calls;
  const queriesSince = async (since) => (await fakeCalls()).slice(since).filter((c) => c.path.endsWith('/query')).map((c) => c.host);

  /** Plays the browser through a team account's sign-in on the fake, as several_accounts.py's Rig.sign_in does. */
  async function signIn(priya, accountId, user) {
    const started = await call(tools, 'POST', `/v1/apps/${encodeURIComponent(APP)}/accounts/${accountId}/sign-in`, priya, { account: 'team' });
    const opened = new URL(started.data?.authorizeUrl ?? 'https://none.test/');
    // Every fake host is served on one address; the sign-in page is reached there with its own host named.
    const target = `https://${resolveMap[sf.hosts[0]]}${opened.pathname}${opened.search}`;
    const page = await fakeRequest(target, { host: opened.hostname });
    // The sign-in form is tied to the page's session cookie, as a browser keeps it.
    const cookie = [page.headers['set-cookie'] ?? []].flat().map((c) => c.split(';')[0]).join('; ');
    const posted = await fakeRequest(target, { method: 'POST', host: opened.hostname, body: new URLSearchParams({ username: user, claims: '' }).toString(), headers: { 'Content-Type': 'application/x-www-form-urlencoded', ...(cookie ? { Cookie: cookie } : {}) } });
    const back = new URL(posted.headers.location ?? 'https://none.test/').searchParams;
    const done = await call(tools, 'POST', '/v1/sign-ins/complete', priya, { state: back.get('state') ?? '', code: back.get('code') ?? '' });
    return { started: started.status, opened: opened.host, page: page.status, posted: posted.status, done: done.status, text: done.text.slice(0, 160) };
  }

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
  const shot = (page, name) => page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: true });
  const openPicker = async (page) => {
    await page.getByTestId('connectors-picker').click();
    await page.getByTestId('connectors-picker-list').waitFor({ timeout: 30_000 });
  };
  const accountLine = (page) => page.getByTestId(`connector-account-${APP}`);

  await withUiStack(
    async (consoleUrl) => {
      mkdirSync(SHOTS, { recursive: true });
      const sam = as(await tokenFor('s.adeyemi@harborpine.example'), 'team_security');
      const priya = as(await tokenFor(PRIYA), 'team_ops');
      const maya = as(await tokenFor(MAYA), 'team_ops');
      await call(tools, 'POST', '/v1/egress/ranges', sam, { value: sf.range, note: 'uc-697' });
      const on = await call(tools, 'PUT', `/v1/apps/${encodeURIComponent(APP)}/team`, priya, { enabled: true, signIn: 'team', accountName: 'Retail org', settings: { login_url: sf.login_url } });
      const eu = await call(tools, 'POST', `/v1/apps/${encodeURIComponent(APP)}/accounts`, priya, { name: 'EU org', settings: { login_url: sf.eu_login_url } });
      const retailIn = await signIn(priya, on.data?.connectionId, 'kestrel.integration');
      const euIn = await signIn(priya, eu.data?.id, 'kestrel.eu');
      const agent = await call(agents, 'POST', '/v1/agents', priya, { name: 'Case desk', role: 'Answers the team about cases' });
      const draft = await call(agents, 'PATCH', `/v1/agents/${agent.data?.id}`, priya, { toolIds: ['salesforce_query'] });
      const asked = await call(agents, 'POST', `/v1/agents/${agent.data?.id}/publish-requests`, priya, { version: draft.data?.version, note: 'uc-697' });
      check(
        '0 Salesforce has Retail org (default) and EU org, both signed in, and Case desk holds salesforce_query',
        on.status === 200 && eu.status === 201 && retailIn.done === 200 && euIn.done === 200 && draft.status === 200 && asked.status < 300,
        { on: on.text, eu: eu.text, retailIn, euIn, draft: draft.text, asked: asked.text },
      );
      const browser = await chromium.launch();
      try {
        for (const width of [1440, 390]) {
          const page = await signedIn(browser, consoleUrl, MAYA, width);
          let thread = '';
          await step(`1 at ${width} a new chat's picker says Salesforce uses Retail org, the team default`, async () => {
            await page.goto(`${consoleUrl}/chat?agent=${agent.data?.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
            await page.getByLabel('Message').waitFor({ timeout: 120_000 });
            await openPicker(page);
            const line = ((await accountLine(page).innerText({ timeout: 60_000 })) ?? '').trim();
            await shot(page, `chat-new-picker-${width}`);
            await page.keyboard.press('Escape');
            check(`1 at ${width} a new chat's picker says Salesforce uses Retail org, the team default`, line.startsWith('Uses Retail org'), line);
          }, page);
          await step(`2 at ${width} Maya changes the chat to EU org and her query runs in the EU org`, async () => {
            const box = page.getByLabel('Message');
            await box.fill('Hello.');
            await page.getByRole('button', { name: 'Send', exact: true }).click();
            await page.waitForURL((u) => /\/chat\/th_/.test(u.pathname), { timeout: 90_000 });
            thread = new URL(page.url()).pathname.split('/').pop();
            await openPicker(page);
            await page.getByTestId(`connector-change-${APP}`).click();
            await page.getByTestId(`connector-pick-${APP}-EU org`).click();
            await page.waitForFunction((id) => document.querySelector(`[data-testid="connector-account-${id}"]`)?.textContent?.startsWith('Uses EU org'), APP, { timeout: 30_000 });
            await shot(page, `chat-picked-eu-${width}`);
            await page.keyboard.press('Escape');
            const before = (await fakeCalls()).length;
            await box.fill(`call salesforce_query {"q": "${QUERY}"}`);
            await page.getByRole('button', { name: 'Send', exact: true }).click();
            const deadline = Date.now() + 60_000;
            let hosts = [];
            while (Date.now() < deadline && !hosts.length) {
              await new Promise((r) => setTimeout(r, 500));
              hosts = await queriesSince(before);
            }
            await page.getByText('00044818').last().waitFor({ timeout: 60_000 }).catch(() => {});
            await shot(page, `chat-answer-eu-${width}`);
            check(`2 at ${width} Maya changes the chat to EU org and her query runs in the EU org`, JSON.stringify(hosts) === JSON.stringify(['kestrel-eu.my.salesforce.test']), { hosts, thread });
          }, page);
          await step(`3 at ${width} the chat's connectors answer names EU org for Salesforce`, async () => {
            const got = await call(agents, 'GET', `/chat/threads/${thread}/connectors`, maya);
            const row = (got.data?.connectors ?? []).find((c) => c.appId === APP) ?? {};
            check(`3 at ${width} the chat's connectors answer names EU org for Salesforce`, Boolean(thread) && row.account === 'EU org', { status: got.status, account: row.account, text: got.text });
          }, page);
          check(`4 at ${width} no page errors`, page.errors.length === 0, page.errors.slice(0, 3));
          await page.context().close();
        }
      } finally {
        await browser.close();
      }
    },
    {
      platform: true,
      tools: {
        gateway: true,
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
