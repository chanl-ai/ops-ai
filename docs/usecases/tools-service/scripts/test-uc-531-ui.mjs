// uc-531 A builder's Python function runs as a workflow step, ui layer: docs/usecases/tools-service/a-builder-adds-a-python-function-tool.md
// (c-531). The platform stack with tools-service, the code runner and a worker. James makes a code module whose
// function says whether a spend passes a daily limit, Security (Nadia) approves it, and a workflow's tool step calls it.
// James starts the workflow from its form in the console; the run page shows the step ran and what it returned.
// Screenshots go to evidenceDir('531', 'uc').
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, TOOLS_PORT, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const NADIA = 'n.petrov@harborpine.example';
const FUNCTION = 'uc531_ui_check_limit';
const WORKFLOW = 'uc531_ui_limit';
const SHOTS = evidenceDir('531', 'uc');

const SOURCE = `
def main(input):
    left = 900
    print("left today", left)
    return {"overLimit": input["amount"] > left, "leftToday": left}
`;

const DEFINITION = {
  schemaVersion: 2,
  id: WORKFLOW,
  name: 'Card limit check (uc-531 ui)',
  nodes: [
    {
      id: 'start',
      type: 'ops.trigger.request',
      typeVersion: 1,
      name: 'Spend',
      parameters: { inputSchema: { type: 'object', required: ['amount'], properties: { amount: { type: 'number', title: 'Amount' } } } },
    },
    { id: 'check', type: 'ops.action.tool', typeVersion: 1, name: 'Check the limit', parameters: { operation: FUNCTION, input: { amount: '$.input.amount' } } },
    { id: 'over', type: 'ops.flow.if', typeVersion: 1, name: 'Over the limit?', parameters: { conditions: [{ left: '$.nodes.check.out.overLimit', op: 'eq', right: true }], combine: 'any' } },
    { id: 'refuse', type: 'ops.flow.end', typeVersion: 1, name: 'Refuse', parameters: { outcome: 'over_limit' } },
    { id: 'allow', type: 'ops.flow.end', typeVersion: 1, name: 'Allow', parameters: { outcome: 'within_limit' } },
    { id: 'failed', type: 'ops.flow.end', typeVersion: 1, name: 'Failed', parameters: { outcome: 'check_failed' } },
  ],
  connections: [
    { from: { node: 'start', port: 'payload' }, to: { node: 'check', port: 'in' } },
    { from: { node: 'check', port: 'ok' }, to: { node: 'over', port: 'in' } },
    { from: { node: 'check', port: 'error' }, to: { node: 'failed', port: 'in' } },
    { from: { node: 'check', port: 'refused' }, to: { node: 'failed', port: 'in' } },
    { from: { node: 'over', port: 'true' }, to: { node: 'refuse', port: 'in' } },
    { from: { node: 'over', port: 'false' }, to: { node: 'allow', port: 'in' } },
  ],
};

const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token, team = 'team_ops') => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
const json = async (r) => (await r.json()).data;
async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

