// The Salesforce plugin demo, walked in a browser on the stack's console (make demo-salesforce-walk), as the sample team
// Harbor & Pine (DEMO_TEAM, Operations by default): the operator's plugin install, the team admin's Connect dialog, the plugin's
// agent and workflow added as team copies, a person's chat that signs them in to Salesforce once, and a workflow run
// whose page shows each Salesforce call. Run `make demo-salesforce RESET=1` first so the team admin's steps start again.
//
// SF=fake (default) drives the fake Salesforce that make demo-salesforce keeps running; its sign-in host exists only for
// this browser, which routes it to the fake. SF=real uses the owner's Developer org: the walk stops at Salesforce's
// sign-in page, since the password and the Allow click are the owner's, and says what the page showed.
// Screenshots go to .logs/demo-salesforce/<mode>/. Nothing secret is printed or drawn: the screenshots are taken before
// any client secret is typed, and the real org's client ID is never on one.
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

import { ROOT, check, chromium, finish } from '@ops-ai/usecase-runner/harness';

const MODE = (process.env.SF ?? 'fake').toLowerCase();
const RUN = join(ROOT, process.env.OPS_RUN_DIR ?? '.run');
const port = (name, fallback) => Number(process.env[`OPS_${name}_PORT`] ?? fallback);
const CONSOLE = `http://localhost:${port('CONSOLE', 3016)}`;
const PLATFORM = `http://127.0.0.1:${port('PLATFORM', 8710)}`;
const TOOLS = `http://127.0.0.1:${port('TOOLS', 8720)}`;
const AGENTS = `http://127.0.0.1:${port('AGENTS', 8700)}`;
const SHOTS = join(ROOT, '.logs', 'demo-salesforce', MODE);
const PLUGIN = 'opsai.salesforce';
const PLUGIN_DIR = join(RUN, 'plugins/ops-ai-plugins/plugins/salesforce');
// The team and its people, as scripts/demo_salesforce.py names them (DEMO_TEAM; the dev seed's Operations by default).
const TEAMS = {
  Operations: { lead: 'p.shah@harborpine.example', builder: 'j.richardson@harborpine.example', approver: 'm.okafor@harborpine.example' },
  'Customer Operations': { lead: 'alex.morgan@harborpine.example', builder: 'jordan.ellis@harborpine.example', approver: 'riley.chen@harborpine.example' },
};
const TEAM_NAME = process.env.DEMO_TEAM ?? 'Operations';
const { lead: LEAD, builder: BUILDER, approver: APPROVER } = TEAMS[TEAM_NAME];
// The fake's case the demo works; in the real org, the Developer org's first sample case.
// FROM=n starts at story n against what earlier runs set up; story 3's install is idempotent and always runs.
const FROM = Number(process.env.FROM ?? 1);
const CASE = process.env.SF_CASE ?? (MODE === 'real' ? '00001026' : '00044818');
mkdirSync(SHOTS, { recursive: true });

