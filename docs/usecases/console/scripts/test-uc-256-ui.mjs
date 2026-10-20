// uc-256 A case page says what it is about, what it waits on and what is next, ui layer:
// docs/usecases/console/case-page-assembled.md (c-292). Platform sign-in as Priya (admin of Operations); a workflow
// configured here opens a seeded `complaint` case and waits on a person, so nothing in the console knows the use case.
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, ROOT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const JAMES = 'j.richardson@northfieldbank.com';
// Priya runs Operations, so she can decide its Human Tasks; James, a Builder, builds and starts the workflow.
const PRIYA = 'p.shah@northfieldbank.com';
const SHOTS = join(ROOT, '.codeloop/evidence/292/screens');
const DEFINITION = `
schemaVersion: 2
id: uc256_fee_dispute
name: Fee dispute (uc-256)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Dispute}
  - id: open
    type: ops.action.openCase
    typeVersion: 1
    name: Open a case
    parameters:
      subject: "Fee dispute from {$.input.customerName}"
      priority: high
      customerId: "$.input.customerId"
      customerName: "$.input.customerName"
      caseType: complaint
      fields: {amount: "$.input.amount", complaint: "$.input.complaint", category: fees}
  - id: review
    type: ops.flow.humanReview
    typeVersion: 1
    name: Approve waiving the fee
    parameters: {title: "Waive {$.input.amount} for {$.input.customerName}", approves: waive}
  - id: waive
    type: ops.action.tool
    typeVersion: 1
    name: Waive the fee
    parameters:
      operation: waive_fee
      approvedBy: review
      input: {cardAccount: "$.input.cardAccount", feeId: "$.input.feeId", amount: "$.input.amount"}
  - {id: done, type: ops.flow.end, typeVersion: 1, name: Waived, parameters: {outcome: waived}}
  - {id: declined, type: ops.flow.end, typeVersion: 1, name: Declined, parameters: {outcome: declined}}
  - {id: failed, type: ops.flow.end, typeVersion: 1, name: Could not finish, parameters: {outcome: failed, result: failed}}
connections:
  - {from: {node: start, port: payload}, to: {node: open, port: in}}
  - {from: {node: open, port: opened}, to: {node: review, port: in}}
  - {from: {node: open, port: error}, to: {node: failed, port: in}}
  - {from: {node: review, port: approve}, to: {node: waive, port: in}}
  - {from: {node: review, port: reject}, to: {node: declined, port: in}}
  - {from: {node: waive, port: ok}, to: {node: done, port: in}}
  - {from: {node: waive, port: refused}, to: {node: failed, port: in}}
  - {from: {node: waive, port: error}, to: {node: failed, port: in}}
`;
const DISPUTE = { customerId: 'CUS-118842', customerName: 'Marcus Bell', cardAccount: 'CARD-4471', feeId: 'FEE-3901', amount: '35', complaint: 'Charged a late fee after paying on time' };
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const data = async (r) => (await r.json().catch(() => ({}))).data;

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

