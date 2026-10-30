// uc-210 a levy notice runs on the workflow runner, ui layer: docs/usecases/agents-service/levy-on-the-runner.md.
// A levy case for Marcus Bell waits on its Hold or Flag task in Human Tasks. Maya holds the notice's amount, more than
// his balance: the bank refuses and the same task comes back to her. To hold less she needs the amount the workflow's
// Hold option declares, which the task does not draw yet (step 5 stays red until it does). The mailbox that starts the case
// is walked by uc-245's ui script, so this one starts the levy case as the intake would. Platform sign-in, the demo's
// core bank with place_hold approved by one person; no real model.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, MAYA, PASSWORD, agents, as, decideOpenTask, until } from '../../lib/workflow_ui.mjs';

const RECORD = {
  name: 'Marcus Bell',
  address: '12 Harbour Street, Halifax NS B3J 1A1',
  ssn_last4: '4471',
  amount: 3250,
  currency: 'CAD',
  court: 'Nova Scotia Supreme Court',
  case_no: `NS-2026-GN-${Math.floor(1000 + Math.random() * 8999)}`,
};

const run = async (headers, id) => (await (await fetch(`${agents}/v1/runs/${id}`, { headers })).json()).data;
/** The run once it waits on a person at iteration `n` of its review, or has ended. */
const waitingAt = (headers, id, n) =>
  until(async () => {
    const r = await run(headers, id);
    return (r?.status === 'waiting' && (r.waiting?.iteration ?? 1) >= n) || ['succeeded', 'failed', 'cancelled'].includes(r?.status) ? r : undefined;
  }, 120);

await withUiStack(
  async (consoleUrl, stack) => {
    await stack.startWorker();
    const J = await as(JAMES);
    const started = (await (await fetch(`${agents}/v1/runs`, { method: 'POST', headers: J, body: JSON.stringify({ workflowId: 'levy_case', input: { record: RECORD } }) })).json()).data;
    const first = started?.runId ? await waitingAt(J, started.runId, 1) : undefined;
    if (first?.waiting?.node !== 'review') throw new Error(`setup: the levy case did not wait on its Hold or Flag task: ${JSON.stringify({ status: first?.status, at: first?.waiting?.node, outcome: first?.outcome, error: first?.error }).slice(0, 300)}`);
    const taskOf = (r) => `/reviews?review=${encodeURIComponent(`${r.id}:${r.waiting.node}:${r.waiting.iteration ?? 1}`)}`;

    const browser = await chromium.launch();
    const errors = [];
    try {
      const maya = await consoleSignIn(browser, consoleUrl, MAYA, PASSWORD, errors);
      await maya.goto(`${consoleUrl}${taskOf(first)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await maya.getByTestId('decision-panel').waitFor({ timeout: 60_000 });
      // The notice's amount (3,250.00) is more than the account's balance at the demo bank, so the bank refuses the hold
      // and the case comes back to the same task, as the api layer's step 4 shows with 9000.
      const over = await decideOpenTask(maya, 'hold');
      const back = await waitingAt(J, first.id, 2);
      const hold = (back?.steps ?? []).filter((s) => s.nodeId === 'hold').pop();
      check(
        '4 Maya holds the notice amount, more than the balance: the bank refuses it and the same task comes back to her',
        over === 200 && back?.status === 'waiting' && back?.waiting?.node === 'review' && (back?.waiting?.iteration ?? 1) === 2 && hold?.port === 'error',
        { decision: over, status: back?.status, at: back?.waiting?.node, iteration: back?.waiting?.iteration, hold: hold && { port: hold.port } },
      );

      // To hold less she needs the amount the workflow's Hold option declares; the task draws no field for it, since a
      // workflow review sends no step option's inputs to the task (engine_reviews option_view).
      await maya.goto(`${consoleUrl}${taskOf(back)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await maya.getByTestId('decision-panel').waitFor({ timeout: 60_000 });
      await maya.getByTestId('option-hold').click();
      const amountField = await maya.getByTestId('option-inputs-hold').getByLabel(/^Amount/i).count();
      check('5 the task offers Hold an amount, so Maya can hold 1500 instead', amountField === 1, { amountField });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);

finish();
