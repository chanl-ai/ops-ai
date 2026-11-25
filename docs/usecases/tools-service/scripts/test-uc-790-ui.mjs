// uc-790 A chat user never chooses between their own login and the team's, ui layer:
// docs/usecases/tools-service/chat-never-asks-whose-login.md, steps 5-7. The test plugins of
// services/tools-service/tests/plugin_kinds and the fake system (docs/usecases/lib/fake_multi_auth.py) stand in for the
// apps: the header key desk signs in with the team's key, the person key desk asks each person for their own key.
// Screenshots at 1440 and 390 go to evidenceDir('790', 'uc').
import { execFileSync, spawn } from 'node:child_process';
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { createInterface } from 'node:readline';
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, evidenceDir, finish, withUiStack, required } from '@ops-ai/usecase-runner/harness';

import { agentBase } from '../../lib/agent_save.mjs';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const PASSWORD = 'northfield-demo';
const SHOTS = evidenceDir('790', 'uc');
const KINDS = join(ROOT, 'services/tools-service/tests/plugin_kinds');
const FOLDERS = readdirSync(KINDS).filter((n) => n.startsWith('kinds_')).map((n) => join(KINDS, n));
const TEAM_APP = 'plugin:test.header-key';
const OWN_APP = 'plugin:test.person-key';
// Person desk offers both answers (team, person), so its Settings shows the whole question.
const BOTH_APP = 'plugin:test.person';

// The fake model: a team record is read on the header key desk, the person's own on the person key desk, and the ask
// goes on once the person signs in from the card.
const OURS = [
  { when: '\\bRead the team record (?P<id>rec-\\d+)', tool: 'header_key_get_record', arguments: { id: '{id}' } },
  { when: '\\bRead my record (?P<id>rec-\\d+)', tool: 'person_key_get_record', arguments: { id: '{id}' } },
  { when: '\\bI connected (?P<system>[^.\\n]+)\\. Please go ahead', tool: 'person_key_get_record', arguments: { id: 'rec-1042' } },
  { after: 'header_key_get_record', text: 'The team record is read.' },
  // The model is told the refusal as a plain line (activities/gateway.py CARD_LINES), never its code.
  { after: 'person_key_get_record', result: 'once they sign in', text: 'I carry on once you sign in from the card above.' },
  { after: 'person_key_get_record', text: 'Your record is read.' },
];
const RULES = evidenceDir('790', 'model');
const demo = JSON.parse(readFileSync(join(ROOT, 'services/models-service/seed/demo-fake-openai/script.json'), 'utf8'));
mkdirSync(RULES, { recursive: true });
writeFileSync(join(RULES, 'script.json'), JSON.stringify({ ...demo, rules: [...OURS, ...demo.rules] }));

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

async function stopFake(fake) {
  const exited = new Promise((resolve) => (fake.child.exitCode !== null ? resolve() : fake.child.once('exit', resolve)));
  fake.child.stdin.end();
  const timer = setTimeout(() => fake.child.kill('SIGTERM'), 20_000);
  await exited;
  clearTimeout(timer);
  const left = execFileSync('docker', ['ps', '-q', '--filter', `label=ops.harness.owner=${fake.info.owner}`], { encoding: 'utf8' }).trim();
  check('the run leaves no container of its own behind', left === '', left);
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

async function step(name, body, page) {
  try {
    await body();
  } catch (e) {
    await page?.screenshot({ path: join(SHOTS, `failed-${name.split(' ')[0]}.png`) }).catch(() => {});
    check(name, false, `${String(e).slice(0, 1500)} at ${page?.url() ?? 'no page'}`);
  }
}

/** The screen at 1440 and 390 as `<name>-<width>.png`; reports anything wider than the window at either width. */
async function shoot(page, name, focus = null) {
  const cut = [];
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    await page.waitForTimeout(400);
    if (focus) await focus.scrollIntoViewIfNeeded();
    await page.screenshot({ path: join(SHOTS, `${name}-${width}.png`), fullPage: !focus });
    // The page and the main area, whose own scroll area holds a chat: neither may be wider than the window.
    const wide = await page.evaluate(() => {
      const main = document.querySelector('main');
      return document.documentElement.scrollWidth > window.innerWidth + 1 || (!!main && main.scrollWidth > main.clientWidth + 1);
    });
    if (wide) cut.push(width);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  return cut;
}

async function signedIn(browser, consoleUrl, email, errors) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, ignoreHTTPSErrors: true });
  const page = await context.newPage();
  page.on('pageerror', (e) => errors.push(`${email}: ${e.message}`));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Work email').fill(email);
  await page.getByLabel('Password').fill(PASSWORD);
  await page.getByTestId('login-submit').click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

