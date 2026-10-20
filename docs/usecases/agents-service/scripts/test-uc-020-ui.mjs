// uc-020 chat starts a workflow, ui layer: docs/usecases/agents-service/chat-starts-workflow.md. Headless Chromium
// against a console whose chat, Cases and Reviews call the agents service on the scripted model.
import { AGENTS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const TEAM = { 'X-Team-Id': 'team_all', 'Content-Type': 'application/json' };
const ASK = 'Start workflow dispute_email: I was charged twice for order 4411 and want the second charge reversed.';
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);
// Returns the status the service now holds, so a run that died with the workflow paused cannot leave this one wrong.
const setStatus = async (status) => (await (await fetch(`${agents}/v1/workflows/dispute_email/status`, { method: 'POST', headers: TEAM, body: JSON.stringify({ status }) })).json()).data?.status;
const childRows = async () => ((await (await fetch(`${agents}/runs?page=1&pageSize=200&view=open`, { headers: TEAM })).json()).data?.data ?? []).filter((r) => (r.trigger ?? '').startsWith('Started by agent')).length;

async function ask(page, consoleUrl) {
  await page.goto(`${consoleUrl}/chat?agent=ag_dispute`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  const box = page.getByLabel('Message');
  await box.waitFor({ timeout: 120_000 });
  await box.fill(ASK);
  const sent = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 }));
  await page.getByRole('button', { name: 'Send' }).click();
  const res = await sent;
  // The reply streams; wait for its end, but never past 60 s, so a stream that stays open cannot hang the run.
  await Promise.race([res?.finished().catch(() => undefined), new Promise((r) => setTimeout(r, 60_000))]);
  return res;
}

await withUiStack(async (consoleUrl) => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    check('dispute_email is live to start with', (await setStatus('live')) === 'live');

    await ask(page, consoleUrl);
    const waiting = page.getByText(/The workflow is waiting for a review: gth_\w+/).last();
    const said = await waiting.waitFor({ timeout: 60_000 }).then(() => true, () => false);
    const child = said ? /gth_\w+/.exec(await waiting.innerText())?.[0] : undefined;
    check('the reply says the workflow waits for a review and names the child', !!child, child ?? (await page.locator('main').innerText().catch(() => '')).slice(-500));
    check('the tool call shows as a card', (await page.getByText('workflow__dispute_email').count()) > 0);
    const conversation = page.url();

    await page.goto(`${consoleUrl}/workflows/runs?kind=graph`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    const row = page.getByTestId(`run-row-${child}`);
    const listed = await row.waitFor({ timeout: 60_000 }).then(() => true, () => false);
    check('Cases shows the child, started by the agent and waiting on a person', listed && (await row.getByText(/Started by agent Card Dispute Resolver/).count()) > 0 && (await row.getByText('Waiting on a person').count()) > 0);

    await page.goto(`${consoleUrl}/reviews`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    const reviewRow = page.getByTestId(`review-row-${child}`);
    check('the child is in the Reviews queue', await reviewRow.waitFor({ timeout: 60_000 }).then(() => true, () => false));
    await reviewRow.click();
    const form = page.getByTestId('review-decision-form');
    await form.waitFor({ timeout: 30_000 });
    const decided = armed(page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/reviews/${child}/decision`), { timeout: 60_000 }));
    await form.getByRole('button', { name: 'Approve', exact: true }).click();
    const decision = await decided;
    check('approving it in Reviews is accepted (200, no step-up for a write)', decision?.status() === 200 && (await page.getByRole('dialog', { name: 'Confirm it is you' }).count()) === 0, decision?.status());

    // The parent conversation gets the outcome as a new message; the chat page shows it on the next load.
    let finishedText = false;
    for (let i = 0; i < 10 && !finishedText; i++) {
      await page.goto(conversation, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      finishedText = await page.getByText(`The dispute email workflow (${child}) finished`).first().waitFor({ timeout: 6_000 }).then(() => true, () => false);
    }
    check('back in the conversation, a message says the workflow finished', finishedText);
    // Non-vacuous half, last because setting the workflow live again does not restore the tool on HEAD: with it
    // paused the agent is not offered it, so a new conversation starts no child.
    check('dispute_email paused', (await setStatus('paused')) === 'paused');
    const before = await childRows();
    await ask(page, consoleUrl);
    const refused = await page.getByText('I could not find that.').last().waitFor({ timeout: 60_000 }).then(() => true, () => false);
    check('with the workflow paused the agent answers without it and starts nothing', refused && (await page.getByText('workflow__dispute_email').count()) === 0 && (await childRows()) === before, { refused, before });

    check('no page errors', errors.length === 0, errors);
  } finally {
    await setStatus('live').catch(() => undefined);
    await browser.close();
  }
});

finish();
