// uc-231 a Calculate step works out a levy's amount and deadline, ui layer:
// docs/usecases/agents-service/calculate-a-levy-amount-and-deadline.md. James's levy workflow works out the amount it can
// hold, the shortfall and the deadline in tools-service's sandbox; its run page shows them as the result, and a notice
// with no amount ends on the error port with the failed formula named on the step's sheet. Platform sign-in; no model
// call is made.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, PASSWORD, as, readRunPage, readStepSheet, saveAndPublish, settled, start } from '../../lib/workflow_ui.mjs';

const ID = `uc231_levy_amount_${Math.random().toString(36).slice(2, 6)}`;
const DEFINITION = `
schemaVersion: 2
id: ${ID}
name: Levy amount and deadline (uc-231 ${ID.slice(-4)})
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Notice}
  - id: calc
    type: ops.data.compute
    typeVersion: 1
    name: Amount and deadline
    parameters:
      values: {levy: "$.input.levy", balance: "$.input.balance"}
      expressions:
        amount: "min(levy.amount, balance)"
        short: "levy.amount - amount"
        deadline: "business_days(levy.served, 20)"
  - {id: done, type: ops.flow.end, typeVersion: 1, name: Done, parameters: {outcome: done, output: "$.nodes.calc.out"}}
  - {id: failed, type: ops.flow.end, typeVersion: 1, name: Failed, parameters: {outcome: formula_failed, output: "$.nodes.calc.out"}}
connections:
  - {from: {node: start, port: payload}, to: {node: calc, port: in}}
  - {from: {node: calc, port: out}, to: {node: done, port: in}}
  - {from: {node: calc, port: error}, to: {node: failed, port: in}}
`;
// Served on a Friday: twenty working days later is Friday 13 November.
const NOTICE = { levy: { amount: 3250.0, served: '2026-10-16' }, balance: 1800 };

await withUiStack(
  async (consoleUrl, stack) => {
    await stack.startWorker();
    const J = await as(JAMES);
    const made = await saveAndPublish(J, DEFINITION);
    if (!made.live) throw new Error(`setup: the levy workflow did not go live: ${made.saved.status} ${JSON.stringify(made.saved.data).slice(0, 300)}`);
    const worked = await start(J, ID, NOTICE);
    const broken = await start(J, ID, { levy: { served: '2026-10-16' }, balance: 1800 });
    await settled(J, worked);
    await settled(J, broken);

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      const done = await readRunPage(page, consoleUrl, worked);
      const result = (await page.getByTestId('run-result').innerText().catch(() => '')).replace(/\s+/g, ' ');
      const calc = await readStepSheet(page, 'calc');
      check(
        '3 the run ends at Done and its page shows the amount held, the shortfall and the deadline',
        done.outcome === 'done' && /1,?800/.test(result) && /1,?450/.test(result) && /Nov 13, 2026/.test(result) && calc.output?.amount === 1800 && calc.output?.deadline === '2026-11-13',
        { outcome: done.outcome, result: result.slice(0, 300), calc: calc.output },
      );

      const failed = await readRunPage(page, consoleUrl, broken);
      const sheet = await readStepSheet(page, 'calc');
      // The step's own name holds "Amount", so the check reads the formula's failure as written, `amount: ...`.
      const said = JSON.stringify(sheet.output ?? '') + (await page.locator('main').innerText().catch(() => ''));
      check(
        '4 a notice with no amount ends at Failed, and the step names the formula that failed',
        failed.outcome === 'formula_failed' && sheet.port === 'error' && /amount:/.test(said),
        { outcome: failed.outcome, port: sheet.port, output: sheet.output },
      );
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);

finish();
