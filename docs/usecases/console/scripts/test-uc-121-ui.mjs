// uc-121 a builder designs a workflow on a canvas that fills the page, ui layer: docs/usecases/console/workflow-canvas.md
// (c-164). withUiStack's demo stack, signed in through platform-service as James. A ten-step wire review is saved as a
// draft through the API, then opened in the editor at 1440px and 400px. Each step is checked on its own.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const JAMES = 'j.richardson@northfieldbank.com';
const PASSWORD = 'northfield-demo';
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });

const node = (id, type, name, col, row, parameters) => ({ id, type, typeVersion: 1, name, parameters, position: { x: col * 290, y: row * 150 } });
const link = (from, port, to) => ({ from: { node: from, port }, to: { node: to, port: 'in' } });
// Ten steps laid out left to right: wider than a 1440px canvas can show whole at a readable zoom.
const WORKFLOW = {
  schemaVersion: 2,
  id: 'uc121_wire_hold_review',
  name: 'Wire hold review',
  nodes: [
    node('start', 'ops.trigger.request', 'Wire flagged', 0, 1, { inputSchema: { type: 'object', properties: { wire_id: { type: 'string' }, customer_id: { type: 'string' } }, required: ['wire_id', 'customer_id'] } }),
    node('customer', 'ops.action.tool', 'Look up the customer', 1, 1, { operation: 'get_customer', input: { customer_id: '$.input.customer_id' } }),
    node('assess', 'ops.ai.agent', 'Assess the wire', 2, 1, { agent: 'ag_fraud', prompt: 'Assess this wire.', input: { wire_id: '$.input.wire_id' } }),
    node('risky', 'ops.flow.if', 'Risky?', 3, 1, { conditions: [{ left: '$.nodes.assess.out.text', op: 'contains', right: 'risky' }], combine: 'all' }),
    node('review', 'ops.flow.humanReview', 'Hold the wire?', 4, 0.4, { title: 'Hold this wire', approves: 'hold' }),
    node('hold', 'ops.action.tool', 'Place the hold', 5, 0.2, { operation: 'place_wire_hold', input: { wire_id: '$.input.wire_id' }, approvedBy: 'review' }),
    node('record', 'ops.data.set', 'Record the decision', 6, 0.2, { values: { wire_id: '$.input.wire_id', decision: 'held' } }),
    node('held', 'ops.flow.end', 'Held', 7, 0.2, { outcome: 'held' }),
    node('released', 'ops.flow.end', 'Released', 5, 1.6, { outcome: 'released' }),
    node('failed', 'ops.flow.end', 'Needs a person', 4, 2.4, { outcome: 'needs_a_person' }),
  ],
  connections: [
    link('start', 'payload', 'customer'), link('customer', 'ok', 'assess'), link('customer', 'refused', 'failed'), link('customer', 'error', 'failed'),
    link('assess', 'ok', 'risky'), link('assess', 'error', 'failed'), link('risky', 'true', 'review'), link('risky', 'false', 'released'),
    link('review', 'approve', 'hold'), link('review', 'reject', 'released'), link('hold', 'ok', 'record'), link('hold', 'refused', 'failed'),
    link('hold', 'error', 'failed'), link('record', 'out', 'held'),
  ],
};

async function step(name, body) {
  try {
    return await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
    return undefined;
  }
}

