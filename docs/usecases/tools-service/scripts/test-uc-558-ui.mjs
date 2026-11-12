// uc-558 People connect their own Salesforce account, ui layer: docs/usecases/tools-service/per-person-sign-in.md
//. The demo stack and a fake Salesforce (docs/usecases/lib/fake_salesforce.py:
// a real OAuth server and an API that records whose token edited a case). James asks in chat to move a case; the call
// is refused with a Connect card, he signs in through the pop-up as handler@kestrel.example, and the chat goes on:
// Salesforce records exactly one edit, his. My accounts (Apps menu) lists the sign-in and Disconnect removes it. Priya,
// an admin, connects her own account on the app's page. The card and My accounts are checked again at 375 px.
// Screenshots go to evidenceDir('558', 'uc').
import { execFileSync, spawn } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { request } from 'node:https';
import { createInterface } from 'node:readline';
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, evidenceDir, finish, withUiStack, required } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const PASSWORD = 'northfield-demo';
const SHOTS = evidenceDir('558', 'uc');
const CASE = '5003000000D8cuIAAR';
const LOGIN_HOST = 'login.salesforce.test';

// The fake model's answers for this walk: the move asks for the update tool, the follow-up after connecting asks for
// it again, and each answer says what happened. The demo's own rules follow, so its set-up answers as it always does.
// The folder is repo-relative: the harness joins it to the repo root.
const OURS = [
  {"when": "\\bmove case (?P<case>\\S+) to (?P<status>[^.\\n]+)", "tool": "uc558_update_case", "arguments": {"status": "{status}"}},
  {"when": "\\bI connected (?P<system>[^.\\n]+)\\. Please go ahead", "tool": "uc558_update_case", "arguments": {"status": "Awaiting documents"}},
  {"after": "uc558_update_case", "result": "has not connected their own", "text": "I did not change the case: Salesforce needs your own account for that. Connect it from the card above and I will go ahead."},
  {"after": "uc558_update_case", "text": "The case is now Awaiting documents, changed with your Salesforce account."},
];
const RULES = '.logs/usecase/uc558-model';
const demo = JSON.parse(readFileSync(join(ROOT, 'services/models-service/seed/demo-fake-openai/script.json'), 'utf8'));
mkdirSync(join(ROOT, RULES), { recursive: true });
writeFileSync(join(ROOT, RULES, 'script.json'), JSON.stringify({ ...demo, rules: [...OURS, ...demo.rules] }));

/** The fake Salesforce, started from its script; resolves with what it printed and stops when the walk ends. */
async function startSalesforce() {
  const child = spawn('uv', ['run', '--quiet', '--directory', join(ROOT, 'services/agents-service'), 'python', join(ROOT, 'docs/usecases/lib/fake_salesforce.py')], { stdio: ['pipe', 'pipe', 'inherit'] });
  const line = await new Promise((resolve, reject) => {
    createInterface({ input: child.stdout }).once('line', resolve);
    child.once('exit', (code) => reject(new Error(`fake Salesforce exited with ${code}`)));
  });
  return { child, info: JSON.parse(line) };
}

/** Closes the fake's stdin and waits for it to exit, with SIGTERM after 20 s; then no container it started is left. */
async function stopSalesforce() {
  const exited = new Promise((resolve) => (sf.child.exitCode !== null ? resolve() : sf.child.once('exit', resolve)));
  sf.child.stdin.end();
  const timer = setTimeout(() => sf.child.kill('SIGTERM'), 20_000);
  await exited;
  clearTimeout(timer);
  const left = execFileSync('docker', ['ps', '-q', '--filter', `label=ops.harness.owner=${sf.info.owner}`], { encoding: 'utf8' }).trim();
  check('20 the run leaves no container of its own behind', left === '', left);
}

/** A GET on the fake's own https address, checked against its CA under the sign-in host its certificate names. */
const fakeGet = (url) =>
  new Promise((resolve, reject) => {
    request(url, { ca: readFileSync(sf.info.ca), servername: LOGIN_HOST }, (res) => {
      let body = '';
      res.on('data', (d) => (body += d));
      res.on('end', () => resolve(JSON.parse(body)));
    })
      .on('error', reject)
      .end();
  });

const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
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

const sf = await startSalesforce();
const [address, port] = JSON.parse(sf.info.settings.OPS_EGRESS_RESOLVE)[LOGIN_HOST].split(':');
const edits = async () => (await fakeGet(sf.info.control)).edits.map((e) => e.by);