// Words that would offer a chat user the team's login in place of their own.
const CHOICE = /Run with the team login|Run as the team|team account|Use the team(’|')s login instead/i;

const fake = await startFake();
try {
  await withUiStack(
    async (consoleUrl) => {
      mkdirSync(SHOTS, { recursive: true });
      const sam = as(await tokenFor('s.adeyemi@harborpine.example'), 'team_security');
      const priya = as(await tokenFor('p.shah@harborpine.example'), 'team_ops');
      const maya = as(await tokenFor('m.okafor@harborpine.example'), 'team_ops');
      for (const host of fake.info.hosts) await call(tools, 'POST', '/v1/egress/hosts', sam, { value: host, note: 'uc-790' });
      await call(tools, 'POST', '/v1/egress/ranges', sam, { value: fake.info.range, note: 'uc-790' });
      const team = await call(tools, 'PUT', `/v1/apps/${TEAM_APP}/team`, priya, { enabled: true, credentials: { key: fake.info.secrets.key } });
      const own = await call(tools, 'PUT', `/v1/apps/${OWN_APP}/team`, priya, { enabled: true, signIn: 'person' });
      // Person desk is turned on with the team's login, so its Settings reads Everyone uses the team's login.
      const both = await call(tools, 'PUT', `/v1/apps/${BOTH_APP}/team`, priya, { enabled: true, signIn: 'team' });
      const agent = required(await call(agents, 'POST', '/v1/agents', priya, { name: 'Record desk', role: 'Reads records from the desks' }), 'create the agent');
      const toolIds = ['header_key_get_record', 'person_key_get_record'];
      const patched = await call(agents, 'PATCH', `/v1/agents/${agent.id}`, priya, { toolIds, ...(await agentBase(agents, priya, agent.id)) });
      const asked = await call(agents, 'POST', `/v1/agents/${agent.id}/publish-requests`, priya, { version: patched.data?.version, note: 'uc-790' });
      const live = asked.data?.status === 'pending' ? await call(agents, 'POST', `/v1/publish-requests/${asked.data.id}/decision`, maya, { decision: 'approved' }) : asked;
      check('0 set-up: the team-login desk and the each-person desk are on, and Record desk holds a tool of each', team.status === 200 && own.status === 200 && both.status === 200 && patched.status === 200 && live.status < 300, { team: team.text, own: own.text, both: both.text, patched: patched.text, live: live.status });

      const browser = await chromium.launch();
      const errors = [];
      try {
        // The chat user is Lena Brandt (chat_user in team_ops, services/platform-service/seed/people.json); she gives the
        // fake desk's second person key as her own.
        const lenaToken = await tokenFor('l.brandt@harborpine.example').catch(() => null);
        check('0b set-up: Lena Brandt, a chat user, signs in', Boolean(lenaToken), lenaToken);
        const james = await signedIn(browser, consoleUrl, 'l.brandt@harborpine.example', errors);
        const open = async () => {
          await james.goto(`${consoleUrl}/chat?agent=${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await james.getByLabel('Message').waitFor({ timeout: 120_000 });
          await james.getByTestId('home-agent').filter({ hasText: 'Record desk' }).waitFor({ timeout: 60_000 });
        };
        const send = async (text) => {
          await james.getByLabel('Message').fill(text);
          await james.locator('button[type=submit][aria-label="Send"]').click();
        };

        await step('5 on the team-login desk the reply says which login acted and that Lena asked, with no sign-in card', async () => {
          await open();
          await send('Read the team record rec-1042.');
          await james.getByText('The team record is read.').waitFor({ timeout: 90_000 });
          const line = ((await james.getByTestId('team-login-line').first().innerText({ timeout: 30_000 })) ?? '').replace(/\s+/g, ' ');
          const cards = await james.getByTestId('connection-required').count();
          const body = (await james.locator('main').innerText()).replace(/\s+/g, ' ');
          const cut = await shoot(james, 'chat-team-login');
          check(
            '5 on the team-login desk the reply says which login acted and that Lena asked, with no sign-in card',
            /^Runs in .+ as .+ \(team login\)\. You are recorded as the person who asked\.$/.test(line) && cards === 0 && !CHOICE.test(body) && cut.length === 0,
            { line, cards, cut },
          );
        }, james);

        await step('6 on the each-person desk one Sign in card shows, the chat carries on after her key, the next ask shows none, and nothing offers the team login', async () => {
          await open();
          await send('Read my record rec-1042.');
          const card = james.getByTestId('connection-required');
          await card.waitFor({ timeout: 90_000 });
          await james.getByText('I carry on once you sign in from the card above.').waitFor({ timeout: 90_000 });
          const said = ((await card.innerText()) ?? '').replace(/\s+/g, ' ');
          const cut = await shoot(james, 'chat-sign-in-card');
          await james.getByTestId('own-field-key').fill(fake.info.person_keys.maya);
          await james.getByTestId('own-credentials-save').click();
          const first = await james.getByText('I carry on once you sign in from the card above.').count();
          await james.getByText('Your record is read.').first().waitFor({ timeout: 90_000 });
          const cardsAfterFirst = await card.count();
          await send('Read my record rec-1043.');
          await james.getByText('Your record is read.').nth(1).waitFor({ timeout: 90_000 });
          const cardsAfterSecond = await james.getByTestId('connection-required').count();
          const body = (await james.locator('main').innerText()).replace(/\s+/g, ' ');
          const cutAfter = await shoot(james, 'chat-signed-in-goes-on');
          check(
            '6 on the each-person desk one Sign in card shows, the chat carries on after her key, the next ask shows none, and nothing offers the team login',
            first === 1 && /Sign in to Person key desk to continue/.test(said) && !CHOICE.test(said) && cardsAfterFirst === 1 && cardsAfterSecond === 1 && !CHOICE.test(body) && cut.length === 0 && cutAfter.length === 0,
            { said: said.slice(0, 300), first, cardsAfterFirst, cardsAfterSecond, cut, cutAfter },
          );
        }, james);

        const admin = await signedIn(browser, consoleUrl, 'p.shah@harborpine.example', errors);
        await step('7 the app page asks Who signs in with two answers, and the agent’s tools row names each app’s answer', async () => {
          await admin.goto(`${consoleUrl}/data/connectors/${encodeURIComponent(BOTH_APP)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await admin.getByTestId('app-tab-settings').click({ timeout: 90_000 });
          const choice = admin.getByTestId('app-everyone');
          const shown = await choice.waitFor({ timeout: 30_000 }).then(async () => ((await choice.innerText()) ?? '').replace(/\s+/g, ' '), () => '');
          const picked = await choice.locator('#who-shared').getAttribute('aria-checked').catch(() => null);
          const cutApp = await shoot(admin, 'app-who-signs-in');
          await admin.goto(`${consoleUrl}/build/agents/${agent.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const tools_ = admin.locator('#agent-tools');
          await tools_.waitFor({ timeout: 90_000 });
          await tools_.getByText('Everyone uses the team’s login', { exact: false }).or(tools_.getByText("Everyone uses the team's login")).first().waitFor({ timeout: 60_000 });
          const rows = ((await tools_.innerText()) ?? '').replace(/\s+/g, ' ');
          await tools_.scrollIntoViewIfNeeded();
          const cutAgent = await shoot(admin, 'agent-tools-row', tools_);
          check(
            '7 the app page asks Who signs in with two answers, and the agent’s tools row names each app’s answer',
            /Everyone uses the team’s login/.test(shown) && /Each person signs in/.test(shown) && picked === 'true' && /Everyone uses the team's login/.test(rows) && /Each person signs in/.test(rows) && cutApp.length === 0 && cutAgent.length === 0,
            { shown, picked, rows: rows.slice(0, 400), cutApp, cutAgent },
          );
        }, admin);

        await step('8 a schedule on a workflow that calls the each-person desk is warned at save, in the API answer and in the editor', async () => {
          const node = (id, type, parameters = {}) => ({ id, type, typeVersion: 1, name: id, parameters });
          const definition = {
            schemaVersion: 2,
            id: 'uc790_nightly',
            name: 'Nightly record read',
            nodes: [
              node('start', 'ops.trigger.schedule', { key: 'nightly' }),
              node('read', 'ops.action.tool', { operation: 'person_key_get_record', input: { id: 'rec-1042' } }),
              node('done', 'ops.flow.end', { outcome: 'read' }),
              node('failed', 'ops.flow.end', { outcome: 'failed' }),
            ],
            connections: [
              { from: { node: 'start', port: 'payload' }, to: { node: 'read', port: 'in' } },
              { from: { node: 'read', port: 'ok' }, to: { node: 'done', port: 'in' } },
              { from: { node: 'read', port: 'error' }, to: { node: 'failed', port: 'in' } },
              { from: { node: 'read', port: 'refused' }, to: { node: 'failed', port: 'in' } },
            ],
          };
          const saved = await call(agents, 'POST', '/v1/workflows/definitions', priya, { definition });
          const told = (saved.data?.warnings ?? []).find((w) => w.node === 'read' && /each person/.test(w.message ?? ''));
          await admin.goto(`${consoleUrl}/build/workflows/definitions/uc790_nightly`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const chip = admin.getByTestId('definition-problems');
          await chip.waitFor({ timeout: 90_000 });
          await admin.waitForFunction(() => /warning/.test(document.querySelector('[data-testid="definition-problems"]')?.textContent ?? ''), null, { timeout: 60_000 }).catch(() => {});
          await chip.click();
          const listed = admin.getByTestId('definition-check').filter({ hasText: 'signs in as each person' });
          const shown = await listed.first().waitFor({ timeout: 30_000 }).then(async () => ((await listed.first().innerText()) ?? '').replace(/\s+/g, ' '), () => '');
          const cut = await shoot(admin, 'workflow-schedule-warning');
          check(
            '8 a schedule on a workflow that calls the each-person desk is warned at save, in the API answer and in the editor',
            [200, 201].includes(saved.status) && /Person key desk signs in as each person, and a schedule starts this workflow/.test(told?.message ?? '') &&
              /Set Person key desk to Everyone uses the team's login, or have a person start the run/.test(shown) && cut.length === 0,
            { status: saved.status, told: told?.message, shown: shown.slice(0, 300), cut },
          );
        }, admin);

        check('no page errors', errors.length === 0, errors.slice(0, 3));
      } finally {
        await browser.close();
      }
    },
    { demo: true, fakeModelRules: RULES, tools: { env: { ...fake.info.settings, OPS_PLUGINS: 'true', OPS_PLUGIN_PATHS: JSON.stringify(FOLDERS), OPS_PLUGIN_CLIENTS: JSON.stringify({ 'test.person': { id: 'multi-app', secret: fake.info.clients['multi-app'] } }) } } },
  );
} finally {
  await stopFake(fake);
}
finish();
