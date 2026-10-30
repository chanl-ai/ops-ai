// uc-139 the console works cases, ui layer: docs/usecases/console/cases-console.md (c-220). Platform sign-in; James
// works Operations' cases. Three cases are opened through the API: one due, one past its resolution deadline, one
// waiting on the customer (paused). Everything after that is clicked in the console.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const TAG = Math.random().toString(36).slice(2, 6);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const json = async (r) => {
  const body = await r.json();
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};
const at = (hours) => new Date(Date.now() + hours * 3_600_000).toISOString();

await withUiStack(
  async (consoleUrl) => {
    const J = { Authorization: `Bearer ${await tokenFor('j.richardson@harborpine.example')}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
    const open = (subject, extra) => fetch(`${agents}/v1/cases`, { method: 'POST', headers: J, body: JSON.stringify({ subject: `${subject} ${TAG}`, customer_name: 'Alex Martin', ...extra }) }).then(json);
    const due = await open('Card replacement', { priority: 'high', responseDueAt: at(2), resolutionDueAt: at(30) });
    const late = await open('Disputed wire', { priority: 'urgent', responseDueAt: at(-30), resolutionDueAt: at(-2) });
    const paused = await open('Missing statement', { priority: 'normal', responseDueAt: at(4), resolutionDueAt: at(48) });
    await json(await fetch(`${agents}/v1/cases/${paused.id}`, { method: 'PATCH', headers: J, body: JSON.stringify({ status: 'waiting_on_customer' }) }));

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('j.richardson@harborpine.example');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      await page.goto(`${consoleUrl}/cases`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const row = (c) => page.getByRole('row').filter({ hasText: c.id });
      await row(due).waitFor({ timeout: 120_000 });
      const state = async (c, which) => row(c).getByTestId(`case-${which}`).getAttribute('data-state');
      const shown = {
        customer: (await row(due).innerText()).includes('Alex Martin'),
        due: await state(due, 'resolution'),
        late: await state(late, 'resolution'),
        lateResponse: await state(late, 'response'),
        paused: await state(paused, 'resolution'),
        runs: await page.getByText('Runs across every workflow').count(),
      };
      check('1 Cases lists the team’s cases with customer and both deadlines: time left, overdue, paused; no runs', shown.customer && shown.due === 'due' && shown.late === 'overdue' && shown.lateResponse === 'overdue' && shown.paused === 'paused' && shown.runs === 0, shown);

      const asked = page.waitForRequest((r) => r.url().includes('/v1/cases?') && r.url().includes('overdue=true'), { timeout: 60_000 });
      await page.getByRole('tab', { name: 'Overdue' }).or(page.getByRole('button', { name: 'Overdue' })).first().click();
      const sent = (await asked).url();
      await page.waitForTimeout(500);
      const overdueRows = { late: await row(late).count(), due: await row(due).count(), paused: await row(paused).count() };
      check('2 the Overdue view asks the server for overdue cases and shows only the late one', sent.includes('overdue=true') && overdueRows.late === 1 && overdueRows.due === 0 && overdueRows.paused === 0, { sent, overdueRows });

      await page.goto(`${consoleUrl}/cases/${late.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('case-timeline').waitFor({ timeout: 120_000 });
      await page.getByTestId('case-priority').click();
      await page.getByRole('option', { name: 'High' }).click();
      await page.getByTestId('case-event').filter({ hasText: 'Changed the priority from Urgent to High' }).waitFor({ timeout: 30_000 });
      await page.getByLabel('Add a note').fill(`Called Alex ${TAG}`);
      await page.getByTestId('case-add-note').click();
      await page.getByTestId('case-event').filter({ hasText: `Called Alex ${TAG}` }).waitFor({ timeout: 30_000 });
      const server = await json(await fetch(`${agents}/v1/cases/${late.id}`, { headers: J }));
      check('3 a priority change and a note each land on the case’s timeline, on the page and the server', server.priority === 'high' && server.events.some((e) => e.kind === 'note' && e.detail.text === `Called Alex ${TAG}`) && server.events.some((e) => e.kind === 'field' && e.detail.field === 'priority'), { priority: server.priority, kinds: server.events.map((e) => e.kind) });

      await page.goto(`${consoleUrl}/cases?run=run_${TAG}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.waitForURL((u) => u.pathname === '/workflows/runs' && u.searchParams.get('run') === `run_${TAG}`, { timeout: 60_000 });
      check('4 an old run link on Cases lands on Workflows › Runs', new URL(page.url()).pathname === '/workflows/runs', page.url());

      // Workflows › Runs opens on the canvas workflows' runs (paged /v1/runs): a run started through the API is listed
      // with the status the server gives it, the Status filter counts it, and its row opens the run.
      const wid = `uc139_runs_${TAG}`.toLowerCase().replace(/[^a-z0-9_]/g, '_');
      const yaml = `schemaVersion: 2\nid: ${wid}\nname: Runs list (uc-139)\nnodes:\n  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request}\n  - {id: done, type: ops.flow.end, typeVersion: 1, name: Done, parameters: {outcome: done}}\nconnections:\n  - {from: {node: start, port: payload}, to: {node: done, port: in}}\n`;
      await json(await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: J, body: JSON.stringify({ yaml }) }));
      const started = await json(await fetch(`${agents}/v1/runs`, { method: 'POST', headers: J, body: JSON.stringify({ workflowId: wid, mode: 'test', input: {} }) }));
      // Settled first, so the status the page shows and the one read back are the same.
      for (let i = 0; i < 60 && ['queued', 'running'].includes((await json(await fetch(`${agents}/v1/runs/${started.runId}`, { headers: J }))).status); i++) await new Promise((r) => setTimeout(r, 1_000));
      await page.goto(`${consoleUrl}/workflows/runs`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const runRow = page.getByTestId(`runner-run-row-${started.runId}`);
      const listed = await runRow.waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const runNow = await json(await fetch(`${agents}/v1/runs/${started.runId}`, { headers: J }));
      const shownStatus = listed ? (await runRow.getByTestId('runner-run-status').innerText()).trim().toLowerCase() : '';
      // One list of the current engine's runs: no engine tabs (c-562).
      const engineTabs = await page.locator('[data-testid^=runs-kind-]').count();
      if (listed) await runRow.click();
      const opened = listed ? await page.waitForURL(`**/workflows/runs/${started.runId}`, { timeout: 60_000 }).then(() => true, () => false) : false;
      check('5 Workflows › Runs lists a workflow’s run with its status in one list, and the row opens it', listed && shownStatus === runNow.status.replace(/_/g, ' ') && engineTabs === 0 && opened, { runId: started.runId, listed, shownStatus, serverStatus: runNow.status, engineTabs, opened });
      // The search box asks the server (Cases is paged there) and finds a case by its subject.
      await page.goto(`${consoleUrl}/cases`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByRole('row').filter({ hasText: due.id }).waitFor({ timeout: 60_000 });
      const searched = page.waitForRequest((r) => r.url().includes('/v1/cases?') && /search=Disputed/.test(r.url()), { timeout: 30_000 });
      await page.getByPlaceholder(/Search/).first().fill(`Disputed wire ${TAG}`);
      const searchAsked = await searched.then(() => true, () => false);
      await page.waitForTimeout(1_500);
      const found = await page.locator('tbody tr').allInnerTexts();
      check('7 the case search goes to the server and finds only the matching case', searchAsked && found.length === 1 && found[0].includes('Disputed wire'), { searchAsked, found: found.map((t) => t.slice(0, 60)) });

      // The Overview's counts are the server's (GET /v1/overview, c-129), not sample data: the three cases above count.
      const counts = await json(await fetch(`${agents}/v1/overview`, { headers: J }));
      await page.goto(`${consoleUrl}/`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const casesCard = page.getByTestId('overview-cases');
      await casesCard.waitFor({ timeout: 60_000 });
      const shownCases = Number((await casesCard.innerText()).match(/Needs a person\s+(\d+)/)?.[1]);
      const shownReviews = Number((await page.getByTestId('overview-reviews').innerText()).match(/Waiting on review\s+(\d+)/)?.[1]);
      check('6 the Overview counts are the server’s: cases needing a person and reviews waiting', counts.cases.open >= 2 && shownCases === counts.cases.open && shownReviews === counts.openReviews, { server: counts.cases, openReviews: counts.openReviews, shownCases, shownReviews });
      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
