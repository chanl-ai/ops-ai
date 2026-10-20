// uc-225 a reviewer takes a workflow Human Task and sees its deadline, ui layer:
// docs/usecases/agents-service/a-reviewer-takes-a-workflow-human.md. The demo stack with platform sign-in and a worker.
// James starts the mailed document workflow on a faxed notice; its read stops at Check the read. Maya sees the task's
// time left, takes it with Assign to me, and finds it under Assigned to me; James, who started the run, cannot take it.
import { mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, FILES_PORT, PLATFORM_PORT, ROOT, check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const files = `http://127.0.0.1:${FILES_PORT}`;
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@northfieldbank.com';
const MAYA = 'm.okafor@northfieldbank.com';
const NOTICE = readFileSync(join(ROOT, 'services/agents-service/tests/fixtures/mailbox/levy_notice_smudged.pdf'));
const SEED = Object.fromEntries(JSON.parse(readFileSync(join(ROOT, 'services/agents-service/seed/engine_workflows.json'), 'utf8')).map((w) => [w.id, w]));
const SENDER = 'registry@court.example';
const MAILBOX = 'intake@northfield.test';

const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token, type = 'application/json') => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': type });
const json = async (r) => (await r.json()).data;
const until = async (probe, ms = 90_000) => {
  for (const end = Date.now() + ms; Date.now() < end; await new Promise((r) => setTimeout(r, 500))) {
    const got = await probe();
    if (got) return got;
  }
  return probe();
};

async function publish(headers, id) {
  const { teamId: _team, ...definition } = SEED[id];
  const saved = await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers, body: JSON.stringify({ definition }) });
  const live = await fetch(`${agents}/v1/workflows/definitions/${id}/publish-requests`, { method: 'POST', headers, body: '{}' });
  return `${saved.status}/${live.status}/${(await live.json()).data?.status}`;
}

// The demo stack seeds and publishes both workflows (409 here); a fresh database gets them published by this call.
/** A person's upload, as the Files page makes it: a ticket, the bytes, then complete. */
async function upload(headers, name, bytes) {
  const ticket = await json(await fetch(`${files}/v1/files/uploads`, { method: 'POST', headers, body: JSON.stringify({ name, size: bytes.length, mime: 'application/pdf', purpose: 'case_attachment' }) }));
  await fetch(`${files}/v1/files/uploads/${ticket.fileId}/content`, { method: 'PUT', headers: { ...headers, 'Content-Type': 'application/pdf' }, body: bytes });
  return json(await fetch(`${files}/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers }));
}

const runs = async (headers, workflowId) => (await json(await fetch(`${agents}/v1/runs?workflowId=${workflowId}&pageSize=50`, { headers }))).data;
const run = async (headers, id) => json(await fetch(`${agents}/v1/runs/${id}`, { headers }));

await withUiStack(
  async (consoleUrl, stack) => {
    await stack.startWorker({ OPS_FILES_URL: files });
    const browser = await chromium.launch();
    const errors = [];
    try {
      const james = as(await tokenFor(JAMES));
      const maya = as(await tokenFor(MAYA));
      await publish(james, 'levy_case');
      await publish(james, 'mail_document');
      const { file } = await upload(james, 'levy_notice_smudged.pdf', NOTICE);
      const started = await json(await fetch(`${agents}/v1/runs`, { method: 'POST', headers: james, body: JSON.stringify({ workflowId: 'mail_document', input: { fileId: file?.id, name: 'levy_notice_smudged.pdf', from: SENDER, subject: 'Levy notice', mailbox: MAILBOX } }) }));
      const waiting = await until(async () => ((await run(james, started.runId)).waiting?.node === 'check' ? true : null));
      const review = await json(await fetch(`${agents}/reviews/${started.runId}`, { headers: maya }));
      check('1 setup: the read waits at Check the read, a Human Task with a deadline from the server', !!waiting && review?.slaMinutes > 0 && review?.assignee == null, { waiting, id: review?.id, slaMinutes: review?.slaMinutes, assignee: review?.assignee });

      // Step 2: Maya sees the task's time left and nothing assigned to her yet.
      const page = await consoleSignIn(browser, consoleUrl, MAYA, PASSWORD, errors);
      await page.goto(`${consoleUrl}/reviews`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const row = page.getByTestId(`review-row-${review.id}`);
      await row.waitFor({ timeout: 120_000 });
      const rowText = await row.innerText();
      const mineBefore = await page.getByRole('tab', { name: /^Assigned to me/ }).innerText();
      // The row names the task by its question, as its page does, never by its run id.
      const requestCell = (await row.locator('td').nth(2).innerText()).trim();
      check('2b the row names the task by its question, not its id', requestCell.startsWith(review.question ?? review.title) && !requestCell.includes('wfrun_'), { requestCell, question: review.question });
      check('2 the row shows the time left on the task, and nothing is assigned to her yet', /\d+h \d+m left/.test(rowText) && /· 0$/.test(mineBefore.trim()), { rowText: rowText.slice(0, 200), mineBefore });

      // Step 3: she takes it with Assign to me; it is hers under Assigned to me and on the sheet.
      await page.getByRole('checkbox', { name: `Select ${review.id}` }).click();
      const assigned = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/reviews/assign'), { timeout: 60_000 });
      await page.getByRole('button', { name: 'Assign to me' }).click();
      const result = await (await assigned).json();
      const tab = page.getByRole('tab', { name: /^Assigned to me/ });
      await page.waitForFunction(() => /Assigned to me · 1/.test(document.body.innerText), null, { timeout: 30_000 });
      await tab.click();
      // A row opens the task's page; Quick view on the row is the side view this step reads.
      await page.getByTestId(`review-peek-${review.id}`).click();
      const sheet = await page.getByTestId('review-sheet').innerText();
      check('3 Assign to me takes it: it is under Assigned to me, and the sheet says it is hers', result.data?.updated?.includes(review.id) && sheet.includes(`Assigned to ${MAYA}`), { result: result.data, sheet: sheet.slice(0, 300) });

      // The card's visual record: the queue with the task taken, and its sheet, at desktop and phone width.
      const shots = join(ROOT, '.codeloop/evidence/074');
      mkdirSync(shots, { recursive: true });
      await page.getByTestId('review-sheet').waitFor({ state: 'visible', timeout: 10_000 });
      await page.waitForTimeout(500); // the sheet's slide-in
      await page.screenshot({ path: join(shots, 'assigned-sheet-1280.png') });
      await page.keyboard.press('Escape');
      await page.getByTestId('review-sheet').waitFor({ state: 'hidden', timeout: 10_000 });
      await page.screenshot({ path: join(shots, 'assigned-to-me-1280.png') });
      await page.setViewportSize({ width: 400, height: 900 });
      await page.getByTestId(`review-row-${review.id}`).scrollIntoViewIfNeeded();
      await page.screenshot({ path: join(shots, 'assigned-to-me-400.png') });
      await page.setViewportSize({ width: 1440, height: 1000 });

      // Step 4: James started the run, so he may not decide it, and may not take it either.
      const his = await json(await fetch(`${agents}/reviews/assign`, { method: 'POST', headers: james, body: JSON.stringify({ ids: [review.id] }) }));
      check('4 the person who started the run cannot take its review', his?.updated?.length === 0 && /may decide/.test(his?.skipped?.[0]?.reason ?? ''), his);

      check('5 no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);
finish();
