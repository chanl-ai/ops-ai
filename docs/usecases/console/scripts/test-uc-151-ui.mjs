// uc-151 a builder sets up Email received on the canvas, ui layer: docs/usecases/agents-service/email-starts-a-workflow.md
// (c-187). withUiStack signed in through platform-service as James, with one team mailbox in the agents service's
// settings. A draft whose trigger is Email received is saved through the API; James opens its trigger in the canvas,
// picks the mailbox the server offers, sets the folder and filters, and saves a version that keeps them.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const JAMES = 'j.richardson@northfieldbank.com';
const PASSWORD = 'northfield-demo';
const MAILBOX = 'levy@northfield.example';
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });

const WORKFLOW = {
  schemaVersion: 2,
  id: 'uc151_levy_intake',
  name: 'Levy intake by email',
  nodes: [
    { id: 'start', type: 'ops.trigger.email', typeVersion: 1, name: 'Levy notice arrives', parameters: { mailbox: MAILBOX }, position: { x: 0, y: 0 } },
    { id: 'done', type: 'ops.flow.end', typeVersion: 1, name: 'Done', parameters: {}, position: { x: 300, y: 0 } },
  ],
  connections: [{ from: { node: 'start', port: 'payload' }, to: { node: 'done', port: 'in' } }],
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
    check('0 the draft with an Email received trigger saves', !!saved.data?.version, saved);

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
      await page.goto(`${consoleUrl}/workflows/definitions/${WORKFLOW.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const canvas = page.getByTestId('definition-canvas');
      await canvas.locator('[data-testid="definition-node"]').first().waitFor({ timeout: 120_000 });
      await page.waitForTimeout(500);

      await step('1 the Triggers tab offers Email received', async () => {
        await page.keyboard.press('n');
        const panel = page.getByTestId('step-list');
        await panel.waitFor({ timeout: 10_000 });
        await page.getByTestId('step-tab-trigger').click();
        const types = await panel.locator('[data-type]').evaluateAll((els) => els.map((e) => e.getAttribute('data-type')));
        check('1 the Triggers tab offers Email received', types.includes('ops.trigger.email') && types.includes('ops.trigger.request'), types);
        await page.keyboard.press('Escape');
      });

      await step('2 the trigger sheet says how it starts and what each run receives', async () => {
        await canvas.locator('[data-node-id="start"]').dblclick();
        await page.getByTestId('step-sheet').waitFor({ timeout: 10_000 });
        const how = await page.getByTestId('trigger-how-it-starts').innerText();
        const input = await page.getByTestId('trigger-run-input').innerText();
        check('2 the trigger sheet says how it starts and what each run receives', how.includes(MAILBOX) && /inbox/.test(how) && /attachments/i.test(input) && /Files id/.test(input), { how, input });
      });

      await step('3 the mailbox picker offers the team mailbox; folder and filters are set and saved', async () => {
        await page.locator('[data-field="node-start-mailbox"]').click();
        const offered = await page.getByRole('option').allInnerTexts();
        await page.getByRole('option', { name: MAILBOX }).click();
        await page.locator('[data-field="node-start-folder"]').fill('Levies');
        await page.locator('[data-field="node-start-fromContains"]').fill('@court.example');
        await page.locator('[data-field="node-start-subjectContains"]').fill('garnishment');
        await page.locator('#node-start-hasAttachment').click();
        await page.getByTestId('definition-save').click();
        let params = {};
        for (let i = 0; i < 30; i++) {
          const latest = await (await fetch(`${agents}/v1/workflows/definitions/${WORKFLOW.id}`, { headers: J })).json();
          if (latest.data?.version === 2) {
            params = latest.data.definition.nodes.find((n) => n.id === 'start').parameters;
            break;
          }
          await page.waitForTimeout(500);
        }
        const kept = params.mailbox === MAILBOX && params.folder === 'Levies' && params.fromContains === '@court.example' && params.subjectContains === 'garnishment' && params.hasAttachment === true;
        check('3 the mailbox picker offers the team mailbox; folder and filters are set and saved', offered.some((o) => o.includes(MAILBOX)) && kept, { offered, params });
      });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, agentsEnv: { OPS_MAILBOXES_SEED_FILE: 'seed/mailboxes.json' } },
);

finish();
