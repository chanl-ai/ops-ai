// uc-477 A person follows an email from arrival to every case it opened, ui layer: docs/usecases/console/follow-an-email-run.md
// (c-477). uc-246's demo stack (platform sign-in, the fake model's committed reads, the core fake bank, a worker). James
// saves copies of the seeded court order notice workflows and sends the intake a test email with the levy notice; then:
// 2 the email run's page shows the email and a row for the attachment's run named after the attachment; 3 that row
// opens the document run, whose page shows the read beside the document with field boxes; 4 a row per debtor, named,
// each with its case and Human Task, a matched debtor's with the customer, accounts and who the task waits for;
// 5 Jordan Whitfield, who matches no customer, has a "No customer matched" case and a Human Task. Screenshots go to
// evidenceDir('477', 'uc').
import { mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, FILES_PORT, PLATFORM_PORT, ROOT, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const files = `http://127.0.0.1:${FILES_PORT}`;
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const MAYA = 'm.okafor@harborpine.example';
const PDF = join(ROOT, 'services/agents-service/tests/fixtures/mailbox/levy_notice.pdf');
const SEED = Object.fromEntries(JSON.parse(readFileSync(join(ROOT, 'services/agents-service/seed/engine_workflows.json'), 'utf8')).map((w) => [w.id, w]));
const SHOTS = evidenceDir('477', 'uc');
const DEBTORS = ['Marcus Bell', 'Priya Natarajan', 'Jordan Whitfield'];

const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });
const json = async (r) => (await r.json()).data;
const until = async (probe, ms = 180_000) => {
  for (const end = Date.now() + ms; Date.now() < end; await new Promise((r) => setTimeout(r, 1000))) {
    const got = await probe();
    if (got) return got;
  }
  return probe();
};

/** The three seeded workflows under this use case's ids and names, each starting the next by its copy's id. */
function copies() {
  const ids = { mail_intake: 'uc477_intake', mail_document: 'uc477_document', levy_case: 'uc477_case' };
  const names = { mail_intake: 'Court order notices by email (uc-477)', mail_document: 'Court order notice: read (uc-477)', levy_case: 'Court order notice: one debtor (uc-477)' };
  return Object.keys(ids).map((seed) => {
    const { teamId: _team, ...d } = structuredClone(SEED[seed]);
    for (const n of d.nodes) if (n.type === 'ops.action.workflow' && ids[n.parameters.workflow]) n.parameters.workflow = ids[n.parameters.workflow];
    return { ...d, id: ids[seed], name: names[seed] };
  });
}

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

