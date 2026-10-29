// uc-400 a workflow's branches join before the next step, ui layer: docs/usecases/agents-service/branches-join.md.
// James saves the two-checks workflow (the api script's YAML) and runs it twice on a worker; each run's console page
// shows the Join and the decision after it once, and the screening branch skipped when the If goes straight to the
// Join. The same fork meeting at a plain step is marked in the editor. Platform sign-in, no model call.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, PASSWORD, as, readRunPage, saveAndPublish, settled, start } from '../../lib/workflow_ui.mjs';

const SET = 'type: ops.data.set, typeVersion: 1';
const JOIN = 'type: ops.flow.join, typeVersion: 1, name: Join';
const PLAIN = `${SET}, name: Meet, parameters: {values: {met: true}}`;
const TAG = Math.random().toString(36).slice(2, 6);

const definition = (id, meet) => `
schemaVersion: 2
id: ${id}
name: Two checks then one decision (uc-400 ${TAG})
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request}
  - {id: fields, ${SET}, name: Fields, parameters: {values: {amount: "$.input.amount"}}}
  - {id: limits, ${SET}, name: Check limits, parameters: {values: {withinLimit: true}}}
  - id: sanctions
    type: ops.flow.if
    typeVersion: 1
    name: Screen the payee?
    parameters: {conditions: [{left: "$.input.screen", op: eq, right: true}]}
  - {id: screen, ${SET}, name: Screen, parameters: {values: {listed: false}}}
  - {id: screened, ${SET}, name: Screened, parameters: {values: {clear: true}}}
  - {id: meet, ${meet}}
  - {id: decide, ${SET}, name: Decide, parameters: {values: {both: "$.nodes.meet.out"}}}
  - {id: done, type: ops.flow.end, typeVersion: 1, name: Done, parameters: {outcome: decided}}
connections:
  - {from: {node: start, port: payload}, to: {node: fields, port: in}}
  - {from: {node: fields, port: out}, to: {node: limits, port: in}}
  - {from: {node: fields, port: out}, to: {node: sanctions, port: in}}
  - {from: {node: sanctions, port: "true"}, to: {node: screen, port: in}}
  - {from: {node: sanctions, port: "false"}, to: {node: meet, port: in}}
  - {from: {node: screen, port: out}, to: {node: screened, port: in}}
  - {from: {node: screened, port: out}, to: {node: meet, port: in}}
  - {from: {node: limits, port: out}, to: {node: meet, port: in}}
  - {from: {node: meet, port: out}, to: {node: decide, port: in}}
  - {from: {node: decide, port: out}, to: {node: done, port: in}}
`;

await withUiStack(
  async (consoleUrl, stack) => {
    const J = await as(JAMES);
    const id = `uc400_${TAG}`;
    const made = await saveAndPublish(J, definition(id, JOIN));
    check('0 the workflow with a Join saves with no warning and goes live', made.saved.status === 201 && (made.saved.data?.warnings ?? []).length === 0 && made.live, { saved: made.saved.status, warnings: made.saved.data?.warnings, asked: made.asked.data?.status });
    await stack.startWorker();
    const both = await start(J, id, { amount: 900, screen: true });
    const skipped = await start(J, id, { amount: 50, screen: false });
    const [first, second] = [await settled(J, both), await settled(J, skipped)];

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      const one = await readRunPage(page, consoleUrl, both);
      check(
        '1 both branches reach the Join: the run page shows both checks, then the Join and the decision once',
        first?.status === 'succeeded' && /done|succeeded/i.test(one.status) && one.count('limits') === 1 && one.count('screened') === 1 && one.count('meet') === 1 && one.count('decide') === 1,
        { status: one.status, steps: one.steps.map((s) => s.nodeId) },
      );
      const two = await readRunPage(page, consoleUrl, skipped);
      check(
        '2 the If skips the screening: the run page has no screening step, and the Join and the decision once',
        second?.status === 'succeeded' && two.count('screen') === 0 && two.count('screened') === 0 && two.count('meet') === 1 && two.count('decide') === 1,
        { status: two.status, steps: two.steps.map((s) => s.nodeId) },
      );

      // Non-vacuous pair with step 0: the same fork without a Join is marked on its meeting step.
      const plainId = `uc400_plain_${TAG}`;
      const plain = await saveAndPublish(J, definition(plainId, PLAIN));
      await page.goto(`${consoleUrl}/workflows/${plainId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('definition-checks-count').getByText(/warning/).waitFor({ timeout: 60_000 }).catch(() => undefined);
      const marked = await page.locator('[data-node-id="meet"] [data-testid="node-warning"]').count();
      check('3 the fork meeting at a plain step saves, and the editor marks that step with a warning', plain.saved.status === 201 && marked === 1, { saved: plain.saved.status, marked, warnings: plain.saved.data?.warnings });
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