await withUiStack(
  async (consoleUrl, stack) => {
    await stack.startWorker({ OPS_GATEWAY_URL: tools });
    mkdirSync(SHOTS, { recursive: true });
    const james = as(await tokenFor(JAMES));
    const nadia = as(await tokenFor(NADIA), 'team_security');

    // Setup: the code module, published through Security's review, and the workflow that calls it, live.
    const function_ = {
      name: FUNCTION,
      description: 'Says whether a spend passes the daily limit',
      access: 'read',
      input: [{ name: 'amount', type: 'number', required: true }],
      code: { source: SOURCE, bindings: [], secrets: [], limits: { memoryMb: 128, timeS: 2, calls: 5 } },
    };
    const made = await fetch(`${tools}/v1/tool-modules`, { method: 'POST', headers: james, body: JSON.stringify({ name: 'uc531-ui-checks', displayName: 'Limit checks', system: 'Card checks', type: 'code', endpoint: '', function: function_ }) });
    const module = await json(made);
    if (made.status !== 201) throw new Error(`setup: the code module answered ${made.status} ${JSON.stringify(module).slice(0, 300)}`);
    await fetch(`${tools}/v1/tool-modules/${module.id}/reviews`, { method: 'POST', headers: james, body: JSON.stringify({ note: 'uc-531 ui' }) });
    const waiting = (await json(await fetch(`${tools}/v1/tool-modules/${module.id}`, { headers: james }))).versions.find((v) => v.status === 'in_review');
    const decided = await fetch(`${agents}/v1/publish-requests/${waiting.reviewId}/decision`, { method: 'POST', headers: nadia, body: JSON.stringify({ decision: 'approved' }) });
    check('0a Security approves the code module (200)', decided.status === 200, (await decided.text()).slice(0, 300));
    const saved = await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: james, body: JSON.stringify({ definition: DEFINITION }) });
    const live = await json(await fetch(`${agents}/v1/workflows/definitions/${WORKFLOW}/publish-requests`, { method: 'POST', headers: james, body: '{}' }));
    check('0b the workflow with the function as its tool step goes live', saved.status < 300 && live?.status === 'approved', { saved: saved.status, live: live?.status });

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      page.setDefaultTimeout(60_000);
      await page.setViewportSize({ width: 1280, height: 800 });
      const shot = async (name) => {
        for (const [w, h, scheme] of [[1280, 800, 'light'], [1280, 800, 'dark'], [375, 800, 'light']]) {
          await page.emulateMedia({ colorScheme: scheme });
          await page.setViewportSize({ width: w, height: h });
          await page.waitForTimeout(700);
          await page.screenshot({ path: join(SHOTS, `${name}-${w}-${scheme}.png`), fullPage: true });
          if (w === 375 && (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth))) errors.push(`${name}: scrolls sideways at 375 px`);
        }
        await page.emulateMedia({ colorScheme: 'light' });
        await page.setViewportSize({ width: 1280, height: 800 });
      };

      let runId = null;
      await step('1 James starts the workflow from its form', async () => {
        await page.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded' });
        await page.getByRole('button', { name: 'Start run' }).first().click({ timeout: 120_000 });
        const picker = page.getByRole('dialog', { name: 'Start a run' });
        await picker.getByTestId('start-run-workflow').getByRole('button', { name: /Choose a workflow/ }).click();
        await page.getByPlaceholder('Search workflows', { exact: true }).fill('Card limit check');
        await page.getByRole('option', { name: /Card limit check \(uc-531 ui\)/ }).first().click();
        const form = page.getByRole('dialog', { name: /^Start a run(:| of)/ });
        if (!(await form.isVisible().catch(() => false)) && (await picker.getByTestId('start-run-next').count())) await picker.getByTestId('start-run-next').click();
        await form.locator('#run-amount').fill('950');
        await form.getByTestId('definition-start-run-submit').click();
        await page.waitForURL(/\/runs\/wfrun_/, { timeout: 60_000 });
        runId = page.url().match(/wfrun_[a-z0-9]+/)?.[0] ?? null;
        check('1 James starts the workflow from its form', !!runId, page.url());
      });

      await step('2 the run page shows the code step ran and the run ended on Refuse', async () => {
        await page.getByTestId('run-story-feed').waitFor({ timeout: 60_000 });
        let lines = [];
        let result = '';
        for (let i = 0; i < 60; i++) {
          await page.reload({ waitUntil: 'domcontentloaded' });
          await page.getByTestId('run-story-feed').waitFor({ timeout: 60_000 });
          lines = (await page.getByTestId('run-story-feed-line').allInnerTexts()).map((t) => t.trim());
          result = (await page.getByTestId('run-result').innerText().catch(() => '')).replace(/\s+/g, ' ');
          if (result) break;
          await page.waitForTimeout(2000);
        }
        await shot('run-page');
        // The story names a tool step by its operation, in words, with the input it was given.
        check('2 the run page shows the code step ran and the run ended on Refuse', lines.some((l) => /check limit: amount 950$/i.test(l)) && lines.some((l) => /finished: Refuse$/.test(l)), { lines, result });
      });

      await step('3 the step shows what the function returned', async () => {
        const res = await fetch(`${agents}/v1/runs/${runId}`, { headers: james });
        const run = await json(res);
        const out = (run?.steps ?? []).find((s) => s.nodeId === 'check')?.output ?? {};
        check('3a the function ran in the sandbox and returned JSON the If read', out.overLimit === true && out.leftToday === 900 && run?.outcome === 'over_limit', { out, outcome: run?.outcome });
        await page.getByText('Check the limit').first().click();
        await page.waitForTimeout(1500);
        const shown = (await page.locator('body').innerText()).replace(/\s+/g, ' ');
        await shot('step-output');
        check('3b the run page shows the step output: over the limit, 900 left', /leftToday|Left today/i.test(shown) && /900/.test(shown), shown.slice(0, 600));
      });

      check('4 no page errors and no sideways scroll at 375 px', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: { gateway: true, runner: true } },
);
finish();
