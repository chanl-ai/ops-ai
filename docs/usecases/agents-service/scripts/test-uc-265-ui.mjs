// uc-265 personal data is masked in an agent's replies, stored messages and workflow step output, ui layer:
// docs/usecases/agents-service/personal-data-masked.md. James asks a new agent about Ann in chat: the reply on screen
// masks her SSN's last four, email, phone and account and keeps her name, and the same holds after a reload, so the
// stored message is masked too. He turns Redact personal data off on the agent's page and publishes it; asked again,
// the reply shows what the model wrote. Platform sign-in, the fake model's ai-steps rules; no real model is called.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { AI_STACK, JAMES, PASSWORD, agents, as } from '../../lib/workflow_ui.mjs';

const RAW = ['6789', 'ann.lee@example.com', '555-0147', '4401235567'];
const shows = (text) => RAW.filter((r) => text.includes(r));

/** Asks the agent in a new chat as the signed-in person and returns the thread's page text once the reply has ended. */
async function ask(page, consoleUrl, agentId, question) {
  await page.goto(`${consoleUrl}/chat?agent=${agentId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  const box = page.getByRole('textbox', { name: /Message|Ask/ }).first();
  await box.waitFor({ timeout: 60_000 });
  await box.fill(question);
  const sent = page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 }).catch(() => undefined);
  await page.locator('button[aria-label="Send"]').first().click();
  const res = await sent;
  await Promise.race([res?.finished().catch(() => undefined), new Promise((r) => setTimeout(r, 60_000))]);
  await page.getByText('Ann Lee').last().waitFor({ timeout: 60_000 }).catch(() => undefined);
  return (await page.getByRole('log').innerText().catch(() => page.locator('main').innerText())).replace(/\s+/g, ' ');
}

await withUiStack(
  async (consoleUrl) => {
    const J = await as(JAMES);
    const made = (await (await fetch(`${agents}/v1/agents`, { method: 'POST', headers: J, body: JSON.stringify({ name: `PII Probe ${Math.random().toString(36).slice(2, 6)}`, role: 'Answers about customers' }) })).json()).data;
    await fetch(`${agents}/v1/agents/${made.id}/publish-requests`, { method: 'POST', headers: J, body: JSON.stringify({ version: made.version, note: 'first' }) });

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      const masked = await ask(page, consoleUrl, made.id, 'UC265-PII who is Ann?');
      check("1 the reply on screen masks Ann's SSN last four, email, phone and account, and keeps her name", masked.includes('Ann Lee') && shows(masked).length === 0, masked.slice(-300));

      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.getByText('Ann Lee').last().waitFor({ timeout: 60_000 }).catch(() => undefined);
      const stored = (await page.getByRole('log').innerText().catch(() => '')).replace(/\s+/g, ' ');
      check('2 after a reload the stored reply is masked the same way', stored.includes('Ann Lee') && shows(stored).length === 0, stored.slice(-300));

      // Redact personal data off on the agent's page: the edit saves into the draft, and Publish puts it live.
      await page.goto(`${consoleUrl}/agents/${made.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const saved = page.waitForResponse((r) => r.request().method() === 'PATCH' && r.url().endsWith(`/v1/agents/${made.id}`) && (r.request().postData() ?? '').includes('"redactPii":false'), { timeout: 60_000 }).catch(() => undefined);
      await page.locator('#g-pii').click({ timeout: 60_000 });
      const patch = await saved;
      await page.getByTestId('request-agent-publish').click({ timeout: 60_000 });
      const dialog = page.getByRole('dialog', { name: /^(Request publish of|Publish) v/ });
      await dialog.getByLabel('What changed').fill('Personal data shown as written');
      const published = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/v1/agents/${made.id}/publish-requests`), { timeout: 60_000 }).catch(() => undefined);
      await dialog.getByRole('button', { name: /^(Request publish|Publish)$/ }).click();
      const pub = await published;
      const plain = await ask(page, consoleUrl, made.id, 'UC265-PII who is Ann?');
      check(
        '4 with Redact personal data off and published, the reply shows what the model wrote',
        patch?.status() === 200 && pub?.status() === 201 && shows(plain).length === RAW.length,
        { patch: patch?.status(), publish: pub?.status(), shown: shows(plain), text: plain.slice(-300) },
      );
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  AI_STACK,
);

finish();
