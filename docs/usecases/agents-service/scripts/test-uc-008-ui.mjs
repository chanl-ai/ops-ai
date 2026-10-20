// uc-008 a paused workflow is decided from the console, ui layer:
// docs/usecases/agents-service/decide-paused-workflow.md. Headless Chromium against a console whose Cases runs and
// Reviews call the agents service on the scripted model; every other area is the mock.
import { AGENTS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;

async function startDispute() {
  const emails = (await import('../../../../services/agents-service/tests/fixtures/seed/dispute_emails.json', { with: { type: 'json' } })).default;
  const created = await fetch(`${agents}/v1/threads`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ graph: 'complex_workflow', metadata: {} }) });
  const tid = (await created.json()).data.threadId;
  const run = await fetch(`${agents}/v1/threads/${tid}/runs/stream`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ input: { email: emails[0] } }) });
  const text = await run.text();
  return { tid, paused: run.status === 200 && text.includes('"interrupted"') };
}

await withUiStack(async (consoleUrl) => {
  const { tid, paused } = await startDispute();
  check('dispute run started and paused for review', paused, tid);
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    const decisions = [];
    page.on('response', (r) => {
      if (r.request().method() === 'POST' && r.url().endsWith(`/reviews/${tid}/decision`)) decisions.push(r.status());
    });

    await page.goto(`${consoleUrl}/workflows/runs?kind=graph`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    const row = page.getByTestId(`run-row-${tid}`);
    const listed = await row.waitFor({ timeout: 120_000 }).then(() => true, () => false);
    check('the run is a Cases row under Needs a person', listed);
    check('the row says Waiting on a person', listed && (await row.getByText('Waiting on a person').count()) > 0);

    await row.click();
    const trace = page.getByTestId('run-trace');
    await trace.waitFor({ timeout: 30_000 }).catch(() => undefined);
    const labels = await trace.locator('li').allInnerTexts().catch(() => []);
    const extracts = labels.filter((l) => l.startsWith('Extract')).length;
    check('run sheet lists the node steps (extract three times)', extracts === 3, labels);
    check('the review step is waiting', (await trace.getByLabel('waiting').count()) === 1, labels);

    await page.goto(`${consoleUrl}/reviews`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    const reviewRow = page.getByTestId(`review-row-${tid}`);
    check('the review is in the Reviews queue', await reviewRow.waitFor({ timeout: 60_000 }).then(() => true, () => false));
    await reviewRow.click();
    const form = page.getByTestId('review-decision-form');
    await form.waitFor({ timeout: 30_000 });
    const answered = page.waitForResponse((r) => r.url().endsWith(`/reviews/${tid}/decision`), { timeout: 60_000 }).then(() => true, () => false);
    await form.getByRole('button', { name: 'Approve', exact: true }).click();
    const stepUp = page.getByRole('dialog', { name: 'Confirm it is you' });
    // Non-vacuous pair: the decision reaches the API once with no step-up (a write), and the row then finishes.
    const sent = await answered;
    check('no step-up asked for a write review', (await stepUp.count()) === 0);
    check('one decision sent and accepted', sent && decisions.length === 1 && decisions[0] === 200, decisions);

    await page.goto(`${consoleUrl}/workflows/runs?kind=graph`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByText(/^Done today/).first().click();
    const doneRow = page.getByTestId(`run-row-${tid}`);
    const finished = await doneRow.waitFor({ timeout: 60_000 }).then(() => true, () => false);
    check('the row finished (Done today, Done)', finished && (await doneRow.getByText('Done', { exact: true }).count()) > 0);
    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
});

finish();
