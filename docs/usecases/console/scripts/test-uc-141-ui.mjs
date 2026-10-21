// uc-141 the one Activity page, ui layer: docs/usecases/console/activity-page.md (c-242). Platform sign-in; James works
// in Operations. A canvas workflow is saved and run through the API; everything after that is read in the console.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const TAG = Math.random().toString(36).slice(2, 6);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const json = async (r) => {
  const body = await r.json();
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};

await withUiStack(
  async (consoleUrl) => {
    const J = { Authorization: `Bearer ${await tokenFor('j.richardson@harborpine.example')}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
    const wid = `uc141_${TAG}`;
    const name = `Activity check ${TAG}`;
    const yaml = `schemaVersion: 2\nid: ${wid}\nname: ${name}\nnodes:\n  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request}\n  - {id: done, type: ops.flow.end, typeVersion: 1, name: Done, parameters: {outcome: done}}\nconnections:\n  - {from: {node: start, port: payload}, to: {node: done, port: in}}\n`;
    await json(await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: J, body: JSON.stringify({ yaml }) }));
    const started = await json(await fetch(`${agents}/v1/runs`, { method: 'POST', headers: J, body: JSON.stringify({ workflowId: wid, mode: 'test', input: {} }) }));
    for (let i = 0; i < 60 && ['queued', 'running'].includes((await json(await fetch(`${agents}/v1/runs/${started.runId}`, { headers: J }))).status); i++) await new Promise((r) => setTimeout(r, 1_000));

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      page.setDefaultTimeout(60_000);
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('j.richardson@harborpine.example');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      // 1. Govern › Activity opens the one list, and the run is a row named for its workflow with its outcome.
      await page.goto(`${consoleUrl}/activity`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const row = page.getByTestId(`activity-row-workflow_run:${started.runId}`);
      const listed = await row.waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const text = listed ? await row.innerText() : '';
      const server = await json(await fetch(`${agents}/v1/runs/${started.runId}`, { headers: J }));
      const outcome = listed ? (await row.getByTestId('activity-status').innerText()).trim().toLowerCase() : '';
      check('1 Activity lists the run by its workflow name, kind and outcome', listed && text.includes(name) && /Workflow run/.test(text) && outcome === server.status.replace(/_/g, ' '), { text: text.slice(0, 160), outcome, server: server.status });

      // 2. The Kind filter asks the server for that kind.
      await page.locator('main').getByRole('button', { name: 'Kind', exact: true }).click();
      const asked = page.waitForRequest((r) => r.url().includes('/v1/activity?') && r.url().includes('kind=workflow_run'), { timeout: 30_000 });
      await page.getByRole('option', { name: /Workflow run/ }).click();
      // The filter applies its choices when its Apply button is pressed.
      await page.getByTestId('facet-apply').click();
      const sent = await asked.then(() => true, () => false);
      check('2 the Kind filter is sent to the server', sent);

      // 3. A workflow's View activity link shows only that workflow's rows, and says so with a way back.
      await page.goto(`${consoleUrl}/activity?source=workflow:${wid}&name=${encodeURIComponent(name)}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId(`activity-row-workflow_run:${started.runId}`).waitFor({ timeout: 60_000 });
      const all = await page.locator('[data-testid^="activity-row-"]').allInnerTexts();
      const chip = await page.getByTestId('activity-source').innerText();
      check('3 a source link shows only that source, named, with Show all', all.length > 0 && all.every((t) => t.includes(name)) && chip.includes(name) && /Show all/.test(chip), { rows: all.length, chip });

      // 4. A row opens its run.
      await page.getByTestId(`activity-row-workflow_run:${started.runId}`).click();
      const opened = await page.waitForURL(`**/workflows/runs/${started.runId}`, { timeout: 60_000 }).then(() => true, () => false);
      check('4 a run row opens the run page', opened, page.url());

      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
