// uc-005 a pause survives a restart, ui layer: docs/usecases/agents-service/pause-survives-restart.md. The dispute
// workflow pauses for review on one stack; that stack stops, and a second one starts on the same database, so nothing
// of the run is left in any process. On the second stack's console the run is still a Cases row waiting on a person,
// Priya, the team's admin, opens the review from All tasks and approves it, and the row finishes. Platform sign-in,
// scripted model.
import { check, chromium, consoleSignIn, finish, withUiStack } from '@ops-ai/usecase-runner/harness';
import { JAMES, PASSWORD, PRIYA, agents, as } from '../../lib/workflow_ui.mjs';

// First process: the run pauses at its review and the review id is noted.
const paused = await withUiStack(async () => {
  const json = await as(JAMES);
  const emails = (await import('../../../../services/agents-service/tests/fixtures/seed/dispute_emails.json', { with: { type: 'json' } })).default;
  const tid = (await (await fetch(`${agents}/v1/threads`, { method: 'POST', headers: json, body: JSON.stringify({ graph: 'complex_workflow', metadata: {} }) })).json()).data.threadId;
  const ran = await fetch(`${agents}/v1/threads/${tid}/runs/stream`, { method: 'POST', headers: json, body: JSON.stringify({ input: { email: emails[1] } }) });
  const interrupted = ran.status === 200 && (await ran.text()).includes('"interrupted"');
  const state = (await (await fetch(`${agents}/v1/threads/${tid}/state`, { headers: json })).json()).data ?? {};
  return { tid, interrupted, reviewId: state.interrupt?.payload?.review_id };
}, { platform: true });
check('1 the first process paused the run for review and noted its review id', paused.interrupted && !!paused.reviewId, paused);

// Second process on the same database: everything it shows comes from PostgreSQL.
await withUiStack(async (consoleUrl) => {
  const { tid } = paused;
  const J = await as(JAMES);
  const after = (await (await fetch(`${agents}/v1/threads/${tid}/state`, { headers: J })).json()).data ?? {};
  check('2 the new process holds the same review', after.interrupt?.payload?.review_id === paused.reviewId, after.interrupt?.payload);
  const browser = await chromium.launch();
  try {
    const errors = [];
    // A reviewer or admin of the team decides a review; Priya is the team's admin.
    const page = await consoleSignIn(browser, consoleUrl, PRIYA, PASSWORD, errors);
    await page.goto(`${consoleUrl}/workflows/runs?kind=graph`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    const row = page.getByTestId(`run-row-${tid}`);
    const listed = await row.waitFor({ timeout: 120_000 }).then(() => true, () => false);
    check('3 after the restart the run is a Cases row waiting on a person', listed && (await row.getByText('Waiting on a person').count()) > 0);

    // All tasks lists every review; its row opens the task in Human Tasks, as a person reaches it.
    await page.goto(`${consoleUrl}/reviews/all`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    const reviewRow = page.getByTestId(`review-row-${tid}`);
    const queued = await reviewRow.waitFor({ timeout: 60_000 }).then(() => true, () => false);
    let decided = false;
    if (queued) {
      await reviewRow.click();
      await page.waitForURL((u) => u.pathname === '/reviews' && u.searchParams.get('review') === tid, { timeout: 30_000 });
      await page.getByTestId('decision-panel').waitFor({ timeout: 30_000 });
      const answered = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/reviews/${tid}/decision`), { timeout: 60_000 }).then((r) => r.status(), () => 0);
      // A conversation's review keeps its own form: Approve names the reply it sends.
      await page.getByTestId('review-approve').click();
      decided = (await answered) === 200;
    }
    check('4 the review is listed in All tasks, opens in Human Tasks and is approved there', queued && decided, { queued, decided });

    const runs = (await (await fetch(`${agents}/v1/threads/${tid}/runs`, { headers: J })).json()).data ?? [];
    const last = runs[runs.length - 1] ?? {};
    await page.goto(`${consoleUrl}/workflows/runs?kind=graph`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
    await page.getByText(/^Done today/).first().click();
    const doneRow = page.getByTestId(`run-row-${tid}`);
    const finished = await doneRow.waitFor({ timeout: 60_000 }).then(() => true, () => false);
    check(
      '5 the row finishes, and the reply was sent once after the restart',
      finished && (await doneRow.getByText('Done', { exact: true }).count()) > 0 && (last.nodes ?? []).filter((n) => n === 'send_reply').length === 1,
      last.nodes,
    );
    check('no page errors', errors.length === 0, errors);
  } finally {
    await browser.close();
  }
}, { platform: true });

finish();
