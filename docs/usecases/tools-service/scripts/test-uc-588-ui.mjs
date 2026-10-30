// uc-588 A developer's plugin signs in every way a system asks, ui layer: docs/usecases/tools-service/plugin-sign-in-methods.md,
// stories S3 (steps 16-17) and S5 (step 18). The demo stack with plugins on (OPS_PLUGINS), the test plugins of
// services/tools-service/tests/plugin_kinds (OPS_PLUGIN_PATHS), the console switch NEXT_PUBLIC_OPS_PERSONAL_SIGNIN on and the
// fake system (docs/usecases/lib/fake_multi_auth.py). Set-up goes through the API as the api layer proved it: the
// install switch, the hosts, the person plugin turned on for each person's own sign-in and the header-key plugin with its
// key, and an agent holding the person plugin's read tool. James asks the agent for a record in chat; the call is
// refused with a Connect card, he signs in through the pop-up with his own account, and the chat goes on with the
// record the system answered to his account. The Connections page then lists both plugin connections with no key on
// it. Screenshots go to evidenceDir('588', 'uc').
import { execFileSync, spawn } from 'node:child_process';
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { request } from 'node:https';
import { createInterface } from 'node:readline';
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const PASSWORD = 'northfield-demo';
const SHOTS = evidenceDir('588', 'uc');
const LOGIN_HOST = 'login.multi.test';
const KINDS = join(ROOT, 'services/tools-service/tests/plugin_kinds');
const FOLDERS = readdirSync(KINDS).filter((n) => n.startsWith('kinds_')).map((n) => join(KINDS, n));
// Plugins are off until their release; this walk turns them on for its own services.
process.env.OPS_PLUGINS = 'true';
process.env.OPS_PLUGIN_PATHS = JSON.stringify(FOLDERS);

// The fake model's answers: the request asks for the person plugin's read tool, the follow-up after connecting asks for
// it again, and the answer names the account the system read the record with. The demo's own rules follow.
const OURS = [
  { when: '\\bRead record (?P<id>rec-\\d+)', tool: 'person_get_record', arguments: { id: '{id}' } },
  { when: '\\bI connected (?P<system>[^.\\n]+)\\. Please go ahead', tool: 'person_get_record', arguments: { id: 'rec-1042' } },
  { after: 'person_get_record', result: 'CONNECTION_NOT_LINKED', text: 'I could not read it: Person desk needs your own account. Connect it from the card above and I will go ahead.' },
  { after: 'person_get_record', result: '"as": ?"(?P<who>[^"]+)"', text: 'Harbor ticket 1042 is open; Person desk answered to {who}.' },
];
const RULES = '.logs/usecase/uc588-model';
const demo = JSON.parse(readFileSync(join(ROOT, 'services/models-service/seed/demo-fake-openai/script.json'), 'utf8'));
mkdirSync(join(ROOT, RULES), { recursive: true });
writeFileSync(join(ROOT, RULES, 'script.json'), JSON.stringify({ ...demo, rules: [...OURS, ...demo.rules] }));

/** The fake system, started from its script; resolves with what it printed and stops when the walk ends. */
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
  check('19 the run leaves no container of its own behind', left === '', left);
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