/** KEY=value lines; values stay in memory and are never printed. */
const readEnv = (path) =>
  Object.fromEntries(
    (existsSync(path) ? readFileSync(path, 'utf8') : '')
      .split('\n')
      .map((l) => l.match(/^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$/))
      .filter(Boolean)
      .map((m) => [m[1], m[2].trim().replace(/^['"]|['"]$/g, '')]),
  );
const PASSWORD = TEAM_NAME === 'Operations' ? 'northfield-demo' : readEnv(join(RUN, 'demo.env')).OPS_DEMO_PASSWORD;
const ADMIN = readEnv(join(RUN, 'dev-admin.env'));
const REAL = readEnv(join(homedir(), '.config/ops-ai/salesforce.env'));
const FAKE = MODE === 'fake' ? JSON.parse(readFileSync(join(RUN, 'fake-salesforce/info.json'), 'utf8').split('\n')[0]) : null;
const FAKE_LOGIN = 'login.salesforce.test';

const call = async (base, method, path, headers, body) => {
  const r = await fetch(`${base}${path}`, { method, headers: { 'Content-Type': 'application/json', ...headers }, body: body === undefined ? undefined : JSON.stringify(body) });
  const text = await r.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    // Not JSON: the text is kept for the failure message.
  }
  return { status: r.status, data: json?.data, text: text.slice(0, 400) };
};
const tokenFor = async (email, password) => (await call(PLATFORM, 'POST', '/v1/auth/sign-in', {}, { email, password })).data?.token;
const until = async (read, ok, tries = 30, ms = 1000) => {
  let got = await read();
  for (let i = 0; i < tries && !ok(got); i++) await new Promise((r) => setTimeout(r, ms)), (got = await read());
  return got;
};
const armed = (p) => (p.catch(() => undefined), p);
const shot = (page, name) => page.screenshot({ path: join(SHOTS, `${name}.png`), fullPage: false });

/** The fake's state through its control route (its own CA, the sign-in host named), for checks on what Salesforce saw. */
async function fakeState() {
  const { request } = await import('node:https');
  const u = new URL(FAKE.control);
  return new Promise((resolve, reject) => {
    const req = request({ host: u.hostname, port: Number(u.port), path: u.pathname, headers: { Host: FAKE_LOGIN }, ca: readFileSync(FAKE.ca), servername: FAKE_LOGIN }, (res) => {
      let text = '';
      res.on('data', (d) => (text += d));
      res.on('end', () => resolve(JSON.parse(text || '{}')));
    });
    req.on('error', reject);
    req.end();
  });
}

/** One story step; a failure keeps the page it was on as failed-<id>.png and the walk goes on. */
async function step(name, page, body) {
  try {
    await body();
  } catch (e) {
    await page?.screenshot({ path: join(SHOTS, `failed-${name.split(' ')[0]}.png`) }).catch(() => {});
    check(name, false, String(e).slice(0, 500));
  }
}

const admin = await tokenFor(ADMIN.OPS_BOOTSTRAP_ADMIN_EMAIL, ADMIN.OPS_BOOTSTRAP_ADMIN_PASSWORD);
const team = (await call(PLATFORM, 'GET', '/v1/teams', { Authorization: `Bearer ${admin}` })).data?.find((t) => t.name === TEAM_NAME)?.id;
const as = async (email) => ({ Authorization: `Bearer ${await tokenFor(email, PASSWORD)}`, 'X-Team-Id': team });
const lead = await as(LEAD);
const salesforceCard = async () => ((await call(TOOLS, 'GET', '/v1/systems', lead)).data ?? []).find((c) => c.pluginId === PLUGIN);

const browser = await chromium.launch();
const errors = [];
/** A console session for `email`; the fake's sign-in host is routed to the fake, as only this browser can reach it. */
async function signIn(email) {
  const context = await browser.newContext({ viewport: { width: 1360, height: 900 } });
  if (FAKE) {
    const [address, fakePort] = JSON.parse(FAKE.settings.OPS_EGRESS_RESOLVE)[FAKE_LOGIN].split(':');
    await context.route(`https://${FAKE_LOGIN}/**`, async (route) => {
      const u = new URL(route.request().url());
      const response = await route.fetch({ url: `https://${address}:${fakePort}${u.pathname}${u.search}`, headers: { ...route.request().headers(), host: FAKE_LOGIN }, maxRedirects: 0, ignoreHTTPSErrors: true });
      await route.fulfill({ response });
    });
  }
  const page = await context.newPage();
  page.on('pageerror', (e) => errors.push(`${email}: ${e.message}`));
  for (let attempt = 1; ; attempt++) {
    await page.goto(`${CONSOLE}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByLabel('Work email').fill(email);
    await page.getByLabel('Password').fill(PASSWORD);
    await page.getByTestId('login-submit').click();
    const ok = await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 }).then(() => true, (e) => (attempt === 2 ? Promise.reject(e) : false));
    if (ok) return page;
  }
}

/** The app's page on Connections, on one tab, screenshotted as `name`. */
async function appPage(page, name, tab) {
  await page.goto(`${CONSOLE}/integrations/apps/${encodeURIComponent(`plugin:${PLUGIN}`)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByRole('tab', { name: 'Tools' }).waitFor({ timeout: 90_000 });
  if (tab) {
    await page.getByRole('tab', { name: tab }).click();
    await page.waitForTimeout(2000);
  }
  await page.waitForTimeout(1500);
  await shot(page, name);
}

/** Signs in on the fake's pop-up as `user` and waits for it to close. */
async function fakeSignIn(popup, user) {
  const name = popup.locator('input[name=username]');
  await name.waitFor({ timeout: 60_000 });
  await name.fill(user);
  await popup.locator('input[type=submit], button[type=submit]').first().click();
  return popup.waitForEvent('close', { timeout: 60_000 }).then(() => true, () => false);
}

/** What Salesforce's real sign-in page showed: its login form, or the error it gave (never typed into). */
async function realSignInPage(popup) {
  // Salesforce goes through a few redirects before its page settles: wait for its login form or the Allow page.
  await popup.locator('input#username, input[name=username], #oaapprove, input[value=Allow]').first().waitFor({ timeout: 60_000 }).catch(() => {});
  const text = ((await popup.locator('body').innerText().catch(() => '')) ?? '').replace(/\s+/g, ' ').slice(0, 300);
  const form = (await popup.locator('input#username, input[name=username], #oaapprove, input[value=Allow]').count()) > 0;
  const url = new URL(popup.url());
  return { host: url.host, path: url.pathname, loginForm: form, text };
}

let realStop = null;
try {
  // Story 1 — the operator installed the plugin (CLI and config); installed, it is there for every team.
  const lp = await signIn(LEAD);
  if (FROM <= 1) await step('1 Operator: the Salesforce plugin validates, is loaded, and shows on Connections', lp, async () => {
    const validated = execFileSync('uv', ['run', '--quiet', 'ops', 'plugin', 'validate', PLUGIN_DIR], { cwd: ROOT, encoding: 'utf8' }).trim();
    writeFileSync(join(SHOTS, 'story1-validate.txt'), `$ ops plugin validate plugins/salesforce\n${validated}\n`);
    await lp.goto(`${CONSOLE}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    const button = lp.getByTestId(`connect-plugin:${PLUGIN}`);
    await button.waitFor({ timeout: 90_000 });
    await lp.getByText('Salesforce', { exact: true }).first().scrollIntoViewIfNeeded();
    await shot(lp, '1-connections-grid');
    check(
      '1 Operator: the Salesforce plugin validates, is loaded, and shows on Connections',
      /^OK opsai\.salesforce/.test(validated) && Boolean(await salesforceCard()),
      { validated },
    );
  });

  // Story 2 — the team admin connects Salesforce from its card: each person signs in, the team account as backup.
  if (FROM <= 2) await step('2 Team admin: Connect dialog, "Each person, team account as backup", the team account signs in and Test passes', lp, async () => {
    await lp.goto(`${CONSOLE}/integrations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await lp.getByTestId(`connect-plugin:${PLUGIN}`).click();
    const dialog = lp.getByTestId('connect-dialog');
    await dialog.waitFor({ timeout: 30_000 });
    await dialog.locator('#who-person_or_team').click();
    await dialog.locator('#app-own').click();
    const section = dialog.getByTestId('env-production');
    await section.locator('#production-clientId').waitFor({ timeout: 30_000 });
    const login = MODE === 'real' ? REAL.SF_LOGIN : FAKE.authorize_url.replace(/\/authorize$/, '');
    await section.locator('#production-login_url').fill(login);
    if (MODE === 'fake') await section.locator('#production-clientId').fill('harbor-pine-ops');
    await shot(lp, '2-connect-dialog');
    if (MODE === 'real') await section.locator('#production-clientId').fill(REAL.SF_CLIENT_ID);
    await section.locator('#production-clientSecret').fill(MODE === 'real' ? REAL.SF_CLIENT_SECRET : 'harbor-pine-ops-secret');
    const tested = armed(lp.waitForResponse((r) => r.request().method() === 'POST' && /\/connections\/[^/]+\/test$/.test(r.url()), { timeout: 120_000 }));
    const [popup] = await Promise.all([lp.waitForEvent('popup', { timeout: 60_000 }), section.getByTestId('test-production').click()]);
    if (MODE === 'real') {
      realStop = await realSignInPage(popup);
      await popup.screenshot({ path: join(SHOTS, '2-salesforce-sign-in.png') });
      check('2 the real org shows its sign-in page for the team account (the owner signs in and clicks Allow)', realStop.loginForm, realStop);
      return;
    }
    const closed = await fakeSignIn(popup, 'harbor.integration');
    await tested;
    await lp.waitForFunction(() => document.querySelector('[data-testid="health-production"]')?.getAttribute('data-status'), null, { timeout: 30_000 }).catch(() => {});
    const health = await section.getByTestId('health-production').getAttribute('data-status').catch(() => null);
    await shot(lp, '2-connect-tested');
    await dialog.getByTestId('connect-submit').click();
    const saved = await dialog.waitFor({ state: 'detached', timeout: 60_000 }).then(() => true, () => false);
    const card = await salesforceCard();
    const detail = (await call(TOOLS, 'GET', `/v1/connections/${card?.connectionId}`, lead)).data ?? {};
    await lp.goto(`${CONSOLE}/tools/connections/${encodeURIComponent(card?.connectionId ?? 'none')}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await lp.getByText(/Each person|team account/i).first().waitFor({ timeout: 60_000 }).catch(() => {});
    await shot(lp, '2-connection-page');
    await appPage(lp, '2-app-connected-team');
    check(
      '2 Team admin: Connect dialog, "Each person, team account as backup", the team account signs in and Test passes',
      closed && health === 'ok' && saved && card?.plugin?.teamOn && detail.signIn === 'person_or_team' && detail.teamBackup === true,
      { closed, health, saved, teamOn: card?.plugin?.teamOn, signIn: detail.signIn, teamBackup: detail.teamBackup },
    );
  });

  // Story 3 — the team admin adds the plugin's agent and workflow as team copies. The Connect dialog's "Add to team" is
  // not built yet, so this is the Python SDK (make demo-salesforce-templates); the console then lists both copies.
  let agentId = null;
  let workflowId = null;
  if (!realStop) {
    await step('3 Team admin: the case helper and the triage workflow are added as team copies (Python SDK) and published', lp, async () => {
      const out = execFileSync('make', ['-s', 'demo-salesforce-templates'], { cwd: ROOT, encoding: 'utf8' }).trim();
      writeFileSync(join(SHOTS, 'story3-templates.txt'), `$ make demo-salesforce-templates\n${out}\n`);
      agentId = out.match(/team's agent (ag_\w+)/)?.[1] ?? null;
      workflowId = out.match(/team's workflow (\w+)/)?.[1] ?? null;
      const agent = (await call(AGENTS, 'GET', `/v1/agents/${agentId}`, lead)).data ?? {};
      const flow = (await call(AGENTS, 'GET', `/v1/workflows/definitions/${workflowId}`, lead)).data ?? {};
      await lp.goto(`${CONSOLE}/agents/${agentId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await lp.getByText('Case helper').first().waitFor({ timeout: 90_000 });
      await shot(lp, '3-agent-copy');
      await lp.goto(`${CONSOLE}/workflows/definitions/${workflowId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await lp.getByText('Triage a Salesforce case').first().waitFor({ timeout: 90_000 });
      await lp.waitForTimeout(1500);
      await shot(lp, '3-workflow-copy');
      await appPage(lp, '3-app-skills', 'Skills');
      check(
        '3 Team admin: the case helper and the triage workflow are added as team copies (Python SDK) and published',
        Boolean(agentId && workflowId) && agent.availability === 'published' && (agent.toolIds ?? []).includes('salesforce_query') && flow.stage === 'live',
        { agentId, workflowId, agent: { availability: agent.availability, tools: agent.toolIds, model: agent.model }, stage: flow.stage },
      );
    });
  }

  // Story 4 — a person asks the case helper about a case: the chat asks them to sign in to Salesforce once, then answers
  // with the case, and the call log shows it ran on their own sign-in.
  if (!realStop && agentId) {
    const bp = await signIn(BUILDER);
    if (FROM <= 4) await step('4 Person: asked about a case, the chat asks them to sign in to Salesforce once, then answers as them', bp, async () => {
      await bp.goto(`${CONSOLE}/chat?agent=${agentId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const box = bp.getByLabel('Message');
      await box.waitFor({ timeout: 120_000 });
      await box.fill(`What is the status of Salesforce case ${CASE}?`);
      await bp.getByRole('button', { name: 'Send' }).click();
      const card = bp.getByTestId('connection-required');
      await card.waitFor({ timeout: 90_000 });
      await shot(bp, '4-chat-sign-in-card');
      const [popup] = await Promise.all([bp.waitForEvent('popup', { timeout: 60_000 }), bp.getByTestId('connection-connect').click()]);
      const closed = await fakeSignIn(popup, BUILDER.split('@')[0]);
      const answered = await bp.getByText(/Salesforce has case .+ as \w+: Card declined abroad\./).last().waitFor({ timeout: 90_000 }).then(() => true, () => false);
      await shot(bp, '4-chat-answered');
      const calls = await until(
        async () => ((await call(TOOLS, 'GET', '/v1/executions?pageSize=20', lead)).data?.data ?? []).filter((c) => c.target === 'salesforce_query' || c.tool === 'salesforce_query'),
        (c) => c.some((x) => x.credential === 'person'),
        10,
      );
      const mine = calls.find((c) => c.credential === 'person');
      check(
        '4 Person: asked about a case, the chat asks them to sign in to Salesforce once, then answers as them',
        closed && answered && mine?.actingFor === BUILDER,
        { closed, answered, call: mine ? { actingFor: mine.actingFor, credential: mine.credential, status: mine.status } : calls.slice(0, 2) },
      );
      // The tool's call log, where each row says whose sign-in it used.
      const modules = (await call(TOOLS, 'GET', '/v1/tool-modules?pageSize=100', lead)).data;
      const moduleId = (modules?.data ?? modules ?? []).find((m) => /salesforce/i.test(`${m.id} ${m.name}`))?.id ?? null;
      if (moduleId) {
        await lp.goto(`${CONSOLE}/tools/${encodeURIComponent(moduleId)}?tab=activity`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const row = lp.getByTestId('caller-signed-in').filter({ hasText: BUILDER }).first();
        const signed = await row.waitFor({ timeout: 60_000 }).then(() => true, () => false);
        if (signed) await row.scrollIntoViewIfNeeded();
        await shot(lp, '4-call-log-signed-in-as');
        check('4 the call log row says the call signed in as the person', signed, { moduleId });
      } else check('4 the call log row says the call signed in as the person', false, 'no module id on the call');
      await appPage(bp, '4-app-connected-as');
      await appPage(bp, '4-app-usage', 'Usage');
    });

    // Story 5 — a workflow run that uses Salesforce tools, started from the console; its page shows each tool call. A run
    // a person starts acts for them, so it reads and writes Salesforce with the sign-in they made in story 4; a run
    // with nobody behind it (a schedule, an email) would use the team account.
    const rp = await signIn(APPROVER);
    await step('5 Workflow: a triage run reads the case, drafts a reply, waits for approval, then marks the case Working', bp, async () => {
      await bp.goto(`${CONSOLE}/workflows/definitions/${workflowId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await bp.getByTestId('definition-start-run').click();
      await bp.getByLabel('Case number').fill(CASE);
      await shot(bp, '5-start-run');
      const started = armed(bp.waitForResponse((r) => r.request().method() === 'POST' && /\/runs?$|\/start$|\/runs$/.test(new URL(r.url()).pathname), { timeout: 60_000 }));
      await bp.getByTestId('definition-start-run-submit').click();
      await started;
      await bp.waitForURL(/\/runs\//, { timeout: 60_000 }).catch(() => {});
      const runUrl = bp.url();
      await bp.getByText(/Approve the reply|Waiting/i).first().waitFor({ timeout: 120_000 }).catch(() => {});
      await shot(bp, '5-run-waiting');
      const review = await until(
        async () => ((await call(AGENTS, 'GET', '/reviews?page=1&pageSize=50', await as(APPROVER))).data?.data ?? []).find((r) => String(r.id).startsWith(runUrl.split('/').pop()) && r.status !== 'resolved'),
        Boolean,
        60,
      );
      await rp.goto(`${CONSOLE}/reviews?review=${encodeURIComponent(review?.id ?? '')}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      // The task's own decision form: Approve as a button, or as an option picked before Decide.
      const option = rp.getByTestId('option-approve');
      const button = rp.getByTestId('decide-approve');
      await option.or(button).first().waitFor({ timeout: 90_000 });
      await shot(rp, '5-human-task');
      if (await button.isVisible().catch(() => false)) await button.click();
      else {
        await option.click();
        await rp.getByTestId('decide').click();
      }
      const confirmRun = rp.getByRole('button', { name: 'Approve and run' });
      if (await confirmRun.waitFor({ timeout: 3_000 }).then(() => true, () => false)) await confirmRun.click();
      if (await rp.getByRole('dialog', { name: 'Confirm it is you' }).waitFor({ timeout: 5_000 }).then(() => true, () => false)) {
        await rp.locator('#reauth-secret').fill(PASSWORD);
        if (await rp.locator('#reauth-code').count()) await rp.locator('#reauth-code').fill('123456');
        await rp.getByTestId('reauth-submit').click();
      }
      const edited = FAKE ? await until(async () => (await fakeState()).edits.filter((e) => e.change?.Status === 'Working'), (e) => e.length > 0, 60) : [];
      await bp.goto(runUrl, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await bp.getByText(/Triaged|Mark it Working/).first().waitFor({ timeout: 90_000 }).catch(() => {});
      await bp.waitForTimeout(1500);
      await shot(bp, '5-run-done');
      const text = (await bp.locator('main').innerText().catch(() => '')) ?? '';
      check(
        '5 Workflow: a triage run reads the case, drafts a reply, waits for approval, then marks the case Working',
        Boolean(review) && edited.length > 0 && edited[0].by === BUILDER.split('@')[0] && /Run a SOQL query|Read the case/.test(text) && /Update a record|Mark it Working/.test(text),
        { runUrl, review: review?.id, edits: edited, text: text.slice(0, 300) },
      );
    });
  }
  check('no page errors', errors.length === 0, errors.slice(0, 3));
} finally {
  await browser.close();
}
if (realStop) console.log(`REAL sign-in page: ${JSON.stringify(realStop)}`);
finish();
