// uc-115 a run shows its workflow graph read-only with what passed, failed and was skipped, ui layer:
// docs/usecases/console/run-on-the-canvas.md (c-097). withUiStack's demo stack with a workflow runner worker: the
// seeded v2 customer summary workflow runs twice, for Priya Natarajan (the scripted model summarises her) and for a
// customer it does not know (its agent step fails on its output schema and the run ends at No summary). Signed in
// through platform-service as James. A third workflow is saved with no node positions, as an API caller or YAML import
// leaves it, to check the canvas lays it out as the editor does. Each step is checked on its own.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const JAMES = 'j.richardson@northfieldbank.com';
const PASSWORD = 'northfield-demo';
const WORKFLOW = 'customer_summary';
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });

async function step(name, body) {
  try {
    return await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
    return undefined;
  }
}

// No node carries a position: the server stores each at 0,0.
const UNPLACED = `
schemaVersion: 2
id: uc115_unplaced
name: Unplaced (uc-115)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request}
  - {id: fields, type: ops.data.set, typeVersion: 1, name: Set fields, parameters: {values: {customer: "$.input.customer"}}}
  - {id: done, type: ops.flow.end, typeVersion: 1, name: Done, parameters: {outcome: done}}
connections:
  - {from: {node: start, port: payload}, to: {node: fields, port: in}}
  - {from: {node: fields, port: out}, to: {node: done, port: in}}
`;

/** Starts a live run and waits until the worker has finished it. */
async function runFor(J, customer, workflowId = WORKFLOW) {
  const started = await (await fetch(`${agents}/v1/runs`, { method: 'POST', headers: J, body: JSON.stringify({ workflowId, input: { customer } }) })).json();
  if (!started.data) throw new Error(`start: ${JSON.stringify(started).slice(0, 300)}`);
  for (let i = 0; i < 120; i++) {
    const run = (await (await fetch(`${agents}/v1/runs/${started.data.runId}`, { headers: J })).json()).data;
    if (['succeeded', 'failed', 'cancelled'].includes(run?.status)) return run;
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`run ${started.data.runId} did not finish`);
}

await withUiStack(
  async (consoleUrl, stack) => {
    await stack.startWorker();
    const J = as(await tokenFor(JAMES));
    const good = await runFor(J, 'Priya Natarajan');
    const bad = await runFor(J, 'Nobody Known');
    const saved = await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: J, body: JSON.stringify({ yaml: UNPLACED }) });
    const live = await (await fetch(`${agents}/v1/workflows/definitions/uc115_unplaced/publish-requests`, { method: 'POST', headers: J, body: '{}' })).json();
    if (!saved.ok || live.data?.status !== 'approved') throw new Error(`setup: unplaced workflow ${saved.status} ${JSON.stringify(live).slice(0, 300)}`);
    const plain = await runFor(J, 'Priya Natarajan', 'uc115_unplaced');
    console.log('runs', JSON.stringify({ good: [good.status, good.steps.map((s) => `${s.nodeId}:${s.status}:${s.port}`)], bad: [bad.status, bad.steps.map((s) => `${s.nodeId}:${s.status}:${s.port}`)] }));

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(JAMES);
      await page.getByLabel('Password').fill(PASSWORD);
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      const marks = async (runId) => {
        await page.goto(`${consoleUrl}/workflows/runs/${runId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('run-canvas').locator('[data-testid="definition-node"]').first().waitFor({ timeout: 120_000 });
        return Object.fromEntries(await page.getByTestId('run-canvas').locator('[data-testid="definition-node"]').evaluateAll((els) => els.map((e) => [e.getAttribute('data-node-id'), e.getAttribute('data-run')])));
      };

      // 1. A run that succeeded: the steps it ran pass, the End it did not reach is skipped.
      await step('1 a succeeded run marks its steps passed and the other End skipped', async () => {
        const m = await marks(good.id);
        check('1 a succeeded run marks its steps passed and the other End skipped', m.start === 'passed' && m.summarise === 'passed' && m.done === 'passed' && m.failed === 'skipped', m);
      });

      // 2. A run whose agent step failed: that step is marked failed, the error path's End passed, Summarised skipped.
      await step('2 a failed step is marked failed and the path not taken skipped', async () => {
        const m = await marks(bad.id);
        check('2 a failed step is marked failed and the path not taken skipped', m.start === 'passed' && m.summarise === 'failed' && m.failed === 'passed' && m.done === 'skipped', m);
      });

      // 3. Clicking the failed step opens its input, output and error.
      await step('3 the failed step opens with its input and error', async () => {
        await page.getByTestId('run-canvas').locator('[data-node-id="summarise"]').click();
        const sheet = page.getByRole('dialog');
        await sheet.waitFor({ timeout: 30_000 });
        const text = await sheet.innerText();
        // The output sits below the input; the sheet scrolls, and innerText reads all of it.
        const failedStep = bad.steps.find((s) => s.nodeId === 'summarise');
        // What the step answered on its error port: its error text when it has one, else its output.
        const why = failedStep?.error ?? failedStep?.output?.error ?? '';
        check(
          '3 the failed step opens with its input and error',
          failedStep?.status === 'error' && text.includes('Nobody Known') && /Error/.test(text) && !!why && text.includes(why.slice(0, 40)),
          { text: text.slice(0, 600), why },
        );
      });

      // 4. A workflow saved with no positions is laid out, not drawn with every node on one spot.
      await step('4 an unplaced workflow is laid out with no two nodes on one spot', async () => {
        const m = await marks(plain.id);
        const boxes = await page.getByTestId('run-canvas').locator('[data-testid="definition-node"]').evaluateAll((els) => els.map((e) => { const r = e.getBoundingClientRect(); return `${Math.round(r.x)},${Math.round(r.y)}`; }));
        check('4 an unplaced workflow is laid out with no two nodes on one spot', boxes.length === 3 && new Set(boxes).size === 3 && m.done === 'passed', { boxes, m });
      });

      // 5. The Graph section says when the workflow cannot be read, and offers a retry, instead of leaving a gap.
      const errorsBefore = errors.length;
      await step('5 the Graph section shows an error with a retry when the workflow does not load', async () => {
        await page.route('**/v1/workflows/definitions/**', (route) => route.fulfill({ status: 500, contentType: 'application/json', body: '{"success":false,"error":{"code":"internal","message":"boom","status":500}}' }));
        await page.goto(`${consoleUrl}/workflows/runs/${plain.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const shown = await page.getByTestId('run-graph-error').waitFor({ timeout: 60_000 }).then(() => true, () => false);
        const retry = shown && (await page.getByTestId('run-graph-error').getByRole('button').count()) > 0;
        await page.unroute('**/v1/workflows/definitions/**');
        check('5 the Graph section shows an error with a retry when the workflow does not load', shown && retry);
        // Page errors from the refused request are this step's own; earlier ones stay counted.
        errors.splice(errorsBefore);
      });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { demo: true },
);

finish();