try {
  await withUiStack(
    async (consoleUrl) => {
      mkdirSync(SHOTS, { recursive: true });
      const sam = as(await tokenFor('s.adeyemi@harborpine.example'), 'team_security');
      const priya = as(await tokenFor('p.shah@harborpine.example'), 'team_ops');
      const james = as(await tokenFor('j.richardson@harborpine.example'), 'team_ops');
      const maya = as(await tokenFor('m.okafor@harborpine.example'), 'team_ops');

      // Set-up through the API, as the api layer's steps 1-8 do.
      const installed = await call(platform, 'PUT', '/v1/policies/plugins', sam, { value: { 'test.person': { enabled: true }, 'test.header-key': { enabled: true } } });
      for (const host of fake.info.hosts) await call(tools, 'POST', '/v1/egress/hosts', sam, { value: host, note: 'uc-588' });
      await call(tools, 'POST', '/v1/egress/ranges', sam, { value: fake.info.range, note: 'uc-588' });
      let listed = await call(tools, 'GET', '/v1/plugins', priya);
      for (let i = 0; i < 40 && !(listed.data?.plugins ?? []).filter((p) => p.installOn).length; i++) await new Promise((r) => setTimeout(r, 500)), (listed = await call(tools, 'GET', '/v1/plugins', priya));
      const person = await call(tools, 'PUT', '/v1/plugins/test.person/team', priya, { enabled: true, signIn: 'person', clientId: 'multi-app', clientSecret: fake.info.clients['multi-app'] });
      const keyed = await call(tools, 'PUT', '/v1/plugins/test.header-key/team', priya, { enabled: true, credentials: { key: fake.info.secrets.key } });
      await call(tools, 'POST', `/v1/connections/${keyed.data?.connectionId}/test`, priya, { environment: 'production' });
      const agent = (await call(agents, 'POST', '/v1/agents', priya, { name: 'Ticket desk', role: 'Reads tickets from Person desk' })).data ?? {};
      // agents-service keeps the grantable tools for 30 s, so the plugin's operation is offered within that.
      let patched = await call(agents, 'PATCH', `/v1/agents/${agent.id}`, priya, { toolIds: ['person_get_record'] });
      for (let i = 0; i < 40 && patched.status === 400; i++) await new Promise((r) => setTimeout(r, 1000)), (patched = await call(agents, 'PATCH', `/v1/agents/${agent.id}`, priya, { toolIds: ['person_get_record'] }));
      const asked = await call(agents, 'POST', `/v1/agents/${agent.id}/publish-requests`, priya, { version: patched.data?.version, note: 'uc-588' });
      const live = asked.data?.status === 'pending' ? await call(agents, 'POST', `/v1/publish-requests/${asked.data.id}/decision`, maya, { decision: 'approved' }) : asked;
      check(
        'setup: the person plugin asks each person to sign in, the header-key plugin holds its key, and the agent holds the read tool',
        installed.status === 200 && person.status === 200 && keyed.status === 200 && patched.status === 200 && live.status < 300,
        { installed: installed.text, person: person.text, keyed: keyed.status, patched: patched.text, live: live.text },
      );

      const browser = await chromium.launch();
      const errors = [];
      try {
        const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, ignoreHTTPSErrors: true });
        // The browser reaches the fake's sign-in host on this machine's address, as tools-service does by its map.
        await context.route(`https://${LOGIN_HOST}/**`, async (route) => {
          const u = new URL(route.request().url());
          const response = await route.fetch({ url: `https://${address}:${port}${u.pathname}${u.search}`, headers: { ...route.request().headers(), host: LOGIN_HOST }, maxRedirects: 0 });
          await route.fulfill({ response });
        });
        const page = await context.newPage();
        page.on('pageerror', (e) => errors.push(e.message));
        await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByLabel('Work email').fill('j.richardson@harborpine.example');
        await page.getByLabel('Password').fill(PASSWORD);
        await page.getByTestId('login-submit').click();
        await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

        await step('16 James asks the agent for a record and the chat asks him to connect his own account, with nothing read', async () => {
          await page.goto(`${consoleUrl}/chat?agent=${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const box = page.getByLabel('Message');
          await box.waitFor({ timeout: 120_000 });
          await page.getByTestId('home-agent').filter({ hasText: 'Ticket desk' }).waitFor({ timeout: 60_000 });
          await box.fill('Read record rec-1042.');
          await page.getByRole('button', { name: 'Send' }).click();
          const card = page.getByTestId('connection-required');
          await card.waitFor({ timeout: 90_000 });
          await page.screenshot({ path: join(SHOTS, 'chat-connect-1280.png') });
          const reads = (await fakeState()).calls.filter((c) => c.method === 'person' && c.accepted);
          check('16 James asks the agent for a record and the chat asks him to connect his own account, with nothing read', (await card.getAttribute('data-state')) === 'open' && reads.length === 0, { reads });
        }, page);

        await step('17 he signs in through the pop-up with his own account and the chat answers with the record read as him', async () => {
          const [popup] = await Promise.all([page.waitForEvent('popup'), page.getByTestId('connection-connect').click()]);
          popup.on('pageerror', (e) => errors.push(`popup: ${e.message}`));
          const user = popup.locator('input[name=username]');
          await user.waitFor({ timeout: 60_000 });
          await user.fill('james.person');
          await popup.locator('input[type=submit], button[type=submit]').first().click();
          await popup.waitForEvent('close', { timeout: 60_000 });
          await page.getByText('Person desk answered to james.person').waitFor({ timeout: 90_000 });
          await page.screenshot({ path: join(SHOTS, 'chat-answered-1280.png') });
          const reads = (await fakeState()).calls.filter((c) => c.method === 'person' && c.accepted).map((c) => c.as);
          check('17 he signs in through the pop-up with his own account and the chat answers with the record read as him', reads.length >= 1 && reads.every((w) => w === 'james.person'), reads);
        }, page);

        await step('18 each plugin connection opens on its page, the header-key one tested and working, and no key or client secret', async () => {
          const admin = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
          admin.on('pageerror', (e) => errors.push(`admin: ${e.message}`));
          await admin.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await admin.getByLabel('Work email').fill('p.shah@harborpine.example');
          await admin.getByLabel('Password').fill(PASSWORD);
          await admin.getByTestId('login-submit').click();
          await admin.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
          let html = '';
          const shown = {};
          for (const [id, name] of [[keyed.data?.connectionId, 'Header key desk'], [person.data?.connectionId, 'Person desk']]) {
            await admin.goto(`${consoleUrl}/tools/connections/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
            await admin.getByText(name).first().waitFor({ timeout: 90_000 });
            // The health line loads after the page's title; the header-key connection was tested in set-up.
            if (name === 'Header key desk') await admin.getByText('Working').first().waitFor({ timeout: 60_000 });
            await admin.screenshot({ path: join(SHOTS, `connection-${name.split(' ')[0].toLowerCase()}-1280.png`) });
            html += await admin.content();
            shown[name] = (await admin.locator('main').textContent()) ?? '';
          }
          const keyPage = /API key, production/i.test(shown['Header key desk']) && /Working\s*200/.test(shown['Header key desk']);
          const personPage = /Sign in with an account/.test(shown['Person desk']);
          check('18 each plugin connection opens on its page, the header-key one tested and working, and no key or client secret', keyPage && personPage && !html.includes(fake.info.secrets.key) && !html.includes(fake.info.clients['multi-app']), { keyPage, personPage, key: html.includes(fake.info.secrets.key), shown: shown['Header key desk'].replace(/\s+/g, ' ').slice(0, 400) });
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
      consoleSwitches: { NEXT_PUBLIC_OPS_PERSONAL_SIGNIN: '1' },
    },
  );
} finally {
  await stopFake();
}
finish();
