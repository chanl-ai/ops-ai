// uc-251 a case reads assembled, ui layer: docs/usecases/agents-service/a-case-reads-assembled.md. A fee dispute workflow
// (configuration, nothing in code knows it) opens a complaint case and waits on a person to approve waiving the fee.
// James opens the case: its fields in the complaint type's order, what it waits on with a link to the task, and the
// drafted action. Maya follows that link, approves on the task page, and the case then reads nothing left and the
// action approved. Platform sign-in; no model call is made.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, MAYA, PASSWORD, agents, as, decideOpenTask, saveAndPublish, start, until } from '../../lib/workflow_ui.mjs';

const ID = `uc251_fee_dispute_${Math.random().toString(36).slice(2, 6)}`;
const DEFINITION = `
schemaVersion: 2
id: ${ID}
name: Fee dispute (uc-251 ${ID.slice(-4)})
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
const DISPUTE = {
  customerId: 'CUS-118842',
  customerName: 'Marcus Bell',
  cardAccount: 'CARD-4471',
  feeId: 'FEE-3901',
  amount: '35',
  complaint: 'Charged a late fee after paying on time',
};

/** The case page as a person reads it: its fields in order, what is left, and each drafted action's status. */
async function readCase(page, consoleUrl, caseId) {
  await page.goto(`${consoleUrl}/cases/${caseId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByTestId('case-whats-left').waitFor({ timeout: 60_000 });
  return {
    fields: await page.locator('[data-testid="case-typed-fields"] [data-testid^="case-field-"]').evaluateAll((els) => els.map((e) => [e.getAttribute('data-testid')?.replace('case-field-', ''), e.textContent?.trim() ?? ''])),
    left: (await page.getByTestId('case-whats-left').innerText()).replace(/\s+/g, ' ').trim(),
    task: await page.getByTestId('case-whats-left').getByRole('link').first().getAttribute('href').catch(() => null),
    actions: await page.locator('[data-testid^="case-action-"]').evaluateAll((els) => els.map((e) => e.getAttribute('data-testid')?.replace('case-action-', ''))),
  };
}

await withUiStack(
  async (consoleUrl, stack) => {
    await stack.startWorker();
    const J = await as(JAMES);
    const made = await saveAndPublish(J, DEFINITION);
    if (!made.live) throw new Error(`setup: the fee dispute workflow did not go live: ${made.saved.status} ${JSON.stringify(made.saved.data).slice(0, 300)}`);
    const runId = await start(J, ID, DISPUTE);
    const waiting = await until(async () => {
      const r = (await (await fetch(`${agents}/v1/runs/${runId}`, { headers: J })).json()).data;
      return r?.status === 'waiting' ? r : undefined;
    });
    const caseId = waiting?.steps?.find((s) => s.nodeId === 'open')?.output?.caseId;
    if (!caseId) throw new Error(`setup: the run opened no case: ${JSON.stringify(waiting ?? null).slice(0, 300)}`);

    const browser = await chromium.launch();
    const errors = [];
    try {
      const james = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      const before = await readCase(james, consoleUrl, caseId);
      const order = before.fields.map(([key]) => key);
      const amount = before.fields.find(([key]) => key === 'amount')?.[1] ?? '';
      check(
        "1 the case shows its fields in the complaint type's order, the amount as money",
        JSON.stringify(order) === JSON.stringify(['complaint', 'category', 'urgency', 'amount']) && /35\.00/.test(amount),
        before.fields,
      );
      check(
        '2 it says what it waits on, links the task, and lists the drafted action as pending',
        /waiting on/i.test(before.left) && /Waive fee: .*fee id FEE-3901, amount 35\?/.test(before.left) && /^\/reviews/.test(before.task ?? '') && JSON.stringify(before.actions) === JSON.stringify(['pending']),
        before,
      );

      // Maya, a reviewer of the team, follows the case's link to the task and approves it there.
      const maya = await consoleSignIn(browser, consoleUrl, MAYA, PASSWORD, errors);
      await maya.goto(`${consoleUrl}${before.task}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const decided = await decideOpenTask(maya, 'approve');
      const after = await until(async () => {
        const c = await readCase(james, consoleUrl, caseId);
        return /Nothing is left/.test(c.left) ? c : undefined;
      }, 60);
      check(
        '4 approved on its task page, the case reads nothing left and the action decided',
        decided === 200 && !!after && after.actions.length === 1 && after.actions[0] !== 'pending',
        { decided, after },
      );
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);

finish();