await withUiStack(
  async (consoleUrl, stack) => {
    await stack.startWorker({ OPS_FILES_URL: files });
    mkdirSync(SHOTS, { recursive: true });
    const james = as(await tokenFor(JAMES));
    const maya = as(await tokenFor(MAYA));
    for (const definition of copies()) {
      const res = await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: james, body: JSON.stringify({ definition }) });
      if (res.status >= 300) throw new Error(`setup: saving ${definition.id} answered ${res.status} ${(await res.text()).slice(0, 300)}`);
    }
    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      page.setDefaultTimeout(60_000);
      const shot = async (name) => {
        for (const width of [1280, 400]) {
          await page.setViewportSize({ width, height: 900 });
          await page.waitForTimeout(800);
          await page.screenshot({ path: join(SHOTS, `${name}-${width}.png`), fullPage: true });
          if (width === 400 && (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth))) errors.push(`${name}: the page scrolls sideways at 400 px`);
        }
        await page.setViewportSize({ width: 1280, height: 900 });
      };
      const runsOf = async (wid) => (await json(await fetch(`${agents}/v1/runs?workflowId=${wid}&pageSize=50`, { headers: james }))).data ?? [];

      let intakeId = null;
      await step('1 a test email with the levy notice starts the intake', async () => {
        await page.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByRole('button', { name: 'Start run' }).first().click({ timeout: 120_000 });
        const picker = page.getByRole('dialog', { name: /^Start a run$/ });
        await picker.waitFor();
        await picker.getByTestId('start-run-workflow').getByRole('button', { name: /Choose a workflow/ }).click();
        await page.getByPlaceholder('Search workflows', { exact: true }).fill('uc-477');
        await page.getByRole('option', { name: /Court order notices by email/ }).first().click();
        const composer = page.getByRole('dialog', { name: /^Send a test email: Court order notices by email \(uc-477\)/ });
        await composer.waitFor();
        await composer.getByRole('radio', { name: /Test run/ }).click();
        await composer.locator('#run-from').fill('registry@court.example');
        await composer.locator('#run-subject').fill('Notice of garnishment NS-2026-GN-01187');
        await composer.locator('#run-body').fill('Please find attached a notice of garnishment naming three judgment debtors.');
        await composer.locator('input[type="file"]').first().setInputFiles(PDF);
        await composer.getByText(/Uploaded · scan clean|Already stored in your team · reused/).first().waitFor({ timeout: 60_000 });
        const started = page.waitForResponse((r) => r.request().method() === 'POST' && /\/v1\/runs\/start$/.test(r.url()), { timeout: 60_000 });
        await composer.getByTestId('definition-start-run-submit').click();
        const res = await started;
        intakeId = (await res.json()).data?.runId ?? null;
        check('1 a test email with the levy notice starts the intake', res.status() === 202 && !!intakeId, { status: res.status() });
      });

      let documentId = null;
      await step('2 the email run shows the email and a row for the attachment run, named after the attachment', async () => {
        documentId = await until(async () => (await runsOf('uc477_document'))[0]?.id ?? null);
        await page.goto(`${consoleUrl}/workflows/runs/${intakeId}`, { waitUntil: 'domcontentloaded' });
        const email = page.getByTestId('run-email');
        await email.waitFor({ timeout: 60_000 });
        const text = await email.innerText();
        const row = page.getByTestId('run-children').getByText('levy_notice.pdf', { exact: true });
        await row.waitFor({ timeout: 60_000 });
        const json = await page.getByTestId('run-result').locator('pre').count().catch(() => 0);
        // The story replaces the result's fields: only the End step's name shows, its JSON behind Raw.
        const resultText = await page.getByTestId('run-result').innerText().catch(() => '');
        await shot('email-run');
        check('2 the email run shows the email and a row for the attachment run, named after the attachment', /registry@court\.example/.test(text) && !/\[email\]/.test(text) && !/workflow id|run id/i.test(resultText) && /Notice of garnishment NS-2026-GN-01187/.test(text) && /three judgment debtors/.test(text) && /levy_notice\.pdf/.test(text) && json === 0 && !!documentId, { text: text.slice(0, 300), json, resultText: resultText.slice(0, 200), documentId });
      });

      await step('3 the document run shows the read beside the document, each field boxed', async () => {
        // A read under the review floor waits on a person first; Maya approves it as read.
        const waiting = await until(async () => {
          const run = await json(await fetch(`${agents}/v1/runs/${documentId}`, { headers: james }));
          return run?.waiting || (run?.steps ?? []).some((s) => s.nodeId === 'open') ? run : null;
        });
        if (waiting?.waiting?.node === 'check') {
          const r = await fetch(`${agents}/reviews/${encodeURIComponent(`${documentId}:check:${waiting.waiting.iteration}`)}/decision`, { method: 'POST', headers: maya, body: JSON.stringify({ decision: 'approve', reason: 'Checked the three debtors against the notice.' }) });
          if (r.status >= 300) throw new Error(`approving the read answered ${r.status} ${(await r.text()).slice(0, 200)}`);
        }
        await page.getByTestId('run-children-0-run').click();
        await page.waitForURL((u) => u.pathname.endsWith(documentId), { timeout: 60_000 });
        const read = page.getByTestId('document-read');
        await read.waitFor({ timeout: 60_000 });
        const tabs = await page.getByTestId('read-record-tabs').getByRole('tab').allInnerTexts();
        await page.locator('[data-testid="document-viewer"] img').first().waitFor({ timeout: 60_000 });
        const boxes = await page.locator('[data-testid="document-viewer"] [data-box-key]').count();
        await shot('document-read');
        check('3 the document run shows the read beside the document, each field boxed', DEBTORS.every((d) => tabs.some((t) => t.includes(d))) && boxes >= 9, { tabs, boxes });
      });

      await step('4 a row per debtor, named, each with its case and Human Task', async () => {
        await until(async () => (await runsOf('uc477_case')).filter((r) => ['waiting', 'succeeded'].includes(r.status)).length === 3);
        await page.reload({ waitUntil: 'domcontentloaded' });
        const rows = page.getByTestId('run-children');
        await rows.getByText('Jordan Whitfield', { exact: true }).waitFor({ timeout: 60_000 });
        const seen = [];
        for (let i = 0; i < 3; i++) {
          const r = page.getByTestId(`run-children-${i}`);
          seen.push({ text: (await r.locator('xpath=ancestor::li[1]').innerText()).replace(/\s+/g, ' '), cases: await page.getByTestId(`run-children-${i}-case`).count(), tasks: await page.getByTestId(`run-children-${i}-task`).count() });
        }
        await shot('debtor-rows');
        const marcus = seen.find((s) => s.text.includes('Marcus Bell'));
        check('4 a row per debtor, named, each with its case and Human Task', DEBTORS.every((d) => seen.some((s) => s.text.includes(d))) && seen.every((s) => s.cases === 1 && s.tasks === 1) && /Hold or flag · waiting for/.test(marcus?.text ?? '') && /Customer: Marcus Bell/.test(marcus?.text ?? '') && /Accounts: /.test(marcus?.text ?? ''), seen);
      });

      await step('5 Jordan Whitfield has a No customer matched case and a Human Task', async () => {
        const runs = await runsOf('uc477_case');
        let jordan = null;
        for (const r of runs) {
          const d = await json(await fetch(`${agents}/v1/runs/${r.id}`, { headers: james }));
          if (d?.input?.record?.name === 'Jordan Whitfield') jordan = d;
        }
        const review = jordan?.waiting ? await json(await fetch(`${agents}/reviews/${encodeURIComponent(`${jordan.id}:${jordan.waiting.node}:${jordan.waiting.iteration}`)}`, { headers: james })) : null;
        const row = (await page.getByTestId('run-children').locator('li').filter({ hasText: 'Jordan Whitfield' }).innerText()).replace(/\s+/g, ' ');
        check('5 Jordan Whitfield has a No customer matched case and a Human Task', jordan?.status === 'waiting' && /Find the customer or close as not ours/.test(review?.title ?? '') && /Waiting for a person/.test(row) && /Case: (\[Test\] )?No customer matched: Jordan Whitfield \(MB-2026-GN-00318\)/.test(row) && /Find the customer or close as not ours · waiting for/.test(row), { status: jordan?.status, title: review?.title, row });
      });
      check('6 no page errors and no sideways scroll at 400 px', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true, agentsEnv: { OPS_FILES_URL: files } },
);
finish();
