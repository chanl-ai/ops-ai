// uc-564 A team turns on the Salesforce plugin, ui layer: docs/usecases/tools-service/a-team-turns-on-the-salesforce.md,
// stories S2 (steps 13-15) and S3 (steps 16-19, 30). The demo stack with the fake Salesforce (docs/usecases/lib/fake_salesforce.py)
// and plugins on (OPS_PLUGINS), loading the Salesforce plugin from the ops-ai-plugins repository beside ops-ai. Set-up goes
// through the API as the api layer proved it: the install switch, the team switch and the team's sign-in. James asks the
// case helper about a case in chat and to escalate it; the approval card names the field the change writes and its new
// value, the write waits in Human Tasks until Maya approves it there, and only then does Salesforce record it.
// Priya syncs a knowledge source read through the plugin's two tools from the source's page: every article first, nothing
// on the second sync, only the changed one on the third. James then asks about a card PIN and the answer cites the
// changed article. Screenshots go to evidenceDir('564', 'uc').
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { request } from 'node:https';
import { createInterface } from 'node:readline';
import { join } from 'node:path';

import { AGENTS_PORT, KB_PORT, PLATFORM_PORT, ROOT, TOOLS_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const kb = `http://127.0.0.1:${KB_PORT}`;
const platform = `http://127.0.0.1:${PLATFORM_PORT}`;
const PASSWORD = 'northfield-demo';
const SHOTS = evidenceDir('564', 'uc');
const PLUGIN = 'opsai.salesforce';
const CASE_ID = '5003000000D8cuJAAR';
const LOGIN_HOST = 'login.salesforce.test';
const SALESFORCE = join(ROOT, '..', 'ops-ai-plugins/plugins/salesforce/src/ops_plugin_salesforce');
// Plugins are off until their release; this walk turns them on for its own services, and kb-service reads a plugin's
// knowledge source through this run's tools-service.
process.env.OPS_PLUGINS = 'true';
process.env.OPS_TOOLS_URL = `http://127.0.0.1:${TOOLS_PORT}`;
const NEW_BODY = '<p>A cardholder resets their PIN in the app under Card, then Reset PIN, and confirms with a code sent by text.</p>';

// The fake model's answers for this walk. The escalation reads the case first and changes the record the read returned,
// so the id it writes is Salesforce's, not a constant; its answer comes only from a result that is not the approval
// wait. The PIN answer quotes the passage the knowledge block carries and cites its number, so it fires only on the
// synced article. The demo's own rules follow.
const QUERY = "SELECT Id, CaseNumber, Status, Subject FROM Case WHERE CaseNumber = '{num}'";
const DONE = '\\A(?![\\s\\S]*(?i:pending|approval|waiting|review))';
const OURS = [
  { when: '\\bEscalate case (?P<num>\\d{8})', tool: 'salesforce_query', arguments: { q: QUERY } },
  { when: '\\bEscalate case (?P<num>\\d{8})', after: 'salesforce_query', result: '"Id": ?"(?P<id>500\\w+)"', tool: 'salesforce_update_record', arguments: { object: 'Case', id: '{id}', fields: { Status: 'Escalated' } } },
  { when: '\\bEscalate case (?P<num>\\d{8})', after: 'salesforce_update_record', result: DONE, text: 'Case {num} is now Escalated in Salesforce.' },
  { when: '\\bFind case (?P<num>\\d{8})', tool: 'salesforce_query', arguments: { q: QUERY } },
  { when: '\\bFind case (?P<num>\\d{8})', after: 'salesforce_query', result: '(?=[\\s\\S]*"Status": ?"(?P<status>[^"]+)")(?=[\\s\\S]*"Subject": ?"(?P<subject>[^"]+)")', text: 'Case {num} is {status}: {subject}.' },
  { when: '(?=[\\s\\S]*\\[(?P<n>\\d+)\\] Reset a card PIN[^\\n]*: (?P<quote>[^\\n]+))[\\s\\S]*resetting a card PIN', text: '{quote} [{n}]' },
];
const RULES = '.logs/usecase/uc564-model';
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
      const james = as(await tokenFor('j.richardson@harborpine.example'), 'team_ops');
      const maya = as(await tokenFor('m.okafor@harborpine.example'), 'team_ops');

      // Set-up through the API, as the api layer's steps 1-6 do: install switch, hosts, team switch, the team's sign-in.
      const installed = await call(platform, 'PUT', '/v1/policies/plugins', sam, { value: { [PLUGIN]: { enabled: true } } });
      for (const host of sf.info.hosts) await call(tools, 'POST', '/v1/egress/hosts', sam, { value: host, note: 'uc-564' });
      await call(tools, 'POST', '/v1/egress/ranges', sam, { value: sf.info.range, note: 'uc-564' });
      const login = sf.info.authorize_url.replace(/\/authorize$/, '');
      const on = await call(tools, 'PUT', `/v1/plugins/${PLUGIN}/team`, priya, { enabled: true, settings: { login_url: login }, clientId: 'ops-ai-acme', clientSecret: 'acme-connected-app-secret' });
      const connectionId = on.data?.connectionId;
      const started = await call(tools, 'POST', `/v1/connections/${connectionId}/sign-in`, priya, { environment: 'production' });
      const back = started.data?.authorizeUrl ? await signInAt(started.data.authorizeUrl, 'acme.integration') : {};
      const signed = await call(tools, 'POST', `/v1/connections/${connectionId}/sign-in/complete`, priya, { state: back.state ?? '', code: back.code ?? '' });

      // The knowledge base the source fills, and the case helper holding the plugin's case tools and that base.
      const made = await call(kb, 'POST', '/v1/knowledge-bases', priya, { name: 'Salesforce articles', owner: 'p.shah@harborpine.example' });
      const base = made.data ?? {};
      const agent = (await call(agents, 'POST', '/v1/agents', priya, { name: 'Case helper', role: 'Works Salesforce cases and answers from the Salesforce articles' })).data ?? {};
      const grant = { toolIds: ['salesforce_query', 'salesforce_update_record'], collections: [base.id] };
      // agents-service keeps the grantable tools for 30 s, so the plugin's operations are offered within that.
      const patched = await until(() => call(agents, 'PATCH', `/v1/agents/${agent.id}`, priya, grant), (r) => r.status !== 400);
      const asked = await call(agents, 'POST', `/v1/agents/${agent.id}/publish-requests`, priya, { version: patched.data?.version, note: 'uc-564' });
      const live = asked.data?.status === 'pending' ? await call(agents, 'POST', `/v1/publish-requests/${asked.data.id}/decision`, maya, { decision: 'approved' }) : asked;
      check(
        'setup: Salesforce is on for the install and the team, the team signed in, and the case helper holds its tools',
        installed.status === 200 && on.status === 200 && signed.status === 200 && !!base.id && patched.status === 200 && live.status < 300,
        { installed: installed.text, on: on.text, signed: signed.status, base: made.text, patched: patched.text, live: live.text },
      );
      const thread = async (kbIds = []) => (await call(agents, 'POST', '/chat/threads', james, { agentId: agent.id, kbIds })).data?.id;

      const browser = await chromium.launch();
      const errors = [];
      try {
        const signIn = async (email) => {
          const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
          page.on('pageerror', (e) => errors.push(`${email}: ${e.message}`));
          // A second try: the dev console compiles a route on its first visit, which can outlast one sign-in's wait.
          for (let attempt = 1; ; attempt++) {
            await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
            await page.getByLabel('Work email').fill(email);
            await page.getByLabel('Password').fill(PASSWORD);
            await page.getByTestId('login-submit').click();
            const ok = await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 }).then(() => true, (e) => (attempt === 2 ? Promise.reject(e) : false));
            if (ok) return page;
          }
        };
        const page = await signIn('j.richardson@harborpine.example');
        const openThread = async (id) => {
          await page.goto(`${consoleUrl}/chat/${id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await page.getByRole('textbox', { name: 'Message' }).waitFor({ timeout: 120_000 });
        };
        const send = async (text) => {
          await page.getByRole('textbox', { name: 'Message' }).fill(text);
          const sent = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 }));
          await page.getByRole('button', { name: 'Send', exact: true }).click();
          const res = await sent;
          await Promise.race([res?.finished().catch(() => undefined), new Promise((r) => setTimeout(r, 60_000))]);
        };
        const caseEdits = async () => (await fakeState()).edits.filter((e) => e.id === CASE_ID);

        const cases = await thread();
        await step('13 James asks the case helper about case 00044818 and it shows the case from Salesforce', async () => {
          await openThread(cases);
          await send('Find case 00044818.');
          // The console masks an eight-digit number as an account number, so the reply is matched without it.
          await page.getByText(/ is New: Card declined abroad\./).last().waitFor({ timeout: 90_000 });
          await page.screenshot({ path: join(SHOTS, 'chat-case-1280.png') });
          const queries = (await fakeState()).queries;
          check('13 James asks the case helper about case 00044818 and it shows the case from Salesforce', queries.includes(QUERY.replace('{num}', '00044818')), queries.slice(-2));
        }, page);

        let reviewId;
        await step('14 asked to escalate it, the card names the tool by its title and shows the field it changes; the change waits and Salesforce is unchanged', async () => {
          await send('Escalate case 00044818.');
          const card = page.locator('section').filter({ hasText: /salesforce_update_record|Update record|Escalated/ }).last();
          await card.waitFor({ timeout: 90_000 });
          const pending = await until(
            async () => ((await call(agents, 'GET', '/reviews?page=1&pageSize=50', maya)).data?.data ?? []).find((r) => r.origin?.threadId === cases && r.status !== 'resolved'),
            Boolean,
            30,
          );
          reviewId = pending?.id;
          await page.screenshot({ path: join(SHOTS, 'chat-waiting-1280.png') });
          const early = await page.getByText('is now Escalated in Salesforce').count();
          // Each field the write sends is a row a person reads, never the raw object.
          const shown = await card.innerText();
          // The plugin's title for the tool (c-581), never its operation name.
          const readable = /Fields · Status/.test(shown) && /Escalated/.test(shown) && !/[{}]/.test(shown) && /Update a record/.test(shown) && !/salesforce_update_record/.test(shown);
          check('14 asked to escalate it, the card names the tool by its title and shows the field it changes; the change waits and Salesforce is unchanged', !!reviewId && (await caseEdits()).length === 0 && early === 0 && readable, { reviewId, edits: await caseEdits(), early, card: shown.slice(0, 300) });
        }, page);

        const approver = await signIn('m.okafor@harborpine.example');
        await step('15 Maya approves it in Human Tasks and Salesforce records the change, made with the team account', async () => {
          await approver.goto(`${consoleUrl}/reviews?review=${encodeURIComponent(reviewId)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const approve = approver.getByRole('button', { name: 'Approve', exact: true }).first();
          await approve.waitFor({ timeout: 90_000 });
          await approver.screenshot({ path: join(SHOTS, 'human-task-1280.png') });
          await approve.click();
          const confirmRun = approver.getByRole('button', { name: 'Approve and run' });
          if (await confirmRun.waitFor({ timeout: 3_000 }).then(() => true, () => false)) await confirmRun.click();
          if (await approver.getByRole('dialog', { name: 'Confirm it is you' }).waitFor({ timeout: 5_000 }).then(() => true, () => false)) {
            await approver.locator('#reauth-secret').fill(PASSWORD);
            if (await approver.locator('#reauth-code').count()) await approver.locator('#reauth-code').fill('123456');
            await approver.getByTestId('reauth-submit').click();
          }
          const edits = await until(caseEdits, (e) => e.length > 0, 60);
          // The thread resumes in the background after the decision; the reply is read from the thread as it is now.
          let resumed = false;
          for (let i = 0; i < 6 && !resumed; i++) {
            await page.reload({ waitUntil: 'domcontentloaded' });
            resumed = await page.getByText(/ is now Escalated in Salesforce\./).last().waitFor({ timeout: 20_000 }).then(() => true, () => false);
          }
          await page.screenshot({ path: join(SHOTS, 'chat-escalated-1280.png') });
          check(
            '15 Maya approves it in Human Tasks and Salesforce records the change, made with the team account',
            edits.length === 1 && edits[0].change?.Status === 'Escalated' && edits[0].by === 'acme.integration' && resumed,
            { edits, resumed },
          );
        }, approver);

        // S3: the source is made through kb-service's API (the console's Add source offers no plugin sources yet), and
        // synced from its page.
        const source = (await call(kb, 'POST', '/v1/sources', priya, { type: 'tool', name: 'Salesforce articles', config: { plugin: PLUGIN, source: 'articles' }, kbIds: [base.id] })).data ?? {};
        const admin = await signIn('p.shah@harborpine.example');
        const fetched = async () => (await fakeState()).fetched;
        // The page header's button; the overview and an empty items list offer their own.
        const syncButton = () => admin.getByRole('button', { name: 'Sync now' }).first();
        let lastRun = '';
        const syncNow = async () => {
          const done = armed(admin.waitForResponse((r) => r.request().method() === 'POST' && /\/v1\/sources\/[^/]+\/sync$/.test(r.url()), { timeout: 120_000 }));
          await syncButton().click();
          const res = await done;
          await res?.finished().catch(() => undefined);
          lastRun = await res?.text().catch(() => '');
          return res?.status();
        };
        const itemsShown = async () => {
          await admin.goto(`${consoleUrl}/integrations/sources/${source.id}?tab=items`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await admin.getByText('Travel notices').first().waitFor({ timeout: 60_000 }).catch(() => undefined);
          return (await admin.locator('main').textContent()) ?? '';
        };

        let seen = [];
        await step('16 Priya syncs the Salesforce articles source and three articles and one attachment are indexed', async () => {
          await admin.goto(`${consoleUrl}/integrations/sources/${source.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await syncButton().waitFor({ timeout: 90_000 });
          const status = await syncNow();
          seen = await fetched();
          const text = await itemsShown();
          await admin.screenshot({ path: join(SHOTS, 'source-items-1280.png') });
          const titles = ['Reset a card PIN', 'Report a lost card', 'Travel notices', 'card-pin-steps.txt'];
          check(
            '16 Priya syncs the Salesforce articles source and three articles and one attachment are indexed',
            !!source.id && status === 200 && JSON.stringify([...seen].sort()) === JSON.stringify(['ka0001', 'ka0001a', 'ka0002', 'ka0003']) && titles.every((t) => text.includes(t)),
            { source: source.id, status, fetched: seen, missing: titles.filter((t) => !text.includes(t)), run: String(lastRun).slice(0, 600) },
          );
        }, admin);

        await step('17 a second sync fetches nothing again', async () => {
          await admin.goto(`${consoleUrl}/integrations/sources/${source.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await syncButton().waitFor({ timeout: 90_000 });
          const status = await syncNow();
          const now = await fetched();
          check('17 a second sync fetches nothing again', status === 200 && now.length === seen.length, { status, again: now.slice(seen.length) });
          seen = now;
        }, admin);

        await step('18 an article changed at the source is the only one fetched, and becomes version 2', async () => {
          await toFake(`${control}/articles`, { method: 'POST', body: JSON.stringify({ change: [{ Id: 'ka0001', LastModifiedDate: '2026-10-20T09:00:00.000+0000', Body__c: NEW_BODY }] }), type: 'application/json' });
          await admin.goto(`${consoleUrl}/integrations/sources/${source.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await syncButton().waitFor({ timeout: 90_000 });
          const status = await syncNow();
          const now = await fetched();
          const items = (await call(kb, 'GET', `/v1/sources/${source.id}/items?pageSize=50`, priya)).data?.data ?? [];
          const pin = items.find((i) => i.title === 'Reset a card PIN');
          await itemsShown();
          await admin.screenshot({ path: join(SHOTS, 'source-items-v2-1280.png') });
          check('18 an article changed at the source is the only one fetched, and becomes version 2', status === 200 && JSON.stringify(now.slice(seen.length)) === '["ka0001"]' && pin?.version === 'v2', { status, fetched: now.slice(seen.length), version: pin?.version });
        }, admin);

        // A source type added after this console was built must still open its page: the source's own answer is
        // rewritten to a type no console knows, as a newer kb-service or plugin would send.
        await step('30 a source of a type this console does not know still opens its page', async () => {
          const before = errors.length;
          const mine = (url) => new URL(url).pathname.endsWith(`/sources/${source.id}`);
          let rewritten = 0;
          await admin.route(mine, async (route) => {
            // A request still in flight when the step removes this handler is answered by then; answering it again
            // throws outside the step and ends the walk, so that failure is let go.
            try {
              // The page's own address and its Next fetches end the same way; only kb-service's JSON answer is rewritten.
              if (route.request().method() !== 'GET' || !['fetch', 'xhr'].includes(route.request().resourceType())) return await route.continue();
              const res = await route.fetch();
              if (!(res.headers()['content-type'] ?? '').includes('application/json')) return await route.fulfill({ response: res });
              const body = await res.json();
              if (body?.data?.type) {
                body.data.type = 'servicenow_kb';
                rewritten++;
              }
              return await route.fulfill({ response: res, json: body });
            } catch {
              return undefined;
            }
          });
          await admin.goto(`${consoleUrl}/integrations/sources/${source.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          const opened = await syncButton().waitFor({ timeout: 60_000 }).then(() => true, () => false);
          await admin.unroute(mine);
          check('30 a source of a type this console does not know still opens its page', rewritten > 0 && opened && errors.length === before, { rewritten, opened, errors: errors.slice(before, before + 2) });
        }, admin);

        await step('19 James asks about resetting a card PIN and the answer cites the Salesforce article', async () => {
          await openThread(await thread([base.id]));
          await send('What is the way to go about resetting a card PIN?');
          const answered = await page.getByText(/confirms with a code sent by text/).last().waitFor({ timeout: 90_000 }).then(() => true, () => false);
          const marker = page.getByRole('button', { name: /^Citation 1: / });
          await marker.click({ timeout: 15_000 }).catch(() => undefined);
          const opened = await page.getByRole('dialog').getByText(/Reset a card PIN|Reset PIN/).first().waitFor({ timeout: 10_000 }).then(() => true, () => false);
          await page.screenshot({ path: join(SHOTS, 'chat-cited-1280.png') });
          check('19 James asks about resetting a card PIN and the answer cites the Salesforce article', answered && opened, { answered, opened });
        }, page);

        check('no page errors', errors.length === 0, errors.slice(0, 3));
      } finally {
        await browser.close();
      }
    },
    { demo: true, fakeModelRules: RULES, tools: { env: { ...sf.info.settings, OPS_PLUGIN_PATHS: JSON.stringify([SALESFORCE]) } } },
  );
} finally {
  sf.child.stdin.end();
  sf.child.kill('SIGTERM');
}
finish();
