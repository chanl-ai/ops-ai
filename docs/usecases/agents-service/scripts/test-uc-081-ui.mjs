// uc-081 basic nodes through the queue, ui layer: docs/usecases/agents-service/workflow-runner-basic-nodes.md. On the
// demo stack (the core bank fake and its published module). The editor draws the definition from the server's node
// types and shows only the server's checks; a run started from it waits with no worker, a worker killed after the tool
// step leaves the tool called once, and the run page shows every step with its input, output, port and attempts.
import { PLATFORM_PORT, TOOLS_PORT, AGENTS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const JAMES = 'j.richardson@harborpine.example';
const PASSWORD = 'northfield-demo';
const ID = 'uc081ui_refund_check';
const DEFINITION = `
schemaVersion: 2
id: uc081ui_refund_check
name: Refund check (uc-081 ui)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request}
  - id: fields
    type: ops.data.set
    typeVersion: 1
    name: Set fields
    parameters: {values: {customer: "$.input.customerId", amount: "$.input.amount"}}
  - id: big
    type: ops.flow.if
    typeVersion: 1
    name: Over 100
    parameters: {conditions: [{left: "$.nodes.fields.out.amount", op: gt, right: 100}]}
  - id: lookup
    type: ops.action.tool
    typeVersion: 1
    name: Look up the customer
    parameters: {operation: get_customer, input: {customer_id: "$.nodes.fields.out.customer"}}
  - id: review
    type: ops.flow.humanReview
    typeVersion: 1
    name: Review the refund
    parameters: {title: Refund over 100, summary: "$.nodes.lookup.out.name"}
  - {id: approved, type: ops.flow.end, typeVersion: 1, name: Approved, parameters: {outcome: approved}}
  - {id: rejected, type: ops.flow.end, typeVersion: 1, name: Rejected, parameters: {outcome: rejected}}
  - {id: small, type: ops.flow.end, typeVersion: 1, name: Small, parameters: {outcome: small}}
  - {id: failed, type: ops.flow.end, typeVersion: 1, name: Failed, parameters: {outcome: tool_failed}}
connections:
  - {from: {node: start, port: payload}, to: {node: fields, port: in}}
  - {from: {node: fields, port: out}, to: {node: big, port: in}}
  - {from: {node: big, port: "true"}, to: {node: lookup, port: in}}
  - {from: {node: big, port: "false"}, to: {node: small, port: in}}
  - {from: {node: lookup, port: ok}, to: {node: review, port: in}}
  - {from: {node: lookup, port: refused}, to: {node: failed, port: in}}
  - {from: {node: lookup, port: error}, to: {node: failed, port: in}}
  - {from: {node: review, port: approve}, to: {node: approved, port: in}}
  - {from: {node: review, port: reject}, to: {node: rejected, port: in}}
`;
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
    const types = await json(await fetch(`${agents}/v1/workflows/node-types`, { headers: H }));
    const tool = types.find((t) => t.id === 'ops.action.tool' && t.version === 1);
    const run = async (id) => json(await fetch(`${agents}/v1/runs/${id}`, { headers: H }));

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      const consoleErrors = [];
      page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text().slice(0, 200)));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(JAMES);
      await page.getByLabel('Password').fill(PASSWORD);
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      // The editor draws every node from the server's types, and its ports from the type (the tool's ok, refused, error).
      await page.goto(`${consoleUrl}/workflows/definitions/${ID}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('definition-node').first().waitFor({ timeout: 120_000 });
      const nodes = await page.getByTestId('definition-node').count();
      const lookup = page.locator('[data-testid="definition-node"][data-node-id="lookup"]');
      const ports = (await lookup.locator('[data-port]').evaluateAll((els) => els.map((e) => e.getAttribute('data-port')))).sort();
      const expected = [...tool.inputs, ...tool.outputs].map((p) => p.name).sort();
      await page.getByTestId('definition-checks-count').getByText(/No problems/).waitFor({ timeout: 30_000 }).catch(() => undefined);
      const clean = (await page.getByTestId('definition-checks-count').innerText()).includes('No problems');
      check('the editor draws every node with the ports its server type declares, and the server finds no problem', nodes === 9 && JSON.stringify(ports) === JSON.stringify(expected) && clean, { nodes, ports, expected, clean });

      // A parameter the type's schema refuses is the server's check, on that node; Save waits until it is fixed.
      const bigNode = page.locator('[data-testid="definition-node"][data-node-id="big"]');
      await bigNode.dblclick({ timeout: 10_000 });
      // The node's form is generated from its type; All settings shows the same parameters as JSON.
      await page.getByTestId('definition-node-all-settings').click();
      const params = page.getByTestId('definition-node-parameters');
      const original = await params.inputValue();
      await params.fill('{"conditions": "not a list"}');
      // The step's sheet names the check at its top; the floating count says one error.
      const shown = await page.getByTestId('step-sheet-errors').waitFor({ timeout: 30_000 }).then(() => true, () => false);
      const blocked = await page.getByTestId('definition-save').isDisabled();
      const marked = (await page.locator('[data-testid="definition-node"][data-node-id="big"][data-error]').count()) === 1;
      await params.fill(original);
      await page.getByTestId('definition-checks-count').getByText(/No problems/).waitFor({ timeout: 30_000 }).catch(() => undefined);
      const cleared = (await page.getByTestId('definition-checks-count').innerText()).includes('No problems') && !(await page.getByTestId('definition-save').isDisabled());
      check('a parameter the schema refuses shows as the server check on that node and blocks Save until fixed', shown && blocked && marked && cleared, { shown, blocked, marked, cleared });

      // Start a run from the editor with no worker (a test run: the definition is a draft): it waits in the queue and
      // the run page says so.
      await page.getByTestId('definition-start-run').click();
      await page.getByTestId('definition-run-input').fill(JSON.stringify({ customerId: 'CUS-1001', amount: 250 }));
      await page.getByTestId('definition-start-run-submit').click();
      await page.waitForURL(/\/workflows\/runs\/[^/?]+/, { timeout: 60_000 });
      const runId = decodeURIComponent(new URL(page.url()).pathname.split('/').pop());
      await page.getByTestId('run-status').waitFor({ timeout: 60_000 });
      await page.waitForTimeout(2_000);
      const queuedStatus = (await page.getByTestId('run-status').innerText()).toLowerCase();
      const noSteps = (await page.getByTestId('run-step').count()) === 0;
      check('a run started from the editor waits queued with no worker, and its page shows no step yet', queuedStatus === 'queued' && noSteps, { queuedStatus, noSteps });

      // A worker that dies right after the tool step, then a second one that takes the run over to the review.
      const doomed = await stack.startWorker({ OPS_ENGINE_FAULT_KILL_AFTER_NODE: 'lookup', OPS_LEASE_TTL_SECONDS: '3' });
      const code = await Promise.race([doomed.exited, new Promise((r) => setTimeout(() => r('alive'), 90_000))]);
      // OPS_ENGINE_FAULT_IGNORE_RECORDED=1 is the non-vacuous variant: the second worker then calls the tool again.
      const second = await stack.startWorker({ OPS_LEASE_TTL_SECONDS: '3', ...(process.env.OPS_ENGINE_FAULT_IGNORE_RECORDED ? { OPS_ENGINE_FAULT_IGNORE_RECORDED: '1' } : {}) });
      const waiting = await until(async () => ((await run(runId)).status === 'waiting' ? true : null));
      await page.getByText('Waiting at Review the refund').waitFor({ timeout: 30_000 }).catch(() => undefined);
      const steps = await page.getByTestId('run-step').evaluateAll((els) => els.map((e) => e.getAttribute('data-node-id')));
      check('the first worker dies after the tool step and a second takes the run to the review, shown on the run page', code !== 'alive' && !!waiting && (await page.getByTestId('run-waiting').count()) === 1 && ['start', 'fields', 'big', 'lookup'].every((n) => steps.includes(n)), { code, waiting, steps });

      // The tool step: one attempt in the journal, one call at the gateway, its output and port on the step.
      await page.locator('[data-testid="run-step"][data-node-id="lookup"]').click();
      const sheet = page.getByTestId('run-step-sheet');
      await sheet.waitFor({ timeout: 15_000 });
      const attempts = await sheet.getByTestId('run-step-attempt').count();
      const sheetText = await sheet.innerText();
      const calls = (await json(await fetch(`${tools}/v1/executions?thread=${runId}&pageSize=200`, { headers: H }))).data.filter((r) => r.target === 'get_customer');
      check('the tool step shows one attempt with its port and output, and the gateway saw one call', attempts === 1 && /\bok\b/.test(sheetText) && /Marcus Bell|CUS-1001/.test(sheetText) && calls.length === 1, { attempts, calls: calls.length, port: /\bok\b/.test(sheetText) });
      await second.stop();

      // The Workflows list holds v2 beside v1: New workflow creates a runner draft and opens it, search finds it, a row
      // opens it, and a draft can be deleted from the list.
      const NEW = 'Card limit check 081';
      await page.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByRole('button', { name: 'New workflow' }).first().click({ timeout: 120_000 });
      const dialog = page.getByRole('dialog', { name: 'New workflow' });
      await dialog.getByLabel('Name').fill(NEW);
      await dialog.getByLabel('Starts when').fill('A customer asks to raise a card limit');
      const runnerFirst = await dialog.getByRole('radio', { name: /Runner workflow/ }).isChecked();
      const published = page.waitForResponse((r) => r.request().method() === 'POST' && r.url() === `${agents}/v1/workflows/definitions`, { timeout: 60_000 });
      await dialog.getByRole('button', { name: 'Create and open' }).click();
      const pub = await published;
      const newId = (await pub.json()).data?.workflowId;
      const openedNew = await page.waitForURL(`**/workflows/definitions/${newId}`, { timeout: 60_000 }).then(() => true, () => false);
      await page.getByTestId('definition-node').first().waitFor({ timeout: 60_000 }).catch(() => {});
      const newNodes = await page.getByTestId('definition-node').count();
      check('New workflow creates a runner draft that passes the checks and opens it in the editor', runnerFirst && pub.status() === 201 && openedNew && newNodes === 2, { runnerFirst, status: pub.status(), newId, url: page.url(), newNodes });

      await page.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByPlaceholder('Search workflows…').fill('card limit check 081');
      const row = page.getByRole('row').filter({ hasText: NEW });
      await row.first().waitFor({ timeout: 60_000 }).catch(() => {});
      const listed = await page.getByRole('row').filter({ has: page.getByTestId('workflow-kind') }).allInnerTexts();
      const kind = await row.first().getByTestId('workflow-kind').innerText().catch(() => '');
      check('search finds it in the Workflows list, marked as a v2 runner workflow and a draft', listed.length === 1 && kind === 'Runner · v2' && /Draft/.test(listed[0] ?? '') && /raise a card limit/.test(listed[0] ?? ''), { listed, kind });
      await row.first().getByText(NEW, { exact: true }).click();
      const openedFromRow = await page.waitForURL(`**/workflows/definitions/${newId}`, { timeout: 60_000 }).then(() => true, () => false);
      check('its row opens the v2 editor', openedFromRow, page.url());

      await page.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByPlaceholder('Search workflows…').fill('card limit check 081');
      await page.waitForFunction(() => document.querySelectorAll('[data-testid="workflow-kind"]').length === 1, null, { timeout: 60_000 }).catch(() => {});
      await page.getByRole('checkbox', { name: `Select ${NEW}` }).click({ timeout: 60_000 });
      await page.getByRole('button', { name: 'Delete', exact: true }).first().click({ timeout: 30_000 });
      const confirm = page.getByRole('dialog', { name: /^Delete/ });
      const dialogText = await confirm.innerText({ timeout: 30_000 }).catch((e) => String(e).slice(0, 160));
      const deleted = page.waitForResponse((r) => r.request().method() === 'DELETE' && r.url().endsWith(`/v1/workflows/definitions/${newId}`), { timeout: 30_000 }).catch(() => null);
      const clickError = await confirm.getByRole('button', { name: 'Delete', exact: true }).click({ timeout: 30_000 }).then(() => null, (e) => String(e).slice(0, 600));
      const del = await deleted;
      if (!del) check('the delete request is sent', false, { dialogText, clickError, consoleErrors, toasts: await page.locator('[data-sonner-toast]').allInnerTexts().catch(() => []) });
      const gone = (await fetch(`${agents}/v1/workflows/definitions/${newId}`, { headers: H })).status;
      const ranKept = (await fetch(`${agents}/v1/workflows/definitions/${ID}`, { method: 'DELETE', headers: H })).status;
      check('the draft is deleted from the list, and a workflow that has run cannot be', del?.status() === 204 && gone === 404 && ranKept === 409, { deleted: del?.status(), gone, ranKept });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { demo: true },
);

finish();
