// uc-460 A reviewer decides a Human Task beside a fixed decision panel, ui layer: docs/usecases/console/human-tasks-queue.md
// (c-460). The demo stack with a worker. James starts three card disputes: Marcus Bell's and Jordan Whitfield's end up
// on one case (Jordan's run is added to Marcus's case), Priya Natarajan's on its own and offered as options. By deadline alone
// Priya's task would sit between the other two; grouped by case it comes last. Maya, an approver, decides in the queue.
// Screenshots go to evidenceDir('460', 'uc').
import { mkdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, FILES_PORT, PLATFORM_PORT, ROOT, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const files = `http://127.0.0.1:${FILES_PORT}`;
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const MAYA = 'm.okafor@harborpine.example';
const SHOTS = evidenceDir('460', 'uc');

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

// After Decide, either Confirm it's you opens (filled in) or the queue moves past the task; under load either can take a
// while, so this waits for whichever comes first instead of guessing a short timeout.
async function confirmIfAsked(page, decided) {
  const reauth = page.getByRole('dialog').filter({ hasText: /Confirm it/i });
  const moved = page.waitForURL((u) => u.searchParams.get('review') !== decided, { timeout: 90_000 }).then(() => 'moved');
  const asked = reauth.waitFor({ timeout: 90_000 }).then(() => 'asked');
  if ((await Promise.race([moved, asked]).catch(() => 'neither')) === 'asked') {
    await reauth.getByLabel(/password/i).first().fill(PASSWORD);
    await reauth.getByRole('button', { name: /confirm|sign in|continue/i }).last().click();
  }
}

await withUiStack(
  async (consoleUrl, stack) => {
    await stack.startWorker({ OPS_FILES_URL: files });
    mkdirSync(SHOTS, { recursive: true });
    const james = as(await tokenFor(JAMES));
    const maya = as(await tokenFor(MAYA));
    const agentId = (await json(await fetch(`${agents}/v1/agents?pageSize=1`, { headers: james })))?.data?.[0]?.id;
    if (!agentId) throw new Error('setup: no agent in Operations');
    const base = JSON.parse(readFileSync(join(ROOT, 'scripts/sample-team/workflows/card_dispute_intake.json'), 'utf8').replaceAll('{agent:dispute}', agentId));
    // The same dispute with its review offering options; an option named after a port takes that port, so the edges hold.
    const withOptions = structuredClone(base);
    withOptions.nodes.find((n) => n.id === 'review').parameters.options = [
      { name: 'approve', label: 'Give the provisional credit' },
      { name: 'reject', label: 'Decline the credit' },
    ];
    for (const [id, name, def] of [['uc460_dispute', 'Card dispute intake (uc-460)', base], ['uc460_options', 'Card dispute with options (uc-460)', withOptions]]) {
      const saved = await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: james, body: JSON.stringify({ definition: { ...def, id, name } }) });
      if (saved.status >= 300) throw new Error(`setup: saving ${id} answered ${saved.status} ${(await saved.text()).slice(0, 300)}`);
    }
    const start = async (workflowId, cardholder, amount, ssnLast4) =>
      (await json(await fetch(`${agents}/v1/runs/start`, { method: 'POST', headers: james, body: JSON.stringify({ workflowId, mode: 'test', values: { cardholder, ssnLast4, merchant: 'Coastal Air', amount, postedOn: '2026-10-16', cardType: 'credit', reason: 'Charged more than quoted.' } }) })))?.runId;
    const waitingAt = async (runId) =>
      until(async () => {
        const r = await json(await fetch(`${agents}/v1/runs/${runId}`, { headers: james }));
        return r?.waiting?.node === 'review' ? r : null;
      });
    // Made one after another so Marcus's is due first, Priya's second and Tom's last.
    const marcus = await start('uc460_dispute', 'Marcus Bell', '1,240.00', '4471');
    const wm = await waitingAt(marcus);
    const priya = await start('uc460_options', 'Priya Natarajan', '300.00', '9032');
    const wp = await waitingAt(priya);
    const tom = await start('uc460_dispute', 'Jordan Whitfield', '5,000.00', '5555');
    const wt = await waitingAt(tom);
    const state = async (runId) => {
      const r = await json(await fetch(`${agents}/v1/runs/${runId}`, { headers: james }));
      return { runId, status: r?.status, waiting: r?.waiting?.node, outcome: r?.outcome };
    };
    if (!wm || !wp || !wt) console.log('setup runs', JSON.stringify([await state(marcus), await state(priya), await state(tom)]));
    const caseOf = async (runId) => (await json(await fetch(`${agents}/reviews/${encodeURIComponent(`${runId}:review:1`)}`, { headers: maya })))?.caseId;
    const caseA = await caseOf(marcus);
    const linked = await fetch(`${agents}/v1/cases/${caseA}/events`, { method: 'POST', headers: james, body: JSON.stringify({ kind: 'run', ref: tom }) });
    const ids = { marcus: `${marcus}:review:1`, priya: `${priya}:review:1`, tom: `${tom}:review:1` };
    const listed = (await json(await fetch(`${agents}/reviews?view=open&group=case&pageSize=200`, { headers: maya })))?.data ?? [];
    const order = listed.map((r) => r.id).filter((i) => Object.values(ids).includes(i));
    check('0 the route orders the three by case: Marcus and Tom together, then Priya, with case titles', linked.status < 300 && order.join() === [ids.marcus, ids.tom, ids.priya].join() && !!listed.find((r) => r.id === ids.marcus)?.caseTitle, { linked: linked.status, order, caseA });

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, MAYA, PASSWORD, errors);
      page.setDefaultTimeout(60_000);
      await page.setViewportSize({ width: 1280, height: 800 });
      const sidebar = () => page.locator('[data-slot=sidebar]').first().getAttribute('data-state');
      const shot = async (name) => {
        for (const [w, h, scheme] of [[1440, 900, 'light'], [1280, 800, 'light'], [1024, 768, 'light'], [375, 800, 'light'], [1280, 800, 'dark']]) {
          await page.emulateMedia({ colorScheme: scheme });
          await page.setViewportSize({ width: w, height: h });
          await page.waitForTimeout(700);
          await page.screenshot({ path: join(SHOTS, `${name}-${w}-${scheme}.png`) });
          if (w === 375 && (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth))) errors.push(`${name}: scrolls sideways at 375 px`);
        }
        await page.emulateMedia({ colorScheme: 'light' });
        await page.setViewportSize({ width: 1280, height: 800 });
      };

      await step('1 the queue lists the tasks under their cases, Marcus before Tom before Priya, with the open task beside it', async () => {
        await page.goto(`${consoleUrl}/reviews`, { waitUntil: 'domcontentloaded' });
        await page.getByTestId('queue-list').waitFor({ timeout: 120_000 });
        await page.getByTestId('decision-panel').waitFor();
        const shown = await page.evaluate((want) => [...document.querySelectorAll('[data-testid^=queue-item-]')].map((e) => e.dataset.testid.replace('queue-item-', '')).filter((i) => want.includes(i)), Object.values(ids));
        const header = await page.getByTestId(`queue-case-${caseA}`).innerText();
        await shot('queue');
        check('1 the queue lists the tasks under their cases, Marcus before Tom before Priya, with the open task beside it', shown.join() === [ids.marcus, ids.tom, ids.priya].join() && header.trim().length > 4 && header.trim() !== 'Case' && (await sidebar()) === 'collapsed', { shown, header, sidebar: await sidebar() });
        // A seeded publish request reads as asked by Setup, never by an internal "seed".
        const queueText = await page.getByTestId('queue-list').innerText();
        check('1b no task in the queue says it was requested by seed', !/Requested by (the tools-service )?seed/.test(queueText), queueText.match(/Requested by [^\n]*/g));
      });

      await step('2 Decide stays in view while the panel scrolls', async () => {
        await page.getByTestId(`queue-item-${ids.marcus}`).click();
        await page.waitForURL((u) => u.searchParams.get('review') === ids.marcus);
        const body = page.getByTestId('decision-body');
        await body.evaluate((e) => e.scrollTo(0, e.scrollHeight));
        const box = await page.getByTestId('decide').boundingBox();
        await body.evaluate((e) => e.scrollTo(0, 0));
        const box2 = await page.getByTestId('decide').boundingBox();
        const inView = (b) => !!b && b.y >= 0 && b.y + b.height <= 800;
        check('2 Decide stays in view while the panel scrolls', inView(box) && inView(box2) && box?.y === box2?.y, { box, box2 });
      });

      await step('3 approving Marcus asks to confirm it is you when the task says so, records it, and opens Tom (same case) next', async () => {
        await page.getByTestId('option-approve').click();
        await page.getByTestId('decide').click();
        await confirmIfAsked(page, ids.marcus);
        await page.waitForURL((u) => u.searchParams.get('review') === ids.tom, { timeout: 60_000 });
        const moved = await until(async () => {
          const r = await json(await fetch(`${agents}/v1/runs/${marcus}`, { headers: james }));
          return r && r.waiting?.node !== 'review' ? r : null;
        }, 120_000);
        check('3 approving Marcus asks to confirm it is you when the task says so, records it, and opens Tom (same case) next', !!moved, { status: moved?.status });
      });

      await step('4 Priya’s option step shows each option with Decide named after the choice, and decides', async () => {
        await page.getByTestId(`queue-item-${ids.priya}`).click();
        await page.waitForURL((u) => u.searchParams.get('review') === ids.priya);
        const form = page.locator('[data-testid=option-decision-form][data-layout=panel]');
        await form.waitFor();
        const firstLabel = (await page.getByTestId('decide').innerText()).trim();
        await page.getByTestId('option-reject').click();
        const label = (await page.getByTestId('decide').innerText()).trim();
        const optionName = (await page.getByTestId('option-reject').locator('span.font-medium').first().innerText()).trim();
        await page.getByTestId('option-reason').fill('Merchant refund already on the way');
        await shot('option-step');
        await page.getByTestId('decide').click();
        await confirmIfAsked(page, ids.priya);
        const ended = await until(async () => {
          const r = await json(await fetch(`${agents}/v1/runs/${priya}`, { headers: james }));
          return r && r.waiting?.node !== 'review' ? r : null;
        }, 120_000);
        check('4 Priya’s option step shows each option with Decide named after the choice, and decides', label === optionName && label !== firstLabel && !!ended, { firstLabel, label, optionName, status: ended?.status });
      });

      await step('5 reassigning Tom gives the task to someone else', async () => {
        await page.goto(`${consoleUrl}/reviews?review=${encodeURIComponent(ids.tom)}`, { waitUntil: 'domcontentloaded' });
        await page.getByTestId('reassign').click();
        const to = page.locator('[data-testid^=reassign-to-]').first();
        const who = (await to.innerText()).trim();
        await to.click();
        const r = await until(async () => {
          const got = await json(await fetch(`${agents}/reviews/${encodeURIComponent(ids.tom)}`, { headers: maya }));
          return got?.assignee === who ? got : null;
        }, 120_000);
        check('5 reassigning Tom gives the task to someone else', !!r, { who, assignee: r?.assignee });
      });

      await step('6 the old task address and a decided task open here', async () => {
        await page.goto(`${consoleUrl}/reviews/${encodeURIComponent(ids.tom)}`, { waitUntil: 'domcontentloaded' });
        await page.waitForURL((u) => u.pathname === '/reviews' && u.searchParams.get('review') === ids.tom, { timeout: 60_000 });
        await page.goto(`${consoleUrl}/reviews?review=${encodeURIComponent(ids.marcus)}`, { waitUntil: 'domcontentloaded' });
        const decided = await page.getByTestId('task-decided').innerText({ timeout: 60_000 });
        check('6 the old task address and a decided task open here', /^Decided by /.test(decided.trim()), { decided });
      });

      await step('7 All tasks keeps the table with its views', async () => {
        await page.goto(`${consoleUrl}/reviews/all`, { waitUntil: 'domcontentloaded' });
        await page.locator('[data-testid^=review-row-]').first().waitFor({ timeout: 60_000 });
        check('7 All tasks keeps the table with its views', (await page.getByRole('tab', { name: /Resolved/ }).count()) > 0);
      });

      await step('8 leaving Human Tasks puts the sidebar back', async () => {
        await page.goto(`${consoleUrl}/cases`, { waitUntil: 'domcontentloaded' });
        await page.waitForTimeout(1500);
        check('8 leaving Human Tasks puts the sidebar back', (await sidebar()) === 'expanded');
      });
      check('9 no page errors and no sideways scroll at 375 px', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true, agentsEnv: { OPS_FILES_URL: files } },
);
finish();
