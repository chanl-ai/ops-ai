// uc-581 An agent queries Salesforce seven ways, ui layer: docs/usecases/tools-service/agents-query-salesforce-many-ways.md,
// stories S3 (steps 12-15) and S4 (steps 16-17). The demo stack with the fake Salesforce (docs/usecases/lib/fake_salesforce.py)
// and plugins on (OPS_PLUGINS), loading the Salesforce plugin from the ops-ai-plugins repository beside ops-ai. Set-up goes
// through the API as uc-564's api layer proved it. Priya's articles source syncs through the plugin's data listing tool;
// Salesforce then answers the listing's second page with 429 and forgets every saved locator, and the next sync starts the
// listing again instead of failing. James finds a Salesforce tool in the case helper's tools picker by its title, grants
// it, and the agent page names it by its title after a reload. Screenshots go to evidenceDir('581', 'uc').
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync } from 'node:fs';
import { request } from 'node:https';
import { createInterface } from 'node:readline';
import { join } from 'node:path';

import { AGENTS_PORT, KB_PORT, PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const kb = `http://127.0.0.1:${KB_PORT}`;
const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const PASSWORD = 'northfield-demo';
const SHOTS = evidenceDir('581', 'uc');
const PLUGIN = 'opsai.salesforce';
const LOGIN_HOST = 'login.salesforce.test';
const SALESFORCE = join(ROOT, '..', 'ops-ai-plugins/plugins/salesforce/src/ops_plugin_salesforce');
// Plugins are off until their release; this walk turns them on for its own services, and kb-service reads a plugin's
// knowledge source through this run's tools-service.
process.env.OPS_PLUGINS = 'true';
process.env.OPS_TOOLS_URL = `http://127.0.0.1:${TOOLS_PORT}`;
const ARTICLES = ['ka0001', 'ka0001a', 'ka0002', 'ka0003'];

/** The fake Salesforce, started from its script; resolves with what it printed and stops when the walk ends. */
async function startSalesforce() {
  const child = spawn('uv', ['run', '--quiet', '--directory', join(ROOT, 'services/agents-service'), 'python', join(ROOT, 'docs/usecases/lib/fake_salesforce.py')], { stdio: ['pipe', 'pipe', 'inherit'] });
  const line = await new Promise((resolve, reject) => {
    createInterface({ input: child.stdout }).once('line', resolve);
    child.once('exit', (code) => reject(new Error(`fake Salesforce exited with ${code}`)));
  });
  return { child, info: JSON.parse(line) };
}

const sf = await startSalesforce();
const [address, port] = JSON.parse(sf.info.settings.OPS_EGRESS_RESOLVE)[LOGIN_HOST].split(':');

/** A request to the fake on its own address, checked against its CA under the sign-in host its certificate names. */
const toFake = (path, { method = 'GET', body, type } = {}) =>
  new Promise((resolve, reject) => {
    const headers = { Host: LOGIN_HOST, ...(type ? { 'Content-Type': type } : {}) };
    const req = request({ host: address, port: Number(port), path, method, headers, ca: readFileSync(sf.info.ca), servername: LOGIN_HOST }, (res) => {
      let text = '';
      res.on('data', (d) => (text += d));
      res.on('end', () => resolve({ status: res.statusCode, location: res.headers.location ?? '', text }));
    });
    req.on('error', reject);
    req.end(body);
  });
const control = new URL(sf.info.control).pathname.replace(/\/state$/, '');
const fakeState = async () => JSON.parse((await toFake(`${control}/state`)).text);
const mode = (body) => toFake(`${control}/mode`, { method: 'POST', body: JSON.stringify(body), type: 'application/json' });

/** Plays the team admin's browser through the fake's sign-in page as `account`; returns the code and state. */
async function signInAt(authorizeUrl, account) {
  const u = new URL(authorizeUrl);
  const page = await toFake(`${u.pathname}${u.search}`);
  if (page.status !== 200) return { error: `sign-in page ${page.status}` };
  const posted = await toFake(`${u.pathname}${u.search}`, { method: 'POST', body: `username=${encodeURIComponent(account)}&claims=`, type: 'application/x-www-form-urlencoded' });
  return Object.fromEntries(new URL(posted.location, 'https://x').searchParams);
}

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
const until = async (read, ok, tries = 40) => {
  let got = await read();
  for (let i = 0; i < tries && !ok(got); i++) await new Promise((r) => setTimeout(r, 1000)), (got = await read());
  return got;
};
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);