try {
  await withUiStack(
    async (consoleUrl) => {
      mkdirSync(SHOTS, { recursive: true });
      const priya = as(await tokenFor('p.shah@harborpine.example'), 'team_ops');
      const james = as(await tokenFor('j.richardson@harborpine.example'), 'team_ops');
      const sam = as(await tokenFor('s.adeyemi@harborpine.example'), 'team_security');
      const nadia = as(await tokenFor('n.petrov@harborpine.example'), 'team_security');

      // Set-up through the API, as uc-558's api layer does: the hosts, the app and its account, the module and an agent.
      for (const host of sf.info.hosts) await call(tools, 'POST', '/v1/egress/hosts', sam, { value: host, note: 'uc-558' });
      await call(tools, 'POST', '/v1/egress/ranges', sam, { value: sf.info.range, note: 'uc-558' });
      const made = await call(tools, 'POST', '/v1/apps', priya, { name: 'Salesforce', authKind: 'oauth2_auth_code', signIn: 'person', sandbox: false });
      const conn = required(made, 'create the Salesforce app');
      const settings = { baseUrl: sf.info.api_base, authorizeUrl: sf.info.authorize_url, tokenUrl: sf.info.token_url, revokeUrl: sf.info.revoke_url, clientId: 'ops-ai-kestrel', scopes: 'openid api refresh_token', testPath: '/services/oauth2/userinfo' };
      const put = await call(tools, 'PATCH', `/v1/apps/${conn.appId}/accounts/${conn.id}`, priya, { revision: conn.revision, settings, secretValues: { clientSecret: 'kestrel-connected-app-secret' } });
      const http = { name: 'uc558_update_case', description: "Update a Salesforce case's status", access: 'write', method: 'PATCH', url: sf.info.case_url, body: '{"Status": {{status}}}' };
      const mod = required(await call(tools, 'POST', '/v1/tool-modules', priya, { name: 'uc558-update-case', displayName: 'Salesforce cases', system: 'Salesforce', type: 'http', endpoint: '', connectionId: conn.id, signIn: 'person', http }), 'create the tool module');
      const op = (mod.operations ?? [])[0] ?? {};
      await call(tools, 'PATCH', `/v1/tool-modules/${mod.id}/operations/${op.id}`, priya, { requiresApproval: false, scopes: ['cases.write'] });
      await call(tools, 'POST', `/v1/tool-modules/${mod.id}/reviews`, priya, { note: 'uc-558' });
      const review = ((await call(tools, 'GET', `/v1/tool-modules/${mod.id}`, priya)).data?.versions ?? []).find((v) => v.status === 'in_review');
      await call(agents, 'POST', `/v1/publish-requests/${review?.reviewId}/decision`, nadia, { decision: 'approved' });
      const published = (await call(tools, 'GET', `/v1/tool-modules/${mod.id}`, priya)).data;
      const agent = required(await call(agents, 'POST', '/v1/agents', priya, { name: 'Claims desk', role: 'Moves claim cases in Salesforce' }), 'create the agent');
      // agents-service keeps the grantable tools for 30 s, so the new module's operation is offered within that.
      let patched = await call(agents, 'PATCH', `/v1/agents/${agent.id}`, priya, { toolIds: ['uc558_update_case'] });
      for (let i = 0; i < 40 && patched.status === 400; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        patched = await call(agents, 'PATCH', `/v1/agents/${agent.id}`, priya, { toolIds: ['uc558_update_case'] });
      }
      const saved = required(patched, 'give the agent its tool');
      const asked = await call(agents, 'POST', `/v1/agents/${agent.id}/publish-requests`, priya, { version: saved.version, note: 'uc-558' });
      // The team's publish policy may hold a new agent for a review; Maya, an approver in Operations, approves it.
      const maya = as(await tokenFor('m.okafor@harborpine.example'), 'team_ops');
      const live = asked.data?.status === 'pending' ? await call(agents, 'POST', `/v1/publish-requests/${asked.data.id}/decision`, maya, { decision: 'approved' }) : asked;
      const offered = ((await call(agents, 'GET', '/v1/agents?pageSize=100', james)).data?.data ?? []).some((a) => a.id === agent.id && a.publishedVersion != null);
      check(
        'setup: the connection asks each person, its module is published and the agent holds it',
        made.status === 201 && put.status === 200 && published?.status === 'published' && live.status < 300 && offered,
        { made: made.status, put: put.status, module: published?.status, patched: patched.status, asked: asked.text, live: live.text, offered },
      );

      const browser = await chromium.launch();
      const errors = [];
      try {
        const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, ignoreHTTPSErrors: true });
        // The browser reaches the fake's sign-in host on this machine's address, as tools-service does by its map.
        const toFake = async (route) => {
          const u = new URL(route.request().url());
          const response = await route.fetch({ url: `https://${address}:${port}${u.pathname}${u.search}`, headers: { ...route.request().headers(), host: LOGIN_HOST }, maxRedirects: 0 });
          await route.fulfill({ response });
        };
        await context.route(`https://${LOGIN_HOST}/**`, toFake);
        const signIn = async (email, on = context) => {
          const page = await on.newPage();
          page.on('pageerror', (e) => errors.push(`${email}: ${e.message}`));
          await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByLabel('Work email').fill(email);
          await page.getByLabel('Password').fill(PASSWORD);
          await page.getByTestId('login-submit').click();
          await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
          return page;
        };
        /** Plays the person through the pop-up: the system's sign-in page as `account`, then back to the console. */
        const throughPopup = async (popup, account) => {
          popup.on('pageerror', (e) => errors.push(`popup: ${e.message}`));
          const user = popup.locator('input[name=username]');
          await user.waitFor({ timeout: 60_000 });
          await popup.screenshot({ path: join(SHOTS, `popup-${account.split('@')[0]}.png`) });
          await user.fill(account);
          await popup.locator('input[type=submit], button[type=submit]').first().click();
          await popup.waitForEvent('close', { timeout: 60_000 });
        };

        const page = await signIn('j.richardson@harborpine.example');
        const answers = [];
        page.on('response', async (r) => {
          if (r.url().includes('/v1/me/accounts') && r.request().method() === 'GET') answers.push(`${r.status()} ${(await r.text().catch(() => '')).slice(0, 160)} team=${r.request().headers()['x-team-id']}`);
        });
        // The conversation's own address, to open it again at 375 px.
        let thread = `${consoleUrl}/chat`;
        await step('12 James asks to move a case and the chat asks him to connect Salesforce, with nothing sent to it', async () => {
          await page.goto(`${consoleUrl}/chat?agent=${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const box = page.getByLabel('Message');
          await box.waitFor({ timeout: 120_000 });
          // The first message goes to the agent the picker shows; until the agents load it would be the default one.
          await page.getByTestId('home-agent').filter({ hasText: 'Claims desk' }).waitFor({ timeout: 60_000 });
          await box.fill(`Move case ${CASE} to Awaiting documents.`);
          await page.getByRole('button', { name: 'Send' }).click();
          const card = page.getByTestId('connection-required');
          await card.waitFor({ timeout: 90_000 });
          await page.screenshot({ path: join(SHOTS, 'chat-connect-1280.png') });
          const connect = await page.getByTestId('connection-connect').textContent();
          check('12 James asks to move a case and the chat asks him to connect Salesforce, with nothing sent to it', (await card.getAttribute('data-state')) === 'open' && /Connect Salesforce/.test(connect ?? '') && (await edits()).length === 0, { connect, edits: await edits() });
        }, page);

        await step('13 he signs in through the pop-up and the chat goes on: Salesforce records exactly one edit, his', async () => {
          const [popup] = await Promise.all([page.waitForEvent('popup'), page.getByTestId('connection-connect').click()]);
          await throughPopup(popup, 'handler@kestrel.example');
          await page.getByTestId('connection-required').and(page.locator('[data-state=connected]')).first().waitFor({ timeout: 60_000 });
          await page.getByText('The case is now Awaiting documents').waitFor({ timeout: 90_000 });
          await page.screenshot({ path: join(SHOTS, 'chat-connected-1280.png') });
          thread = page.url();
          check('13 he signs in through the pop-up and the chat goes on: Salesforce records exactly one edit, his', JSON.stringify(await edits()) === JSON.stringify(['handler@kestrel.example']), await edits());
        }, page);

        await step('14 Your connections, from the person menu, lists his Salesforce account', async () => {
          await page.getByTestId('nav-user').click();
          await page.getByTestId('nav-connections').click();
          await page.waitForURL(/\/settings\/account\/connectors$/, { timeout: 60_000 });
          const row = page.getByTestId('my-connections');
          await row.waitFor({ timeout: 60_000 });
          const text = (await row.textContent()) ?? '';
          await page.screenshot({ path: join(SHOTS, 'your-connections-1280.png') });
          check('14 Your connections, from the person menu, lists his Salesforce account', /Salesforce/.test(text) && /handler@kestrel\.example/.test(text), text.slice(0, 200));
        }, page);

        await step('15 at 375 px the card and Your connections fit the screen', async () => {
          await page.setViewportSize({ width: 375, height: 760 });
          await page.reload({ waitUntil: 'domcontentloaded' });
          await page.getByTestId('my-connections').waitFor({ timeout: 60_000 }).catch((e) => {
            throw new Error(`${String(e).split('\n')[0]} answers: ${answers.join(' | ')}`);
          });
          const mine = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
          await page.screenshot({ path: join(SHOTS, 'your-connections-375.png') });
          await page.goto(thread, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId('connection-required').first().waitFor({ timeout: 60_000 });
          const chat = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
          await page.screenshot({ path: join(SHOTS, 'chat-connected-375.png') });
          check('15 at 375 px the card and Your connections fit the screen', mine && chat, { mine, chat });
          await page.setViewportSize({ width: 1280, height: 900 });
        }, page);

        await step('16 Disconnect removes his sign-in, and the system is asked to end it', async () => {
          // The old address opens My accounts; the row stays, offering Connect, as the app still lets him connect his own.
          await page.goto(`${consoleUrl}/settings/account/connections`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByTestId(`disconnect-${conn.id}`).click();
          await page.getByTestId('delete-my-connection-confirm-btn').click();
          await page.getByTestId(`connect-${conn.id}`).waitFor({ timeout: 60_000 });
          const left = (await call(tools, 'GET', '/v1/me/accounts', james)).data ?? null;
          check('16 Disconnect removes his sign-in, and the system is asked to end it', Array.isArray(left) && left.length === 0, left);
        }, page);

        // Her own browser: a person's sign-in lives in the browser's storage, so a second person needs a second one.
        const adminContext = await browser.newContext({ viewport: { width: 1280, height: 900 }, ignoreHTTPSErrors: true });
        await adminContext.route(`https://${LOGIN_HOST}/**`, toFake);
        const admin = await signIn('p.shah@harborpine.example', adminContext);
        await step('17 Priya reads Everyone signs in on the app’s Settings, turns it off to the team account and back on', async () => {
          // Who signs in sits on the app page's Settings in the final Apps frames; the old address opens the page.
          await admin.goto(`${consoleUrl}/tools/connections/${conn.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await admin.waitForURL((u) => u.pathname.startsWith('/data/connectors/'), { timeout: 60_000 });
          await admin.getByTestId('app-tab-settings').click();
          const everyone = admin.getByTestId('app-everyone');
          await everyone.waitFor({ timeout: 90_000 });
          const first = await everyone.getAttribute('data-state');
          const read = async () => required(await call(tools, 'GET', `/v1/apps/${conn.appId}/accounts/${conn.id}`, priya), 'read the account');
          const until = async (want) => {
            let now = await read();
            for (let i = 0; i < 20 && now.signIn !== want; i++) await admin.waitForTimeout(500), (now = await read());
            return now;
          };
          await everyone.click();
          const off = await until('team');
          await admin.getByTestId('app-everyone').click();
          const on = await until('person');
          check('17 Priya reads Everyone signs in on the app’s Settings, turns it off to the team account and back on', first === 'checked' && off.signIn === 'team' && on.signIn === 'person', { first, off: off.signIn, on: on.signIn });
        }, admin);

        await step('18 she connects her own account on the app’s page, which the old connection address opens', async () => {
          await admin.goto(`${consoleUrl}/tools/connections/${conn.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await admin.waitForURL((u) => u.pathname.startsWith('/data/connectors/'), { timeout: 60_000 });
          const button = admin.getByTestId('app-connect-me');
          await button.waitFor({ timeout: 90_000 }).catch(async (e) => {
            // What the page shows instead, so a red run says why.
            console.log('app page:', admin.url(), ((await admin.locator('main').innerText().catch(() => '')) ?? '').replace(/\s+/g, ' ').slice(0, 600));
            throw e;
          });
          const [popup] = await Promise.all([admin.waitForEvent('popup', { timeout: 60_000 }), button.click()]);
          await throughPopup(popup, 'lead@kestrel.example');
          const me = admin.getByTestId('app-connected-as');
          await me.getByText(/Connected\b.* as /).waitFor({ timeout: 60_000 }).catch(() => {});
          const text = ((await me.innerText()) ?? '').replace(/\s+/g, ' ');
          await admin.screenshot({ path: join(SHOTS, 'app-own-account-1280.png') });
          const mine = (await call(tools, 'GET', '/v1/me/accounts', priya)).data ?? [];
          check('18 she connects her own account on the app’s page, which the old connection address opens', /Connected\b.* as lead@kestrel\.example/.test(text) && mine.some((c) => c.account === 'lead@kestrel.example'), { text, mine });
        }, admin);

        check('no page errors', errors.length === 0, errors.slice(0, 3));
      } finally {
        await browser.close();
      }
    },
    { demo: true, fakeModelRules: RULES, tools: { env: sf.info.settings } },
  );
} finally {
  await stopSalesforce();
}

finish();
