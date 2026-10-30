// uc-567 every run ends with a clear outcome, ui layer: docs/usecases/agents-service/run-outcomes.md. On the demo
// stack (the core bank fake and its published module). A step that kills its worker every time it runs leaves the run
// Stuck with the reason; the run page shows it with Retry and Cancel at 1280 and 375 px, a Retry the run has moved past
// is refused on the page, and Retry carries the run on to its end.
import { execFileSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { PLATFORM_PORT, AGENTS_PORT, ROOT, TOOLS_PORT, check, chromium, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const SHOTS = evidenceDir('561', 'uc');
mkdirSync(SHOTS, { recursive: true });

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const JAMES = 'j.richardson@harborpine.example';
const SAM = 's.adeyemi@harborpine.example';
const PASSWORD = 'northfield-demo';
const ID = 'uc561ui_customer_check';
const DEFINITION = `
schemaVersion: 2
id: ${ID}
name: Customer check (uc-567)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request}
  - id: lookup
    type: ops.action.tool
    typeVersion: 1
    name: Look up the customer
    parameters: {operation: get_customer, input: {customer_id: "$.input.customerId"}}
  - {id: found, type: ops.flow.end, typeVersion: 1, name: Found, parameters: {outcome: found}}
  - {id: failed, type: ops.flow.end, typeVersion: 1, name: Failed, parameters: {outcome: lookup_failed}}
connections:
  - {from: {node: start, port: payload}, to: {node: lookup, port: in}}
  - {from: {node: lookup, port: ok}, to: {node: found, port: in}}
  - {from: {node: lookup, port: refused}, to: {node: failed, port: in}}
  - {from: {node: lookup, port: error}, to: {node: failed, port: in}}
`;
// A worker that dies by SIGKILL every time the lookup step runs: the step is run again, not read from its record, on
// each takeover. A short lease lets the next worker take the run over within seconds.
const DYING = { OPS_ENGINE_FAULT_KILL_AFTER_NODE: 'lookup', OPS_ENGINE_FAULT_IGNORE_RECORDED: '1', OPS_LEASE_TTL_SECONDS: '2' };
const HEALTHY = { OPS_LEASE_TTL_SECONDS: '2', OPS_ENGINE_RECONCILE_SECONDS: '2' };
// The set-aside email: a mailbox on GreenMail, and a worker whose mail listener fails to start a run for a subject with
// BROKEN in it (the dev and test only email_fault_fail_subject), as a message that breaks a start would.
const RUN = Math.random().toString(36).slice(2, 8);
const ADDRESS = `intake-${RUN}@harborpine.test`;
const BROKEN = `unreadable-${RUN}`;
const SECRET = 'UC567_MAIL_PASSWORD';
const MAIL_ID = `uc567mail_${RUN}`;
const MAIL_DEFINITION = `
schemaVersion: 2
id: ${MAIL_ID}
name: Notice intake (uc-567)
nodes:
  - {id: start, type: ops.trigger.email, typeVersion: 1, name: Notice received, parameters: {mailbox: "${ADDRESS}", folder: inbox}}
  - {id: done, type: ops.flow.end, typeVersion: 1, name: Read, parameters: {outcome: read}}
connections:
  - {from: {node: start, port: payload}, to: {node: done, port: in}}
`;
const sendMail = (subject) =>
  execFileSync('uv', ['run', '--quiet', 'python', '-c', `
import smtplib, sys
from email.message import EmailMessage
m = EmailMessage()
m["From"], m["To"], m["Subject"] = "clerk@court.example", sys.argv[1], sys.argv[2]
m.set_content("Please hold the account.")
with smtplib.SMTP("127.0.0.1", int(sys.argv[3])) as s:
    s.send_message(m)
`, ADDRESS, subject, process.env.OPS_GREENMAIL_SMTP_PORT ?? '3025'], { cwd: `${ROOT}/services/agents-service`, stdio: 'pipe' });

const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const json = async (r) => {
  const body = await r.json();
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};
const until = async (probe, ms = 90_000) => {
  for (const end = Date.now() + ms; Date.now() < end; await new Promise((r) => setTimeout(r, 400))) {
    const v = await probe();
    if (v) return v;
  }
  return null;
};

await withUiStack(
  async (consoleUrl, stack) => {
    const H = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
    const created = await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: H, body: JSON.stringify({ yaml: DEFINITION }) });
    if (created.status !== 201) throw new Error(`setup: definition answered ${created.status}: ${await created.text()}`);
    const run = async (id) => json(await fetch(`${agents}/v1/runs/${id}`, { headers: H }));
    const start = async (n) => (await json(await fetch(`${agents}/v1/runs`, { method: 'POST', headers: H, body: JSON.stringify({ workflowId: ID, mode: 'test', input: { customerId: 'CUS-1001' }, runKey: `uc561ui-${n}` }) }))).runId;

    // 1-2. The run's worker dies on the lookup 7 times over; the next worker leaves it, and the reconciler marks it
    // Stuck with the reason.
    const runId = await start(1);
    const deaths = [];
    for (let i = 0; i < 7; i++) {
      const w = await stack.startWorker(DYING);
      deaths.push(await Promise.race([w.exited, new Promise((r) => setTimeout(() => r('alive'), 90_000))]));
    }
    const healthy = await stack.startWorker(HEALTHY);
    const stuck = await until(async () => ((await run(runId)).status === 'stuck' ? run(runId) : null), 60_000);
    check('1 a run whose worker dies on it every time is marked Stuck with the reason, and no worker takes it again', !!stuck && /stopped 7 times (after|while running) Look up the customer/.test(stuck.error ?? '') && stuck.canRetry === true && !deaths.includes('alive'), { status: stuck?.status, error: stuck?.error, deaths });

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(JAMES);
      await page.getByLabel('Password').fill(PASSWORD);
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      // 3. The run page: the Stuck pill, the reason, and Retry beside Cancel.
      await page.goto(`${consoleUrl}/workflows/runs/${runId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('run-status').waitFor({ timeout: 60_000 });
      const pill = (await page.getByTestId('run-status').innerText()).trim();
      const reason = await page.getByTestId('run-stuck').innerText({ timeout: 30_000 }).catch(() => '');
      const retryShown = await page.getByTestId('run-retry').isVisible().catch(() => false);
      const cancelShown = await page.getByTestId('run-cancel').isVisible().catch(() => false);
      const failedAlert = await page.getByText('The run failed').count();
      await page.screenshot({ path: join(SHOTS, 'stuck-1280.png'), fullPage: true });
      check('3 the run page shows Stuck with its reason, Retry and Cancel, and does not call it failed', /stuck/i.test(pill) && /stopped 7 times (after|while running) Look up the customer/.test(reason) && retryShown && cancelShown && failedAlert === 0, { pill, reason, retryShown, cancelShown, failedAlert });

      // 4. At 375 px the header wraps: no sideways scroll, both buttons on screen.
      await page.setViewportSize({ width: 375, height: 800 });
      await page.waitForTimeout(500);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      const box = await page.getByTestId('run-retry').boundingBox().catch(() => null);
      await page.screenshot({ path: join(SHOTS, 'stuck-375.png'), fullPage: true });
      check('4 at 375 px the stuck run page does not scroll sideways and Retry is on screen', overflow <= 0 && !!box && box.x >= 0 && box.x + box.width <= 375, { overflow, box });

      // 5. A Retry the run has already moved past (another tab retried it) is refused on the page, which keeps the run.
      await healthy.stop();
      const elsewhere = await fetch(`${agents}/v1/runs/${runId}/retry`, { method: 'POST', headers: H });
      await page.getByTestId('run-retry').click();
      await page.waitForTimeout(3_000);
      const refused = await page.getByTestId('run-retry-error').innerText({ timeout: 2_000 }).catch(() => '');
      const pillAfter = (await page.getByTestId('run-status').innerText()).trim();
      await page.screenshot({ path: join(SHOTS, 'retry-refused-375.png'), fullPage: true });
      // The page moves on to the run's new state; any message is plain words, never its id or engine terms.
      check('5 a Retry the run has moved past leaves the page on the run as it now is, in plain words', elsewhere.status === 200 && !/stuck/i.test(pillAfter) && !/wfrun_|not stuck;|queued/i.test(refused), { elsewhere: elsewhere.status, refused, pillAfter });
      await page.setViewportSize({ width: 1280, height: 900 });
      // Ended, so the workers below take only the next run.
      await fetch(`${agents}/v1/runs/${runId}/cancel`, { method: 'POST', headers: H });

      // 6. Back to Stuck once more, then Retry from the page carries the run to its end with one lookup.
      const again = await start(2);
      for (let i = 0; i < 7; i++) {
        const w = await stack.startWorker(DYING);
        await Promise.race([w.exited, new Promise((r) => setTimeout(r, 90_000))]);
      }
      const marking = await stack.startWorker(HEALTHY);
      await until(async () => ((await run(again)).status === 'stuck' ? true : null), 60_000);
      await page.goto(`${consoleUrl}/workflows/runs/${again}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('run-retry').click({ timeout: 60_000 });
      const ended = await until(async () => (['succeeded', 'failed'].includes((await run(again)).status) ? run(again) : null), 90_000);
      await page.getByTestId('run-retry').waitFor({ state: 'detached', timeout: 30_000 }).catch(() => undefined);
      const retryGone = (await page.getByTestId('run-retry').count()) === 0;
      await page.reload({ waitUntil: 'domcontentloaded' });
      const result = await page.getByTestId('run-result').locator('xpath=ancestor::section[1]').innerText({ timeout: 30_000 }).catch(() => '');
      check('6 Retry on the page carries the run on to its end and the button goes', ended?.outcome === 'found' && retryGone, { status: ended?.status, outcome: ended?.outcome, retryGone });
      check('6b the result says where the run ended once, with no empty value', !/Found: Found/.test(result) && !/Nothing\s*Raw/.test(result), { result: result.slice(0, 200) });
      await marking.stop();

      // 7. Two emails arrive; the first one's run fails to start on every read, so after 3 reads it is set aside with
      // its reason and the second starts its run.
      const S = { Authorization: `Bearer ${await tokenFor(SAM)}`, 'X-Team-Id': 'team_security', 'Content-Type': 'application/json' };
      await fetch(`${tools}/v1/secrets`, { method: 'POST', headers: S, body: JSON.stringify({ name: SECRET, value: 'app-password', teamId: 'team_ops' }) });
      await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: S, body: JSON.stringify({ value: stack.mail.imapHost, note: 'uc-567' }) });
      await fetch(`${tools}/v1/egress/ranges`, { method: 'POST', headers: S, body: JSON.stringify({ value: stack.mail.range, note: 'uc-567' }) });
      const mailbox = await fetch(`${agents}/v1/channels/mailboxes`, { method: 'POST', headers: H, body: JSON.stringify({ name: `Intake ${RUN}`, address: ADDRESS, provider: 'imap', imapHost: stack.mail.imapHost, imapPort: 143, imapTls: false, passwordSecret: SECRET }) });
      await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: H, body: JSON.stringify({ yaml: MAIL_DEFINITION }) });
      const live = await (await fetch(`${agents}/v1/workflows/definitions/${MAIL_ID}/publish-requests`, { method: 'POST', headers: H, body: '{}' })).json();
      const listener = await stack.startWorker({ OPS_EMAIL_POLL_SECONDS: '1', OPS_EMAIL_FAULT_FAIL_SUBJECT: BROKEN });
      await new Promise((r) => setTimeout(r, 31_000)); // the first read takes the mailbox's cursor; tool lists cache 30 s
      sendMail(`Garnishment notice ${BROKEN}`);
      sendMail(`Garnishment notice ${RUN} readable`);
      const emails = async () => (await json(await fetch(`${agents}/v1/activity?kind=email&pageSize=50`, { headers: H }))).data.filter((r) => r.title.includes(RUN));
      const settled = await until(async () => {
        const rows = await emails();
        return rows.some((r) => r.outcome === 'set_aside') && rows.some((r) => r.outcome === 'started') ? rows : null;
      }, 120_000);
      const outcomes = (settled ?? (await emails())).map((r) => `${r.outcome}:${r.title.includes(BROKEN) ? 'broken' : 'readable'}`);
      check('7 an email whose run fails to start 3 times is set aside, and the email after it starts its run', mailbox.status === 201 && live.data?.status === 'approved' && outcomes.filter((o) => o.endsWith(':broken')).length === 1 && outcomes.includes('set_aside:broken') && outcomes.includes('started:readable') && /^Failed to start 3 times: /.test((settled ?? []).find((r) => r.outcome === 'set_aside')?.detail ?? ''), { mailbox: mailbox.status, live: live.data?.status, outcomes });
      await listener.stop();

      // 8. James presses Run again on the set-aside row in Activity, confirms, and its run starts.
      const runner = await stack.startWorker({ OPS_ENGINE_POLL_SECONDS: '0.2' });
      await page.goto(`${consoleUrl}/activity?kind=email`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const row = page.getByRole('row').filter({ hasText: BROKEN }).filter({ has: page.getByTestId('activity-run-again') });
      await row.first().waitFor({ timeout: 60_000 }).catch(() => undefined);
      const offered = await row.count();
      const rowText = await row.first().innerText().catch(() => '');
      const kinds = await page.getByTestId('activity-kind').allInnerTexts().catch(() => []);
      check('8a the set-aside email is one row that says why, and the link shows only emails', offered === 1 && /Failed to start 3 times/.test(rowText) && kinds.length > 0 && kinds.every((k) => /email/i.test(k)), { offered, rowText: rowText.slice(0, 200), kinds: [...new Set(kinds)] });
      await page.setViewportSize({ width: 375, height: 800 });
      await page.waitForTimeout(500);
      const sideways = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      const againBox = await row.first().locator('[data-testid="activity-run-again"]:visible').boundingBox().catch(() => null);
      await page.screenshot({ path: join(SHOTS, 'activity-375.png'), fullPage: true });
      check('8b at 375 px Run again is on screen and the page does not scroll sideways', sideways <= 0 && !!againBox && againBox.x >= 0 && againBox.x + againBox.width <= 375, { sideways, againBox });
      await page.setViewportSize({ width: 1280, height: 900 });
      await row.first().locator('[data-testid="activity-run-again"]:visible').click({ timeout: 10_000 }).catch(() => undefined);
      const dialog = page.getByRole('dialog', { name: 'Run this email again' });
      const asked = await dialog.waitFor({ timeout: 10_000 }).then(() => true, () => false);
      await page.screenshot({ path: join(SHOTS, 'run-again-confirm-1280.png') });
      const posted = page.waitForResponse((r) => r.url().includes('/set-aside-emails/'), { timeout: 30_000 }).catch(() => null);
      await dialog.getByRole('button', { name: 'Run again' }).click({ timeout: 10_000 }).catch(() => undefined);
      const answer = await posted;
      const answered = answer ? { status: answer.status(), body: (await answer.text()).slice(0, 300) } : null;
      const refusedText = await dialog.getByRole('alert').innerText({ timeout: 2_000 }).catch(() => '');
      const toasted = await page.getByText("The email's run started").waitFor({ timeout: 30_000 }).then(() => true, () => false);
      const ran = await until(async () => (await json(await fetch(`${agents}/v1/runs?workflowId=${MAIL_ID}&pageSize=50`, { headers: H }))).data.find((r) => r.input?.subject?.includes?.(BROKEN) && r.status === 'succeeded'), 60_000);
      check('8 Run again on the set-aside row asks first, then its run starts and says so', offered >= 1 && asked && toasted && !!ran, { offered, asked, toasted, answered, refusedText, ran: ran?.status });
      await runner.stop();

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { demo: true, tools: { mail: true } },
);

finish();