await withUiStack(
  async (consoleUrl, stack) => {
    const J = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
    const created = await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: J, body: JSON.stringify({ yaml: DEFINITION }) });
    const live = await data(await fetch(`${agents}/v1/workflows/definitions/uc256_fee_dispute/publish-requests`, { method: 'POST', headers: J, body: '{}' }));
    await stack.startWorker();
    const runId = (await data(await fetch(`${agents}/v1/runs`, { method: 'POST', headers: J, body: JSON.stringify({ workflowId: 'uc256_fee_dispute', input: DISPUTE, runKey: `uc256-${Date.now()}` }) })))?.runId;
    let caseId;
    for (let i = 0; i < 90 && !caseId; i++) {
      const run = (await data(await fetch(`${agents}/v1/runs/${runId}`, { headers: J }))) ?? {};
      if (run.status === 'waiting') caseId = (run.steps ?? []).find((s) => s.nodeId === 'open')?.output?.caseId;
      if (!caseId) await new Promise((r) => setTimeout(r, 1000));
    }
    check('1 the workflow goes live and its run waits with a case open', created.status === 201 && live?.status === 'approved' && !!caseId, { created: created.status, live: live?.status, runId, caseId });
    if (!caseId) return;

    mkdirSync(SHOTS, { recursive: true });
    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
      page.setDefaultTimeout(60_000);
      page.on('pageerror', (e) => errors.push(e.message));
      const read = [];
      page.on('request', (r) => {
        const u = new URL(r.url());
        // The sidebar's open-task count (one row) is the shell's, not the page's.
        if (u.port === String(AGENTS_PORT) && u.searchParams.get('pageSize') !== '1') read.push(`${r.method()} ${u.pathname}`);
      });
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(PRIYA);
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      const openCase = async () => {
        read.length = 0;
        await page.goto(`${consoleUrl}/cases/${caseId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('case-details-card').waitFor();
        await page.waitForTimeout(1500);
      };
      await openCase();

      await step('2 the header, next action and fields come from one case request', async () => {
        const header = (await page.getByTestId('page-header').innerText()).replace(/\s+/g, ' ');
        const next = await page.getByTestId('case-next-action').getAttribute('href');
        const nextSays = (await page.getByTestId('case-next').innerText()).replace(/\s+/g, ' ');
        const rows = await page.locator('[data-testid^="case-field-"]').evaluateAll((els) => els.map((e) => [e.getAttribute('data-testid').slice(11), e.innerText.replace(/\s+/g, ' ').trim()]));
        const caseReads = read.filter((x) => x.startsWith('GET ') && x.includes(`/v1/cases/${caseId}`));
        const joins = read.filter((x) => /^GET .*\/(reviews|runs|files)(\?|$)/.test(x));
        check(
          '2 the header, next action and fields come from one case request',
          /Fee dispute from Marcus Bell/.test(header) && /High/.test(header) && /First response/.test(header) && /Resolution/.test(header) && /^Next: /.test(nextSays) && /^\/reviews\/[^?]/.test(next ?? '') &&
            rows.map(([k]) => k).join(',') === 'complaint,category,urgency,amount' && /35\.00/.test(rows.find(([k]) => k === 'amount')?.[1] ?? '') &&
            caseReads.length >= 1 && joins.length === 0,
          { header: header.slice(0, 240), next, nextSays, rows, caseReads: caseReads.length, joins },
        );
      });

      await step('3 it lists the waiting task and the drafted action, each linking to the task', async () => {
        const task = page.getByTestId('case-waiting-task');
        const action = page.getByTestId('case-action-pending');
        const taskText = (await task.innerText()).replace(/\s+/g, ' ');
        const href = await task.locator('a').first().getAttribute('href');
        const actionText = (await action.innerText()).replace(/\s+/g, ' ');
        check('3 it lists the waiting task and the drafted action, each linking to the task', (await task.count()) === 1 && /Waive fee/.test(taskText) && /35/.test(taskText) && /^\/reviews\/[^?]/.test(href ?? '') && /Waiting on its task/.test(actionText), { taskText, href, actionText });
      });

      await page.screenshot({ path: join(SHOTS, 'case-page-1280.png'), fullPage: true });

      await step('4 the rail links the run and workflow; activity reads in sentences and View all filters to the case', async () => {
        const run = await page.getByTestId('case-link-run').count();
        const details = (await page.getByTestId('case-details-card').innerText()).replace(/\s+/g, ' ');
        const lines = await page.getByTestId('case-activity-line').allInnerTexts();
        await page.getByRole('link', { name: /^View all/ }).click();
        await page.waitForURL(/\/activity\?case=/);
        const url = page.url();
        check(
          '4 the rail links the run and workflow; activity reads in sentences and View all filters to the case',
          run === 1 && /Fee dispute \(uc-256\)/.test(details) && lines.length >= 1 && lines.length <= 5 && !lines.some((l) => /wfrun_|run:/.test(l)) && url.includes(`case=${caseId}`),
          { run, details: details.slice(0, 200), lines, url },
        );
      });

      await step('5 approved where its link opens it, the case shows the action approved and nothing waiting', async () => {
        await openCase();
        // The task link opens it in Human Tasks' quick view, where it is decided by its type's Approve.
        await page.getByTestId('case-waiting-task').locator('a').first().click();
        await page.waitForURL(/\/reviews/);
        const decided = page.waitForResponse((r) => r.request().method() === 'POST' && /\/decision$/.test(r.url()), { timeout: 30_000 }).then(() => true, () => false);
        await page.getByTestId('decide-approve').click({ timeout: 30_000 }).catch(() => undefined);
        if (!(await decided)) {
          await page.screenshot({ path: join(SHOTS, 'case-approve-failed.png') });
          throw new Error(`no decision was sent; the sheet showed: ${(await page.getByTestId('review-sheet').innerText().catch(() => page.locator('body').innerText())).replace(/\s+/g, ' ').slice(0, 500)}`);
        }
        let empty = false;
        let approved = 0;
        for (let i = 0; i < 20 && !(empty && approved); i++) {
          await openCase();
          empty = (await page.getByTestId('case-waiting-empty').count()) === 1;
          approved = await page.getByTestId('case-action-approved').count();
        }
        const next = await page.getByTestId('case-next-action').count();
        check('5 approved where its link opens it, the case shows the action approved and nothing waiting', empty && approved === 1 && next === 0, { empty, approved, next });
      });

      await step('6 at 400px nothing scrolls sideways', async () => {
        await page.setViewportSize({ width: 400, height: 900 });
        await page.waitForTimeout(800);
        await page.screenshot({ path: join(SHOTS, 'case-page-400.png'), fullPage: true });
        const sideways = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
        check('6 at 400px nothing scrolls sideways', sideways <= 0, { sideways });
      });
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
