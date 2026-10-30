// uc-469 Staff start, follow and finish their work in chat, ui layer: docs/usecases/console/chat-home.md (c-469). The
// demo stack (platform sign-in, the fake model's rules, the core fake bank, a worker). James starts a card dispute,
// which waits for a provisional credit decision. Maya, an approver, signs in and lands on Chat's home beside the open
// sidebar (c-552), asks "What needs me today?", approves the task from its card (signing in again when the task asks for it),
// and sees the run move on in its run card; a reload shows the task decided, with no buttons. Screenshots go to
// evidenceDir('469', 'uc').
import { mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, FILES_PORT, PLATFORM_PORT, ROOT, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const files = `http://127.0.0.1:${FILES_PORT}`;
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const MAYA = 'm.okafor@harborpine.example';
const SHOTS = evidenceDir('469', 'uc');

const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });
const json = async (r) => (await r.json()).data;
const until = async (probe, ms = 180_000) => {
  for (const end = Date.now() + ms; Date.now() < end; await new Promise((r) => setTimeout(r, 1000))) {
    const got = await probe();
    if (got) return got;
  }
  return probe();
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
    await stack.startWorker({ OPS_FILES_URL: files });
    mkdirSync(SHOTS, { recursive: true });
    const james = as(await tokenFor(JAMES));
    const agentId = (await json(await fetch(`${agents}/v1/agents?pageSize=1`, { headers: james })))?.data?.[0]?.id;
    if (!agentId) throw new Error('setup: no agent in Operations');
    const dispute = JSON.parse(readFileSync(join(ROOT, 'scripts/sample-team/workflows/card_dispute_intake.json'), 'utf8').replaceAll('{agent:dispute}', agentId));
    const saved = await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: james, body: JSON.stringify({ definition: { ...dispute, id: 'uc469_dispute', name: 'Card dispute intake (uc-469)' } }) });
    if (saved.status >= 300) throw new Error(`setup: saving the dispute answered ${saved.status} ${(await saved.text()).slice(0, 300)}`);
    const values = { cardholder: 'Marcus Bell', ssnLast4: '4471', merchant: 'Coastal Air', amount: '1,240.00', postedOn: '2026-10-16', cardType: 'credit', reason: 'Quoted 640.00 CAD and charged 1,240.00 CAD.' };
    const started = await json(await fetch(`${agents}/v1/runs/start`, { method: 'POST', headers: james, body: JSON.stringify({ workflowId: 'uc469_dispute', mode: 'test', values }) }));
    const runId = started?.runId;
    const run = async () => json(await fetch(`${agents}/v1/runs/${runId}`, { headers: james }));
    const waiting = await until(async () => {
      const r = await run();
      return r?.waiting?.node === 'review' ? r : null;
    });
    check('0 setup: the dispute waits for the provisional credit decision', !!waiting, { runId, status: waiting?.status });

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, MAYA, PASSWORD, errors);
      page.setDefaultTimeout(60_000);
      const shot = async (name) => {
        for (const [width, scheme] of [[1280, 'light'], [375, 'light'], [1280, 'dark']]) {
          await page.emulateMedia({ colorScheme: scheme });
          await page.setViewportSize({ width, height: 900 });
          await page.waitForTimeout(800);
          await page.screenshot({ path: join(SHOTS, `${name}-${width}-${scheme}.png`) });
          if (width === 375 && (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth))) errors.push(`${name}: the page scrolls sideways at 375 px`);
        }
        await page.emulateMedia({ colorScheme: 'light' });
        await page.setViewportSize({ width: 1280, height: 900 });
      };

      await step('1 Maya lands on Chat’s home beside the open sidebar, with hints or starts', async () => {
        await page.getByTestId('home-start').waitFor({ timeout: 90_000 });
        await page.locator('[data-testid=home-hints], [data-testid=home-starts]').first().waitFor({ timeout: 60_000 });
        const sidebar = await page.locator('[data-slot=sidebar]').first().getAttribute('data-state');
        const offered = await page.locator('[data-testid^=home-hint-], [data-testid^=home-start-]').count();
        await shot('home');
        check('1 Maya lands on Chat’s home beside the open sidebar, with hints or starts', new URL(page.url()).pathname === '/chat' && sidebar === 'expanded' && offered >= 1 && offered <= 4, { at: page.url(), sidebar, offered });
      });

      // Other tasks Maya may decide (a seeded agent publish) can come first; the dispute's card is the one checked.
      const taskCard = page.locator('[data-testid=ops-call-cards] [data-record=task]').filter({ hasText: /Provisional credit/ }).first();
      await step('2 "What needs me today?" answers with the dispute’s Human Task as a card she can decide', async () => {
        // Her own work shows as hints when something waits, so she asks in the composer rather than through a start.
        await page.getByRole('textbox', { name: 'Message' }).first().fill('What needs me today?');
        await page.getByRole('textbox', { name: 'Message' }).first().press('Enter');
        await page.waitForURL((u) => /^\/chat\/[^/]+$/.test(u.pathname), { timeout: 90_000 });
        await taskCard.waitFor({ timeout: 120_000 });
        const text = (await taskCard.innerText()).replace(/\s+/g, ' ');
        const approve = await taskCard.getByTestId('ops-card-action-approve').count();
        await shot('task-card');
        check('2 "What needs me today?" answers with the dispute’s Human Task as a card she can decide', /Provisional credit/.test(text) && /Marcus Bell/.test(text) && approve === 1 && !/[{}]/.test(text), { text: text.slice(0, 300), approve });
        // The tool row reads as words ("My human tasks"), never the tool's id.
        const tools = (await page.getByTestId('chat-tool-call').allInnerTexts()).map((t) => t.split('\n')[0].trim());
        check('2b the chat names the tool it used in words, not its id', tools.length > 0 && tools.every((t) => !/_/.test(t)), tools);
      });

      await step('3 she approves from the card, signing in again if the task asks, and the card says so', async () => {
        await taskCard.getByTestId('ops-card-action-approve').click();
        const reauth = page.getByRole('dialog').filter({ hasText: /Confirm it/i });
        if (await reauth.waitFor({ timeout: 5_000 }).then(() => true, () => false)) {
          await reauth.getByLabel(/password/i).first().fill(PASSWORD);
          await reauth.getByRole('button', { name: /confirm|sign in|continue/i }).last().click();
        }
        await taskCard.getByTestId('ops-card-outcome').or(taskCard.getByTestId('ops-card-status').filter({ hasText: /Approved/ })).first().waitFor({ timeout: 60_000 });
        const moved = await until(async () => {
          const r = await run();
          return r && r.waiting?.node !== 'review' ? r : null;
        }, 120_000);
        check('3 she approves from the card, signing in again if the task asks, and the card says so', !!moved, { status: moved?.status, waiting: moved?.waiting?.node });
      });

      await step('4 the run card shows the run moved on past the decision', async () => {
        await page.getByPlaceholder(/Message /).fill(`What happened to run ${runId}?`);
        await page.keyboard.press('Enter');
        const runCard = page.locator('[data-testid=ops-call-cards] [data-record=run]').last();
        if (!(await runCard.waitFor({ timeout: 90_000 }).then(() => true, () => false))) {
          const said = (await page.locator('main').innerText()).replace(/\s+/g, ' ').slice(-500);
          return check('4 the run card shows the run moved on past the decision', false, { said });
        }
        const status = await runCard.getByTestId('ops-card-status').innerText();
        await shot('run-card');
        check('4 the run card shows the run moved on past the decision', !/Waiting for a person/.test(status), { status });
      });

      await step('5 after a reload the task card reads who decided it and offers no buttons', async () => {
        await page.reload({ waitUntil: 'domcontentloaded' });
        const card = page.locator('[data-testid=ops-call-cards] [data-record=task]').filter({ hasText: /Provisional credit/ }).first();
        await card.waitFor({ timeout: 90_000 });
        const status = await card.getByTestId('ops-card-status').innerText();
        const buttons = await card.locator('[data-testid^=ops-card-action-]').count();
        check('5 after a reload the task card reads who decided it and offers no buttons', /^Approved by /.test(status) && buttons === 0, { status, buttons });
      });

      await step('5b on a 13-inch laptop the conversation keeps its room beside the open sidebar', async () => {
        const middle = () => page.evaluate(() => Math.round(document.querySelector('[data-middle-column]')?.getBoundingClientRect().width ?? 0));
        const sidebar = () => page.locator('[data-slot=sidebar]').first().getAttribute('data-state');
        await page.setViewportSize({ width: 1024, height: 800 });
        await page.waitForTimeout(600);
        const at1024 = { middle: await middle(), sidebar: await sidebar(), rail: await page.getByTestId('chat-rail').count() };
        await page.goto(`${consoleUrl}/workflows/runs/${runId}`, { waitUntil: 'domcontentloaded' });
        await page.waitForTimeout(3000);
        const runFold = await sidebar();
        await page.setViewportSize({ width: 1280, height: 900 });
        check('5b on a 13-inch laptop the conversation keeps its room beside the open sidebar', at1024.middle >= 640 && at1024.sidebar === 'expanded' && at1024.rail === 0 && runFold === 'collapsed', { at1024, runFold });
      });

      await step('6 other pages keep the sidebar as it was', async () => {
        await page.goto(`${consoleUrl}/cases`, { waitUntil: 'domcontentloaded' });
        await page.waitForTimeout(1500);
        check('6 other pages keep the sidebar as it was', (await page.locator('[data-slot=sidebar]').first().getAttribute('data-state')) === 'expanded');
      });
      check('7 no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true, agentsEnv: { OPS_FILES_URL: files } },
);
finish();