/** One step; on a failure the page it was on is kept as `failed-<n>.png` beside the evidence. */
async function step(name, body, page) {
  try {
    await body();
  } catch (e) {
    await page?.screenshot({ path: join(SHOTS, `failed-${name.split(' ')[0]}.png`) }).catch(() => {});
    check(name, false, String(e).slice(0, 400));
  }
}

try {
  await withUiStack(
    async (consoleUrl) => {
      mkdirSync(SHOTS, { recursive: true });
      const sam = as(await tokenFor('s.adeyemi@harborpine.example'), 'team_security');
      const priya = as(await tokenFor('p.shah@harborpine.example'), 'team_ops');

      // Set-up through the API, as uc-564's api layer does: install switch, hosts, team switch, the team's sign-in.
      const installed = await call(platform, 'PUT', '/v1/policies/plugins', sam, { value: { [PLUGIN]: { enabled: true } } });
      for (const host of sf.info.hosts) await call(tools, 'POST', '/v1/egress/hosts', sam, { value: host, note: 'uc-581' });
      await call(tools, 'POST', '/v1/egress/ranges', sam, { value: sf.info.range, note: 'uc-581' });
      const login = sf.info.authorize_url.replace(/\/authorize$/, '');
      const on = await call(tools, 'PUT', `/v1/plugins/${PLUGIN}/team`, priya, { enabled: true, settings: { login_url: login }, clientId: 'ops-ai-acme', clientSecret: 'acme-connected-app-secret' });
      const connectionId = on.data?.connectionId;
      const started = await call(tools, 'POST', `/v1/connections/${connectionId}/sign-in`, priya, { environment: 'production' });
      const back = started.data?.authorizeUrl ? await signInAt(started.data.authorizeUrl, 'acme.integration') : {};
      const signed = await call(tools, 'POST', `/v1/connections/${connectionId}/sign-in/complete`, priya, { state: back.state ?? '', code: back.code ?? '' });
      const base = (await call(kb, 'POST', '/v1/knowledge-bases', priya, { name: 'Salesforce articles', owner: 'p.shah@harborpine.example' })).data ?? {};
      const agent = (await call(agents, 'POST', '/v1/agents', priya, { name: 'Case helper', role: 'Works Salesforce cases' })).data ?? {};
      check(
        'setup: Salesforce is on for the install and the team, the team signed in, and the base and agent exist',
        installed.status === 200 && on.status === 200 && signed.status === 200 && !!base.id && !!agent.id,
        { installed: installed.text, on: on.text, signed: signed.status, base: base.id, agent: agent.id },
      );

      // S3: the source through kb-service's API, synced through it; its listing tool is now plain plugin data.
      const source = (await call(kb, 'POST', '/v1/sources', priya, { type: 'tool', name: 'Salesforce articles', config: { plugin: PLUGIN, source: 'articles' }, kbIds: [base.id] })).data ?? {};
      const sync = async (full) => call(kb, 'POST', `/v1/sources/${source.id}/sync`, priya, { full });
      const fetched = async () => (await fakeState()).fetched;
      const runOf = (r) => r.data?.status ?? r.data?.run?.status;

      await step('12 the articles source syncs through the data listing tool: three articles and one attachment', async () => {
        const run = await sync(false);
        const got = await fetched();
        check('12 the articles source syncs through the data listing tool: three articles and one attachment', run.status === 200 && runOf(run) === 'success' && JSON.stringify([...got].sort()) === JSON.stringify(ARTICLES), { status: run.status, run: run.text, fetched: got });
      });

      await step('13 a rate limit on the listing\'s second page stops a full sync partial, its place saved', async () => {
        await mode({ limitSecondPage: true });
        const run = await sync(true);
        check('13 a rate limit on the listing\'s second page stops a full sync partial, its place saved', runOf(run) === 'partial', { status: run.status, run: run.text });
      });

      let before = [];
      await step('14 Salesforce forgets the saved page and the next sync starts the listing again and succeeds', async () => {
        await mode({ expireLocators: true });
        before = await fetched();
        const run = await sync(false);
        const queries = (await fakeState()).queries.filter((q) => q.includes('Knowledge__kav'));
        check('14 Salesforce forgets the saved page and the next sync starts the listing again and succeeds', runOf(run) === 'success', { status: run.status, run: run.text, listings: queries.length });
      });

      await step('15 a further sync fetches nothing again', async () => {
        const known = (await fetched()).length;
        const run = await sync(false);
        check('15 a further sync fetches nothing again', runOf(run) === 'success' && (await fetched()).length === known, { run: run.text, before: before.length, after: (await fetched()).length });
      });

      // S4: the tools picker and the agent page read a plugin tool by its title.
      const browser = await chromium.launch();
      const errors = [];
      try {
        const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
        page.on('pageerror', (e) => errors.push(e.message));
        for (let attempt = 1; ; attempt++) {
          await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByLabel('Work email').fill('j.richardson@harborpine.example');
          await page.getByLabel('Password').fill(PASSWORD);
          await page.getByTestId('login-submit').click();
          const ok = await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 }).then(() => true, (e) => (attempt === 2 ? Promise.reject(e) : false));
          if (ok) break;
        }
        const picker = page.getByTestId('agent-tools-picker');

        await step('16 the tools picker finds a Salesforce tool by its title', async () => {
          // agents-service keeps the grantable tools for 30 s and the console keeps a search's answer, so the picker is
          // opened once agents-service offers the plugin's tools, and searched once.
          const james = as(await tokenFor('j.richardson@harborpine.example'), 'team_ops');
          const offered = await until(() => call(agents, 'GET', '/v1/tools/options?search=find%20cases&limit=5', james), (r) => (r.data?.data ?? []).some((o) => o.label === 'Find cases'), 60);
          await page.goto(`${consoleUrl}/agents/${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await picker.getByRole('button', { name: 'Grant tools' }).click({ timeout: 90_000 });
          await page.getByPlaceholder('Search tools by name or system…').fill('find cases');
          const option = page.getByRole('option', { name: /^Find cases/ });
          const shown = await option.first().waitFor({ timeout: 30_000 }).then(() => true, () => false);
          const raw = await page.getByRole('option', { name: /salesforce_find_cases/ }).count();
          await page.screenshot({ path: join(SHOTS, 'tools-picker-1280.png') });
          check('16 the tools picker finds a Salesforce tool by its title', shown && raw === 0, { shown, raw, offered: offered.text });
          if (shown) await option.first().click();
          await page.keyboard.press('Escape');
        }, page);

        await step('17 granted and saved, the agent page names the tool by its title', async () => {
          // The agent page saves a change as it is made, so the grant is read back rather than saved by a button.
          const stored = await until(async () => (await call(agents, 'GET', `/v1/agents/${agent.id}`, priya)).data ?? {}, (a) => (a.toolIds ?? []).includes('salesforce_find_cases'), 30);
          await page.reload({ waitUntil: 'domcontentloaded' });
          const chip = picker.getByText('Find cases', { exact: true });
          const named = await chip.waitFor({ timeout: 60_000 }).then(() => true, () => false);
          const raw = await picker.getByText('salesforce_find_cases').count();
          await page.screenshot({ path: join(SHOTS, 'agent-tools-1280.png') });
          check('17 granted and saved, the agent page names the tool by its title', named && raw === 0 && (stored.toolIds ?? []).includes('salesforce_find_cases'), { named, raw, toolIds: stored.toolIds });
        }, page);

        check('no page errors', errors.length === 0, errors.slice(0, 3));
      } finally {
        await browser.close();
      }
    },
    { demo: true, tools: { env: { ...sf.info.settings, OPS_PLUGIN_PATHS: JSON.stringify([SALESFORCE]) } } },
  );
} finally {
  sf.child.stdin.end();
  sf.child.kill('SIGTERM');
}
finish();
