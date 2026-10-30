// uc-247 a builder tests an agent on a real chat thread the server marks test, ui layer:
// docs/usecases/agents-service/test-an-agent-on-a-real-thread.md. James asks Branch Concierge a question in its page's
// test panel: the thread the panel starts is marked test, the reply arrives, and the test stays out of his
// conversations. Ravi, a viewer, asks too and is told the test could not start. Platform sign-in, scripted model.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, PASSWORD } from '../../lib/workflow_ui.mjs';

const RAVI = 'r.menon@harborpine.example';
const AGENT = 'ag_branch';
const QUESTION = `How do I open a joint account? (uc-247 ${Math.random().toString(36).slice(2, 6)})`;

/** Asks the agent page's test panel `text` as the signed-in person; returns the answer to the thread it started. */
async function askInTest(page, consoleUrl, text) {
  await page.goto(`${consoleUrl}/agents/${AGENT}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  const panel = page.getByTestId('agent-test-panel');
  await panel.waitFor({ timeout: 120_000 });
  const started = page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads$/.test(r.url()), { timeout: 60_000 }).catch(() => undefined);
  const box = panel.getByRole('textbox').first();
  await box.fill(text);
  await panel.getByRole('button', { name: 'Send', exact: true }).click();
  return started;
}

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    const errors = [];
    try {
      const james = await consoleSignIn(browser, consoleUrl, JAMES, PASSWORD, errors);
      const made = await askInTest(james, consoleUrl, QUESTION);
      const thread = made ? await made.json().catch(() => ({})) : {};
      const sent = made ? JSON.parse(made.request().postData() ?? '{}') : {};
      check('1 James asks in the test panel, and the thread it starts is marked test', made?.status() === 201 && sent.test === true && thread.data?.test === true, { status: made?.status(), sent, test: thread.data?.test });

      const panel = james.getByTestId('agent-test-panel');
      const asked = await panel.getByText(QUESTION).first().waitFor({ timeout: 60_000 }).then(() => true, () => false);
      // The reply is the assistant's message after the question; the scripted model answers every question.
      const replied = await james.waitForFunction((q) => {
        const text = document.querySelector('[data-testid="agent-test-panel"]')?.textContent ?? '';
        const at = text.indexOf(q);
        return at >= 0 && text.slice(at + q.length).trim().length > 10;
      }, QUESTION, { timeout: 90_000 }).then(() => true, () => false);
      check('3 the question and its reply show in the panel', asked && replied, { asked, replied });

      // An ordinary chat as well, which the list must show, so an empty list cannot pass for one that leaves tests out.
      const CHAT = `Where is my nearest branch? (uc-247 ${QUESTION.slice(-5, -1)})`;
      await james.goto(`${consoleUrl}/chat?agent=${AGENT}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const chatBox = james.getByRole('textbox', { name: /Message|Ask/ }).first();
      await chatBox.waitFor({ timeout: 60_000 });
      await chatBox.fill(CHAT);
      const chatMade = james.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 90_000 }).catch(() => undefined);
      await james.locator('button[aria-label="Send"]').first().click();
      await chatMade;
      await james.goto(`${consoleUrl}/chat/conversations`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const chatListed = await james.locator('main').getByText(CHAT).first().waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const listed = (await james.locator('main').innerText().catch(() => '')).includes(QUESTION);
      check('4 his conversations list the chat and leave the test out', chatListed && !listed, { chatListed, listed });

      const ravi = await consoleSignIn(browser, consoleUrl, RAVI, PASSWORD, errors);
      const refused = await askInTest(ravi, consoleUrl, `${QUESTION} from Ravi`);
      const toast = await ravi.getByText('Couldn’t start the test').first().waitFor({ timeout: 30_000 }).then(() => true, () => false);
      check('2 Ravi, a viewer, asks too and is told the test could not start (403)', refused?.status() === 403 && toast, { status: refused?.status(), toast });
      // Ravi's refused request is an expected 403 in the console, not a page error.
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
