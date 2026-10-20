// uc-133 agent test replies show what the agent did, ui layer: docs/usecases/agents-service/agent-test-shows-steps.md.
// The scripted agents service with platform sign-in; James builds in team_ops and tests in the page's panel (c-285).
import { check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('j.richardson@northfieldbank.com');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      await page.goto(`${consoleUrl}/agents/ag_fraud`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('test-agent-button').click({ timeout: 120_000 });
      // The test is a real chat in the page's right panel (c-285); Why explains the newest reply.
      const panel = page.getByTestId('agent-test-panel');
      // Each case on a thread of its own: a test is a real chat, and one paused on an approval takes no new message.
      const ask = async (text) => {
        await panel.getByTestId('test-tab').click();
        if (await panel.getByTestId('new-test').isVisible()) await panel.getByTestId('new-test').click();
        await panel.getByLabel('Message').fill(text);
        await panel.locator('button[aria-label="Send"]').click();
        // The submit button reads Stop while the reply streams; the reply has ended when it reads Send again.
        await panel.locator('button[aria-label="Stop"]').waitFor({ timeout: 10_000 }).catch(() => undefined);
        await panel.locator('button[aria-label="Stop"]').waitFor({ timeout: 10_000 }).catch(() => undefined);
    await panel.locator('button[aria-label="Stop"]').waitFor({ state: 'detached', timeout: 120_000 });
        await page.waitForTimeout(1500);
        await panel.getByTestId('why-tab').click();
        const steps = panel.getByTestId('test-steps');
        await steps.waitFor({ timeout: 60_000 });
        return steps;
      };

      const wire = await ask('Place a 24-hour hold on wire W-88213');
      const tools = await wire.getByTestId('test-step-tools').innerText();
      const paused = await wire.getByTestId('test-would-pause').innerText().catch(() => '');
      check('1 a write shows its call stopped for a review and where it waits', /place_wire_hold/.test(tools) && /stopped for a review/.test(tools) && /Waiting on|for /.test(paused), { tools, paused });

      const limit = await ask('What is the daily wire limit?');
      const knowledge = await limit.getByTestId('test-step-knowledge').innerText();
      check('2 a grounded answer names the passages and their knowledge base', /Cited \d+ passage/.test(knowledge) && /Searched /.test(knowledge), knowledge);

      const hello = await ask('Hello');
      const none = await hello.getByTestId('test-step-tools').innerText();
      const gates = await hello.getByTestId('test-step-pause').innerText();
      check('3 a plain reply says it called no tools, names what it holds, and which would pause', /Called no tools/.test(none) && /lookup_account/.test(none) && /Did not pause this time/.test(gates) && /place_wire_hold/.test(gates), { none, gates });
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
