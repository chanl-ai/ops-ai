// uc-228 Starting a run, and reading a run and a case, ui layer: docs/usecases/console/start-run-and-records.md (c-266).
// Platform sign-in; James works in Operations. UC228_SHOTS names a folder to keep each surface's screenshot in, for a
// side-by-side comparison before and after a refactor.
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const JAMES = 'j.richardson@harborpine.example';
const SHOTS = process.env.UC228_SHOTS;
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const json = async (r) => {
  const body = await r.json();
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};

async function step(name, body) {
  try {
    await body();
  } catch (e) {
    check(name, false, String(e).slice(0, 400));
  }
}

await withUiStack(
  async (consoleUrl, stack) => {
    const J = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
    const made = await json(await fetch(`${agents}/v1/cases`, { method: 'POST', headers: J, body: JSON.stringify({ subject: 'Card charge not recognised', customer_name: 'Alex Martin' }) }));
    const wid = 'uc228_card_dispute';
    const yaml = `schemaVersion: 2\nid: ${wid}\nname: Card dispute intake\nnodes:\n  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request}\n  - {id: done, type: ops.flow.end, typeVersion: 1, name: Done, parameters: {outcome: resolved}}\nconnections:\n  - {from: {node: start, port: payload}, to: {node: done, port: in}}\n`;
    await json(await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: J, body: JSON.stringify({ yaml }) }));
    const started = await json(await fetch(`${agents}/v1/runs`, { method: 'POST', headers: J, body: JSON.stringify({ workflowId: wid, mode: 'test', input: {} }) }));

    const browser = await chromium.launch();
    const errors = [];
    if (SHOTS) mkdirSync(SHOTS, { recursive: true });
    const shot = async (page, name) => SHOTS && page.screenshot({ path: join(SHOTS, `${name}.png`), animations: 'disabled' });
    try {
      const signIn = async (width) => {
        const page = await (await browser.newContext({ viewport: { width, height: 900 } })).newPage();
        page.setDefaultTimeout(60_000);
        page.on('pageerror', (e) => errors.push(e.message));
        await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByLabel('Email').fill(JAMES);
        await page.getByLabel('Password').fill('northfield-demo');
        await page.getByRole('button', { name: /^Sign in/ }).first().click();
        await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
        return page;
      };
      const page = await signIn(1280);

      await step('1 Start run on Workflows offers every workflow and no agent, searched on the server, then opens the chosen workflow\'s own form', async () => {
        const total = (await json(await fetch(`${agents}/v1/workflows?page=1&pageSize=1`, { headers: J }))).pagination.total;
        await page.goto(`${consoleUrl}/workflows`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByRole('button', { name: 'Start run' }).first().click({ timeout: 120_000 });
        const dialog = page.getByRole('dialog', { name: 'Start a run' });
        await dialog.waitFor();
        await dialog.getByTestId('start-run-workflow').getByRole('button', { name: 'Choose a workflow' }).click();
        const list = page.locator('[cmdk-list]');
        await page.getByRole('option').first().waitFor({ timeout: 30_000 });
        // The list pages on scroll; scrolling to the end loads every page the server has.
        let offered = 0;
        for (let i = 0; i < 12; i++) {
          offered = await page.getByRole('option').count();
          if (offered >= total) break;
          await list.evaluate((el) => el.scrollTo(0, el.scrollHeight));
          await page.waitForTimeout(600);
        }
        await shot(page, 'start-run-list-1280');
        const search = page.locator('[cmdk-input]');
        await search.fill('Card dispute intake');
        const found = await page.getByRole('option', { name: /Card dispute intake/ }).waitFor({ timeout: 30_000 }).then(() => true, () => false);
        // An agent is talked to in Chat, so the picker never offers one.
        await search.fill('Wire Fraud Sentinel');
        await page.waitForTimeout(1200);
        const agentsOffered = await page.getByRole('option', { name: /Wire Fraud Sentinel/ }).count();
        await search.fill('Card dispute intake');
        await page.getByRole('option', { name: /Card dispute intake/ }).click();
        await dialog.getByTestId('start-run-next').click();
        const form = await page.getByRole('dialog', { name: /Start a run of Card dispute intake/ }).waitFor({ timeout: 30_000 }).then(() => true, () => false);
        check(
          '1 Start run on Workflows offers every workflow and no agent, searched on the server, then opens the chosen workflow\'s own form',
          total > 0 && offered === total && found && agentsOffered === 0 && form,
          { total, offered, found, agentsOffered, form },
        );
        await page.keyboard.press('Escape');
      });

      await step('2 Test run in the editor names the workflow and offers a test run', async () => {
        await page.goto(`${consoleUrl}/workflows/definitions/${wid}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('definition-start-run').click({ timeout: 120_000 });
        const dialog = page.getByRole('dialog', { name: /Start a run of Card dispute intake/ });
        await dialog.waitFor();
        await page.waitForTimeout(500);
        const test = await dialog.getByRole('radio', { name: /Test run/ }).isChecked();
        await shot(page, 'start-run-editor-1280');
        check('2 Test run in the editor names the workflow and offers a test run', test, { test });
        await page.keyboard.press('Escape');
      });

      await step('3 the run page shows the workflow, the run and its status', async () => {
        await page.goto(`${consoleUrl}/workflows/runs/${started.runId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const title = page.getByTestId('page-title').first();
        await title.waitFor();
        await page.waitForTimeout(1500);
        const body = await page.locator('main').innerText();
        await shot(page, 'run-1280');
        // The rail is narrow: a long id reads in full on hover and copies in one click.
        const rail = page.getByTestId('run-attributes');
        const defTitle = await rail.getByRole('link', { name: /uc228_card_dispute/ }).getAttribute('title');
        const copies = await rail.getByRole('button', { name: /^Copy (workflow id|digest)/ }).count();
        check('3b the run rail shows long values in full on hover and copies the ids', defTitle === 'uc228_card_dispute v1' && copies === 2, { defTitle, copies });
        check('3 the run page shows the workflow, the run and its status', body.includes('Card dispute intake') && body.includes(started.runId) && /Queued|Running|Succeeded|Completed|Failed/.test(body), { body: body.slice(0, 300) });
      });

      await step('4 the case page shows its subject and customer', async () => {
        await page.goto(`${consoleUrl}/cases/${made.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('page-title').first().waitFor();
        await page.waitForTimeout(1500);
        const body = await page.locator('main').innerText();
        await shot(page, 'case-1280');
        check('4 the case page shows its subject and customer', body.includes('Card charge not recognised') && body.includes('Alex Martin'), { body: body.slice(0, 200) });
      });

      await step('5 at 400 px the run and the case do not scroll sideways', async () => {
        const phone = await signIn(400);
        const widths = {};
        for (const [name, path] of [['run', `/workflows/runs/${started.runId}`], ['case', `/cases/${made.id}`]]) {
          await phone.goto(`${consoleUrl}${path}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
          await phone.getByTestId('page-title').first().waitFor();
          await phone.waitForTimeout(1500);
          widths[name] = await phone.evaluate(() => document.documentElement.scrollWidth);
          await shot(phone, `${name}-400`);
        }
        check('5 at 400 px the run and the case do not scroll sideways', Object.values(widths).every((w) => w <= 400), widths);
      });

      await step('6 a case a workflow opened shows the fields it gave the case, dates formatted and numbers grouped', async () => {
        // The queued run's page is open when a worker starts: it reaches its end on the page, with no reload.
        await page.goto(`${consoleUrl}/workflows/runs/${started.runId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByTestId('run-status').waitFor();
        const before = (await page.getByTestId('run-status').innerText()).trim();
        await stack.startWorker();
        const finished = await page.waitForFunction(() => /succeeded|completed/i.test(document.querySelector('[data-testid="run-status"]')?.textContent ?? ''), null, { timeout: 90_000 }).then(() => true, () => false);
        const took = await page.getByTestId('run-step-took').allInnerTexts();
        check('5b a run page left open moves to the run’s end without a reload, with each step’s time', /queued/i.test(before) && finished && took.length > 0 && took.every((t) => t !== 'Running' && t !== '—'), { before, finished, took });
        // A workflow opens the case with fields, as the levy workflows do.
        const fid = 'uc228_open_case';
        const fy = `schemaVersion: 2\nid: ${fid}\nname: Open a levy case\nnodes:\n  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request}\n  - id: open\n    type: ops.action.openCase\n    typeVersion: 1\n    name: Open the case\n    parameters:\n      subject: Tax levy for Riley Fixture\n      customerName: Riley Fixture\n      fields: {taxpayer: Riley Fixture, amountDue: 1250.5, respondBy: '2026-11-02', daysToRespond: 14, document: TEST012.pdf, documentFileId: fil_uc228doc}\n  - {id: done, type: ops.flow.end, typeVersion: 1, name: Done, parameters: {outcome: opened}}\nconnections:\n  - {from: {node: start, port: payload}, to: {node: open, port: in}}\n  - {from: {node: open, port: opened}, to: {node: done, port: in}}\n  - {from: {node: open, port: error}, to: {node: done, port: in}}\n`;
        await json(await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: J, body: JSON.stringify({ yaml: fy }) }));
        const run = await json(await fetch(`${agents}/v1/runs`, { method: 'POST', headers: J, body: JSON.stringify({ workflowId: fid, mode: 'test', input: {} }) }));
        let caseId;
        let last;
        for (let i = 0; i < 60 && !caseId; i++) {
          last = await json(await fetch(`${agents}/v1/runs/${run.runId}`, { headers: J }));
          caseId = last.steps?.find((x) => (x.node ?? x.nodeId) === 'open')?.output?.caseId;
          if (!caseId) await new Promise((res) => setTimeout(res, 1000));
        }
        if (!caseId) throw new Error(`the workflow opened no case: ${JSON.stringify({ status: last?.status, error: last?.error, steps: last?.steps }).slice(0, 600)}`);
        await page.goto(`${consoleUrl}/cases/${caseId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const card = page.getByTestId('case-fields');
        await card.waitFor({ timeout: 60_000 });
        const amount = await card.getByTestId('case-field-amountDue').innerText();
        const due = await card.getByTestId('case-field-respondBy').innerText();
        const document = await card.getByTestId('case-field-document').innerText();
        const fileLink = await card.getByTestId('case-field-documentFileId').getByRole('link').getAttribute('href');
        await shot(page, 'case-fields-1280');
        check('6 a case a workflow opened shows the fields it gave the case, dates formatted and numbers grouped', /1,250\.5/.test(amount) && !/2026-11-02/.test(due) && /Nov/.test(due) && /TEST012\.pdf/.test(document) && fileLink === '/files/fil_uc228doc', { amount, due, document, fileLink });
      });

      await step('7 the runs list says how each run ended', async () => {
        let ended = null;
        for (let i = 0; i < 60 && !ended?.finishedAt; i++) {
          ended = await json(await fetch(`${agents}/v1/runs/${started.runId}`, { headers: J }));
          if (!ended.finishedAt) await new Promise((r) => setTimeout(r, 1000));
        }
        await page.goto(`${consoleUrl}/workflows/runs`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        const cell = page.getByTestId(`run-outcome-${started.runId}`);
        const shown = await cell.waitFor({ timeout: 60_000 }).then(() => true, () => false);
        const text = shown ? (await cell.innerText()).trim() : '';
        const want = (ended.outcome ?? '').replace(/[_-]+/g, ' ').toLowerCase();
        check('7 the runs list says how each run ended', shown && !!want && text.toLowerCase() === want, { text, outcome: ended.outcome });
      });

      check('no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);
finish();