await withUiStack(
  async (consoleUrl) => {
    const J = as(await tokenFor(JAMES));
    const saved = await (await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: J, body: JSON.stringify({ definition: WORKFLOW }) })).json();
    check('0 the ten-step workflow saves as a draft', !!saved.data?.version, saved);

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(JAMES);
      await page.getByLabel('Password').fill(PASSWORD);
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      const sidebar = () => page.locator('[data-slot="sidebar"]').first().getAttribute('data-state');
      const sidebarBefore = await sidebar();
      const canvas = page.getByTestId('definition-canvas');
      const open = async () => {
        await page.goto(`${consoleUrl}/workflows/definitions/${WORKFLOW.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await canvas.locator('[data-testid="definition-node"]').first().waitFor({ timeout: 120_000 });
        await page.waitForTimeout(500);
      };
      await open();

      // 1. The canvas fills the page: sidebar collapsed, no side columns, actions in the header.
      await step('1 the sidebar collapses and the canvas takes the width, actions in the header', async () => {
        const box = await canvas.boundingBox();
        const header = await page.getByTestId('page-header').getByTestId('definition-save').count();
        const inspector = await page.getByTestId('definition-inspector').count();
        check('1 the sidebar collapses and the canvas takes the width, actions in the header', sidebarBefore === 'expanded' && (await sidebar()) === 'collapsed' && box.width > 1200 && header === 1 && inspector === 0, { sidebarBefore, box, header, inspector });
      });

      // 2. A readable zoom: never below 0.65, and the trigger is in view.
      await step('2 the graph opens at a readable zoom with the trigger in view', async () => {
        const zoom = await canvas.locator('.react-flow__viewport').evaluate((el) => new DOMMatrix(getComputedStyle(el).transform).a);
        const c = await canvas.boundingBox();
        const t = await canvas.locator('[data-node-id="start"]').boundingBox();
        const inView = t.x >= c.x && t.x + t.width <= c.x + c.width && t.y >= c.y && t.y + t.height <= c.y + c.height;
        check('2 the graph opens at a readable zoom with the trigger in view', zoom >= 0.649 && inView, { zoom, c, t });
      });

      // 3. Fullscreen takes the window and Escape gives it back; every canvas control is named.
      await step('3 fullscreen and back, every control named', async () => {
        await page.getByRole('button', { name: 'Fullscreen' }).click();
        const full = await canvas.boundingBox();
        await page.keyboard.press('Escape');
        const back = await canvas.getAttribute('data-fullscreen');
        const unnamed = await canvas.locator('button').evaluateAll((bs) => bs.filter((b) => !(b.getAttribute('aria-label') || b.innerText.trim())).length);
        check('3 fullscreen and back, every control named', full.width === 1440 && full.height === 900 && back === null && unnamed === 0, { full, back, unnamed });
      });

      // 3b. One click on a step opens its settings straight away: the sheet is in the page by the next frame.
      await step('3b one click on a step opens its settings at once', async () => {
        const node = canvas.locator('[data-node-id="hold"]');
        const box = await node.boundingBox();
        await page.mouse.click(box.x + 40, box.y + 20);
        const atOnce = await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => r(!!document.querySelector('[data-testid="step-sheet-body"]')))));
        const later = await page.getByTestId('step-sheet-body').waitFor({ timeout: 2_000 }).then(() => true, () => false);
        check('3b one click on a step opens its settings at once', atOnce && later, { atOnce, later });
        await page.keyboard.press('Escape');
        await page.getByTestId('step-sheet-body').waitFor({ state: 'detached', timeout: 10_000 }).catch(() => undefined);
      });

      // 4. A refused step: clear the hold step's operation; the step turns red and the count shows the error.
      await step('4 a refused step is marked and counted', async () => {
        await canvas.locator('[data-node-id="hold"]').dblclick();
        await page.getByTestId('definition-node-all-settings').click();
        await page.getByTestId('definition-node-parameters').fill(JSON.stringify({ input: { wire_id: '$.input.wire_id' }, approvedBy: 'review' }));
        await page.getByTestId('definition-checks-count').getByText('1 error').waitFor({ timeout: 30_000 });
        const marked = await canvas.locator('[data-node-id="hold"]').getAttribute('data-error');
        await page.getByTestId('definition-checks-count').click();
        const listed = await page.getByTestId('definition-check').filter({ hasText: 'operation' }).count();
        check('4 a refused step is marked and counted', marked === 'true' && listed === 1, { marked, listed });
        await page.keyboard.press('Escape');
        await page.keyboard.press('Escape');
      });

      // 4b. A warning (two branches meeting with no Join) marks its step and is counted, and never stops the save.
      await step('4b a warning marks its step and is counted, and the workflow saves with it', async () => {
        const FORK = {
          schemaVersion: 2,
          id: 'uc121_fork_without_join',
          name: 'Fork without a join',
          nodes: [
            node('start', 'ops.trigger.request', 'Asked', 0, 1, { inputSchema: { type: 'object', properties: { id: { type: 'string' } } } }),
            node('left', 'ops.data.set', 'Note the left', 1, 0.4, { values: { side: 'left' } }),
            node('right', 'ops.data.set', 'Note the right', 1, 1.6, { values: { side: 'right' } }),
            node('done', 'ops.flow.end', 'Done', 2, 1, { outcome: 'done' }),
          ],
          connections: [link('start', 'payload', 'left'), link('start', 'payload', 'right'), link('left', 'out', 'done'), link('right', 'out', 'done')],
        };
        const savedFork = await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: J, body: JSON.stringify({ definition: FORK }) });
        const said = await savedFork.json().catch(() => ({}));
        await page.goto(`${consoleUrl}/workflows/${FORK.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('definition-checks-count').getByText(/1 warning|\d+ warnings/).waitFor({ timeout: 60_000 });
        const counter = (await page.getByTestId('definition-checks-count').innerText()).trim();
        const marked = await page.locator('[data-node-id="done"] [data-testid="node-warning"]').count();
        check(
          '4b a warning marks its step and is counted, and the workflow saves with it',
          savedFork.status === 201 && /warning/.test(counter) && marked === 1 && (said.data?.warnings ?? []).some((w) => w.node === 'done'),
          { status: savedFork.status, warnings: said.data?.warnings, counter, marked },
        );
      });

      // 5. At 400px the page does not scroll sideways.
      await step('5 no sideways scroll at 400px', async () => {
        await page.setViewportSize({ width: 400, height: 860 });
        await open();
        const width = await page.evaluate(() => document.documentElement.scrollWidth);
        check('5 no sideways scroll at 400px', width === 400, { width });
        await page.setViewportSize({ width: 1440, height: 900 });
      });

      // 6. Leaving the page puts the sidebar back as it was.
      await step('6 the sidebar comes back on leaving', async () => {
        await page.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.waitForTimeout(500);
        check('6 the sidebar comes back on leaving', (await sidebar()) === 'expanded', await sidebar());
      });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { demo: true },
);

finish();
