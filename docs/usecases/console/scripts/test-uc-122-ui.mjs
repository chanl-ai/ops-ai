// uc-122 a builder edits steps in a side sheet and adds them from a tabbed panel, ui layer:
// docs/usecases/console/edit-steps-in-a-sheet.md (c-165). withUiStack's demo stack, signed in through platform-service as
// James. A ten-step wire review is saved as a draft through the API, then edited in the canvas. Each step is checked on its own.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const JAMES = 'j.richardson@harborpine.example';
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
    const def = { ...WORKFLOW, id: 'uc122_wire_hold_review' };
    const saved = await (await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: J, body: JSON.stringify({ definition: def }) })).json();
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
      await page.goto(`${consoleUrl}/workflows/definitions/${def.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const canvas = page.getByTestId('definition-canvas');
      await canvas.locator('[data-testid="definition-node"]').first().waitFor({ timeout: 120_000 });
      await page.waitForTimeout(500);
      const sheet = page.getByTestId('step-sheet');
      const title = () => page.getByTestId('detail-sheet-title').innerText();

      // 1. Add a step: the Actions tab lists only action steps (tools, workflows, case steps); a search finds a step outside the open tab.
      await step('1 the panel filters by tab and searches every tab; a pick opens its sheet', async () => {
        await page.keyboard.press('n');
        const panel = page.getByTestId('step-list');
        await panel.waitFor({ timeout: 10_000 });
        await page.getByTestId('step-tab-action').click();
        const tools = await panel.locator('[data-type]').evaluateAll((els) => els.map((e) => e.getAttribute('data-type')));
        await panel.getByPlaceholder('Search every step').fill('review');
        const found = await panel.locator('[data-type]').evaluateAll((els) => els.map((e) => e.getAttribute('data-type')));
        await panel.locator('[data-type="ops.flow.humanReview"]').click();
        await sheet.waitFor({ timeout: 10_000 });
        const opened = await title();
        const before = def.nodes.length;
        const now = await canvas.locator('[data-testid="definition-node"]').count();
        check('1 the panel filters by tab and searches every tab; a pick opens its sheet', tools.includes('ops.action.tool') && tools.every((t) => t.startsWith('ops.action.')) && found.includes('ops.flow.humanReview') && opened === 'Human review' && now === before + 1, { tools, found, opened, now });
        await page.getByTestId('definition-node-delete').click();
      });

      // 2. The sheet does not block the canvas: with the agent step open, clicking another step moves the sheet there.
      await step('2 an edit lands in the draft and a click on another step moves the open sheet', async () => {
        await canvas.locator('[data-node-id="assess"]').dblclick();
        await sheet.waitFor({ timeout: 10_000 });
        const overlay = await page.locator('[data-slot="sheet-overlay"]').count();
        await page.locator('[data-field="node-assess-prompt"]').fill('Assess this wire carefully.');
        await canvas.locator('[data-node-id="customer"]').click();
        const moved = await title();
        await canvas.locator('[data-node-id="assess"]').click();
        const kept = await page.locator('[data-field="node-assess-prompt"]').inputValue();
        check('2 an edit lands in the draft and a click on another step moves the open sheet', overlay === 0 && moved === 'Look up the customer' && kept === 'Assess this wire carefully.', { overlay, moved, kept });
      });

      // 3. The trigger's sheet says how a run starts and lists the run input from its schema.
      await step('3 the trigger sheet shows how a run starts and the run input', async () => {
        await canvas.locator('[data-node-id="start"]').click();
        const how = await page.getByTestId('trigger-how-it-starts').innerText();
        const input = await page.getByTestId('trigger-run-input').innerText();
        check('3 the trigger sheet shows how a run starts and the run input', /POST \/v1\/runs/.test(how) && how.includes(`workflow__${def.id}`) && /wire_id/i.test(input) && /customer_id/i.test(input) && /required/.test(input), { how, input });
      });

      // 4. A refused step: clear the hold step's operation; the message sits at the top and under Operation.
      await step('4 a refused field shows at the top of the sheet and under its field', async () => {
        // Previous and next walk the steps in run order; Place the hold sits past the sheet's edge, so it is reached by Next.
        for (let i = 0; i < 10 && (await title()) !== 'Place the hold'; i++) await page.getByTestId('detail-sheet-next').click();
        await page.getByTestId('definition-node-all-settings').click();
        await page.getByTestId('definition-node-parameters').fill(JSON.stringify({ input: { wire_id: '$.input.wire_id' }, approvedBy: 'review' }));
        await page.getByTestId('step-sheet-errors').waitFor({ timeout: 30_000 });
        const under = await page.locator('[data-field="node-hold-operation"]').locator('xpath=ancestor::div[1]').innerText();
        check('4 a refused field shows at the top of the sheet and under its field', /operation/.test(under) && /required/.test(under), { under });
      });

      // 5. Escape closes the sheet.
      await step('5 Escape closes the sheet', async () => {
        await page.locator('body').click({ position: { x: 5, y: 5 } }).catch(() => undefined);
        await page.keyboard.press('Escape');
        await page.waitForTimeout(400);
        check('5 Escape closes the sheet', (await sheet.count()) === 0, await sheet.count());
      });

      // 6. A review set to expire has a timeout way out on the canvas, which the engine routes a late review through.
      await step('6 a review set to expire draws a timeout port; one that waits does not', async () => {
        const late = { ...def, id: 'uc122_wire_hold_expires', nodes: def.nodes.map((n) => (n.id === 'review' ? { ...n, parameters: { ...n.parameters, slaHours: 4, onTimeout: 'expire' } } : n)), connections: [...def.connections, link('review', 'timeout', 'failed')] };
        const made = await (await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: J, body: JSON.stringify({ definition: late }) })).json();
        if (!made.data?.version) throw new Error(`save: ${JSON.stringify(made).slice(0, 400)}`);
        const ports = async () => page.locator('.react-flow__node[data-id="review"] [data-port]').evaluateAll((els) => els.map((e) => e.getAttribute('data-port')));
        const waits = await ports();
        // The engine refuses an expiring review whose timeout leads nowhere, so the canvas has to offer that port.
        await page.goto(`${consoleUrl}/workflows/definitions/${late.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.locator('.react-flow__node[data-id="review"]').waitFor({ timeout: 120_000 });
        const expires = await ports();
        check('6 a review set to expire draws a timeout port; one that waits does not', !!made.data?.version && !waits.includes('timeout') && expires.includes('timeout') && expires.filter((x) => x === 'timeout').length === 1, { saved: made.data?.version ?? made, waits, expires });
      });

      // 7. A switch has a way out per case, in order, and otherwise last.
      await step('7 a switch draws a port per case and otherwise last', async () => {
        const sw = {
          ...def,
          id: 'uc122_wire_switch',
          name: 'Wire switch',
          nodes: [
            def.nodes.find((n) => n.id === 'start'),
            node('route', 'ops.flow.switch', 'Which wire?', 1, 1, { cases: [{ name: 'large', conditions: [{ left: '$.input.wire_id', op: 'exists' }], combine: 'all' }, { name: 'known', conditions: [{ left: '$.input.customer_id', op: 'exists' }], combine: 'all' }] }),
            node('held', 'ops.flow.end', 'Held', 2, 0.4, { outcome: 'held' }),
            node('released', 'ops.flow.end', 'Released', 2, 1.6, { outcome: 'released' }),
          ],
          connections: [link('start', 'payload', 'route'), link('route', 'large', 'held'), link('route', 'known', 'held'), link('route', 'otherwise', 'released')],
        };
        const made = await (await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: J, body: JSON.stringify({ definition: sw }) })).json();
        if (!made.data?.version) throw new Error(`save: ${JSON.stringify(made).slice(0, 400)}`);
        await page.goto(`${consoleUrl}/workflows/definitions/${sw.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const route = page.locator('.react-flow__node[data-id="route"]');
        await route.waitFor({ timeout: 120_000 });
        const out = await route.locator('.react-flow__handle.source[data-port]').evaluateAll((els) => els.map((e) => e.getAttribute('data-port')));
        check('7 a switch draws a port per case and otherwise last', JSON.stringify(out) === JSON.stringify(['large', 'known', 'otherwise']), { out });
      });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { demo: true },
);

finish();
