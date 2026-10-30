// uc-552 A person works from one chat, with every other page in one collapsible sidebar, ui layer:
// docs/usecases/console/chat-first.md (c-552). The demo stack (platform sign-in, the fake model, a worker). James starts
// a card dispute that waits for a decision, and it is assigned to Maya; a case is past its deadline. Maya signs in and
// lands on Chat with hints from her own work, starts a chat from one, finds it under Today in the sidebar, reads the
// Overview count and widgets from one request, folds the sidebar and a group and finds both remembered, loses her
// session mid-draft and gets it back after signing in again, then signs out and the draft is gone. Screenshots go to
// evidenceDir('552', 'uc').
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

import { AGENTS_PORT, FILES_PORT, PLATFORM_PORT, check, chromium, consoleSignIn, evidenceDir, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const files = `http://127.0.0.1:${FILES_PORT}`;
const PASSWORD = 'northfield-demo';
const JAMES = 'j.richardson@harborpine.example';
const MAYA = 'm.okafor@harborpine.example';
const SHOTS = evidenceDir('552', 'uc');
const DRAFT = 'Draft about the Coastal Air dispute';

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

// UC552_STEPS=1,3,3b runs only those steps (setup always runs), so codeloop verify can prove one acceptance line at a time.
const ONLY = process.env.UC552_STEPS?.split(',').map((x) => x.trim());

async function step(name, body) {
  if (ONLY && !ONLY.includes(name.split(' ')[0])) return;
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
    const maya = as(await tokenFor(MAYA));
    // A plain workflow that waits on a person, so the task exists without any model call.
    const yaml = ['schemaVersion: 2', 'id: uc552_refund', 'name: Refund over 100 (uc-552)', 'nodes:', '  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request}', '  - {id: review, type: ops.flow.humanReview, typeVersion: 1, name: Refund over 100, parameters: {title: Refund for Marcus Bell}}', '  - {id: approved, type: ops.flow.end, typeVersion: 1, name: Approved, parameters: {outcome: approved}}', '  - {id: rejected, type: ops.flow.end, typeVersion: 1, name: Rejected, parameters: {outcome: rejected}}', 'connections:', '  - {from: {node: start, port: payload}, to: {node: review, port: in}}', '  - {from: {node: review, port: approve}, to: {node: approved, port: in}}', '  - {from: {node: review, port: reject}, to: {node: rejected, port: in}}'].join('\n');
    const saved = await fetch(`${agents}/v1/workflows/definitions`, { method: 'POST', headers: james, body: JSON.stringify({ yaml }) });
    if (saved.status >= 300) throw new Error(`setup: saving the workflow answered ${saved.status} ${(await saved.text()).slice(0, 300)}`);
    const req = await json(await fetch(`${agents}/v1/workflows/definitions/uc552_refund/publish-requests`, { method: 'POST', headers: james, body: JSON.stringify({}) }));
    if (req?.status !== 'approved') await fetch(`${agents}/v1/publish-requests/${req?.id}/decision`, { method: 'POST', headers: maya, body: JSON.stringify({ decision: 'approved' }) });
    const runId = (await json(await fetch(`${agents}/v1/runs`, { method: 'POST', headers: james, body: JSON.stringify({ workflowId: 'uc552_refund', input: { amount: 250 } }) })))?.runId;
    const waiting = await until(async () => {
      const r = await json(await fetch(`${agents}/v1/runs/${runId}`, { headers: james }));
      return r?.status === 'waiting' ? r : null;
    });
    const reviewId = `${runId}:review:1`;
    const assignRes = await fetch(`${agents}/reviews/assign`, { method: 'POST', headers: maya, body: JSON.stringify({ ids: [reviewId], assignee: MAYA }) });
    const assigned = assignRes.status < 300 ? await json(assignRes) : { status: assignRes.status, body: (await assignRes.text()).slice(0, 300) };
    const made = await json(await fetch(`${agents}/v1/cases`, { method: 'POST', headers: james, body: JSON.stringify({ subject: 'Chargeback evidence for Marcus Bell', priority: 'high', customerId: 'C-2201', customerName: 'Marcus Bell' }) }));
    await fetch(`${agents}/v1/cases/${made.id}`, { method: 'PATCH', headers: james, body: JSON.stringify({ resolutionDueAt: '2020-01-01T00:00:00.000Z' }) });
    check('0 setup: a dispute task assigned to Maya and a case past its deadline', !!waiting && assigned?.updated?.length === 1 && !!made?.id, { runId, status: waiting?.status, reviewId, assigned, caseId: made?.id });

    const browser = await chromium.launch();
    const errors = [];
    try {
      const page = await consoleSignIn(browser, consoleUrl, MAYA, PASSWORD, errors);
      page.setDefaultTimeout(60_000);
      const overviewCalls = [];
      page.on('request', (r) => {
        const u = new URL(r.url());
        // API calls only: the console's own page prefetches (`?_rsc=`) share some of these paths.
        if (u.origin !== new URL(consoleUrl).origin && ['/v1/overview', '/reviews', '/v1/cases', '/v1/runs', '/v1/case-records'].some((p) => u.pathname.endsWith(p))) overviewCalls.push(u.pathname + u.search);
      });
      const shot = async (name) => {
        for (const [width, scheme] of [[1280, 'light'], [375, 'light'], [1280, 'dark']]) {
          await page.emulateMedia({ colorScheme: scheme });
          await page.setViewportSize({ width, height: 900 });
          await page.waitForTimeout(800);
          await page.screenshot({ path: join(SHOTS, `${name}-${width}-${scheme}.png`) });
          if (width === 375 && (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth))) errors.push(`${name}: the page scrolls sideways at 375 px`);
        }
        await page.emulateMedia({ colorScheme: 'light' });
        await page.setViewportSize({ width: 1440, height: 1000 });
      };
      const sidebar = page.locator('[data-slot=sidebar]').first();
      const groupOpen = async (label) => (await page.locator(`[data-nav-group="${label}"] [data-sidebar=group-label]`).first().getAttribute('aria-expanded')) === 'true';

      await step('1 Maya lands on Chat with hints from her own work', async () => {
        await page.getByTestId('home-hints').waitFor({ timeout: 90_000 });
        const url = new URL(page.url()).pathname;
        const task = await page.getByTestId('home-hint-task').innerText();
        const cases = await page.getByTestId('home-hint-case').count();
        const starts = await page.locator('[data-testid^=home-start-]').count();
        await shot('chat-home');
        check('1 Maya lands on Chat with hints from her own work', url === '/chat' && task.length > 0 && cases === 1 && starts === 0, { url, task, cases, starts });
      });

      await step('2 the sidebar holds New chat, Overview, Cases and Human Tasks with her count at the top, then the groups', async () => {
        // One count (c-562): on Human Tasks, the tasks waiting for her; Overview carries none.
        const count = Number(await page.getByTestId('sidebar-count-reviews').innerText());
        const overviewCount = await page.getByTestId('sidebar-overview-count').count();
        const mine = (await json(await fetch(`${agents}/reviews?view=mine&pageSize=1`, { headers: maya })))?.viewCounts?.mine;
        const top = (await page.locator('[data-sidebar=header] [data-sidebar=menu-button]').allInnerTexts()).map((t) => t.replace(/\s*\d+$/, '').trim()).filter(Boolean);
        const search = await page.getByTestId('sidebar-search').count();
        const groups = { chats: await groupOpen('Chats'), agents: await groupOpen('Agents'), dataHub: await groupOpen('Data Hub'), govern: await groupOpen('Govern'), work: await page.locator('[data-nav-group="Work"]').count() };
        const want = ['New chat', 'Overview', 'Cases', 'Human Tasks'];
        check('2 the sidebar holds New chat, Overview, Cases and Human Tasks with her count at the top, then the groups', count === mine && count >= 1 && overviewCount === 0 && want.every((w) => top.includes(w)) && search === 0 && groups.chats && !groups.agents && !groups.dataHub && !groups.govern && groups.work === 0, { count, overviewCount, mine, top, search, groups });
      });

      await step('2c the trail names no Work group, and the agent picker shows its name whole', async () => {
        // PM test 10-29: the trail began with a Work group the sidebar no longer shows, and the picker cut "Default" short.
        await page.goto(`${consoleUrl}/chat`, { waitUntil: 'load' });
        await page.getByTestId('home-agent').waitFor({ timeout: 30_000 });
        const seen = await page.evaluate(() => ({
          crumbs: [...document.querySelectorAll('header nav[aria-label=Breadcrumb] > span')].map((c) => (c.textContent ?? '').replace('/', '').trim()),
          picker: document.querySelector('[data-testid=home-agent] [data-slot=select-value]')?.textContent?.trim() ?? null,
        }));
        check('2c the trail names no Work group, and the agent picker shows its name whole', !seen.crumbs.includes('Work') && !!seen.picker && !/Default/.test(seen.picker), seen);
      });

      await step('3 a hint starts a chat, listed under Today in the sidebar', async () => {
        await page.getByTestId('home-hint-task').click();
        await page.waitForURL((u) => /^\/chat\/[^/]+$/.test(u.pathname) && u.pathname !== '/chat/conversations', { timeout: 60_000 });
        const id = new URL(page.url()).pathname.split('/')[2];
        const today = page.locator(`[data-chat-group="Today"] a[href="/chat/${id}"]`);
        await today.waitFor({ timeout: 30_000 });
        const active = await today.getAttribute('aria-current');
        await shot('chat-thread');
        check('3 a hint starts a chat, listed under Today in the sidebar', active === 'page', { id, active });
      });

      const threadIds = new Set();
      await step('3b "What needs me today?" shows the tasks Overview counts for her, and says the Human Tasks numbers', async () => {
        threadIds.add(new URL(page.url()).pathname.split('/')[2]);
        await page.getByTestId('sidebar-new-chat').click();
        await page.waitForURL((u) => u.pathname === '/chat');
        const box = page.getByRole('textbox', { name: 'Message' }).first();
        await box.fill('What needs me today?');
        await box.press('Enter');
        await page.waitForURL((u) => /^\/chat\/[^/]+$/.test(u.pathname) && u.pathname !== '/chat/conversations', { timeout: 60_000 });
        threadIds.add(new URL(page.url()).pathname.split('/')[2]);
        const cards = page.locator('[data-testid=ops-call-cards] [data-record=task]');
        await cards.first().waitFor({ timeout: 120_000 });
        await page.waitForTimeout(1500);
        const shown = await cards.count();
        const o = await json(await fetch(`${agents}/v1/overview`, { headers: maya }));
        const counts = (await json(await fetch(`${agents}/reviews?view=mine&pageSize=1`, { headers: maya })))?.viewCounts;
        await shot('needs-me');
        check('3b "What needs me today?" shows the tasks Overview counts for her, and says the Human Tasks numbers', shown === o.counts.waitingForMe && shown === counts.mine, { shown, overview: o.counts.waitingForMe, humanTasks: counts });
      });

      await step('3c after the sign-in page sends her to Chat, what she types starts a new chat', async () => {
        // The staging steps: signed in, open /login and press Enter; the console sends her to /chat.
        await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded' });
        await page.getByLabel('Work email').press('Enter').catch(() => undefined);
        await page.waitForURL((u) => u.pathname === '/chat', { timeout: 30_000 }).catch(() => page.goto(`${consoleUrl}/chat`, { waitUntil: 'domcontentloaded' }));
        await page.waitForTimeout(2500);
        const stillHome = new URL(page.url()).pathname;
        const box = page.getByRole('textbox', { name: 'Message' }).first();
        await box.fill('A fresh question about refunds');
        await box.press('Enter');
        await page.waitForURL((u) => /^\/chat\/[^/]+$/.test(u.pathname) && u.pathname !== '/chat/conversations', { timeout: 60_000 });
        const id = new URL(page.url()).pathname.split('/')[2];
        check('3c after the sign-in page sends her to Chat, what she types starts a new chat', stillHome === '/chat' && !threadIds.has(id), { stillHome, id, earlier: [...threadIds] });
      });

      await step('3d a chat opened for one agent starts on that agent, even when she sends before the agent list loads', async () => {
        // Chat home read the agent from the loaded list, so a message sent before it arrived started on the team's default.
        const list = (await json(await fetch(`${agents}/chat/agents`, { headers: maya }))) ?? [];
        const defaultId = (await json(await fetch(`${agents}/chat/default-agent`, { headers: maya })))?.agentId;
        const wanted = list.find((a) => a.id !== defaultId)?.id;
        let release;
        const held = new Promise((r) => (release = r));
        await page.route((u) => u.pathname.endsWith('/chat/agents'), async (route) => (await held, route.continue()));
        const created = page.waitForRequest((r) => r.method() === 'POST' && new URL(r.url()).pathname.endsWith('/chat/threads'), { timeout: 60_000 });
        await page.goto(`${consoleUrl}/chat?agent=${wanted}`, { waitUntil: 'domcontentloaded' });
        const box = page.getByRole('textbox', { name: 'Message' }).first();
        await box.fill('Which branch holds my card?');
        await box.press('Enter');
        await page.waitForTimeout(1500);
        release();
        await page.unroute((u) => u.pathname.endsWith('/chat/agents'));
        // Held until the list arrives, the message is still in the box: she sends it again, now on the agent she opened.
        if (new URL(page.url()).pathname === '/chat') {
          await page.getByTestId('home-agent').filter({ hasText: list.find((a) => a.id === wanted)?.name ?? '' }).waitFor({ timeout: 30_000 }).catch(() => undefined);
          await box.press('Enter').catch(() => undefined);
        }
        const sent = JSON.parse((await created).postData() ?? '{}');
        check('3d a chat opened for one agent starts on that agent, even when she sends before the agent list loads', !!wanted && sent.agentId === wanted, { wanted, defaultId, sent: sent.agentId });
      });

      await step('4 Overview shows the four widgets from one request, and a row opens its page', async () => {
        // A fresh load, so the Overview's own request is the one counted rather than the sidebar's cached answer.
        await page.goto(`${consoleUrl}/`, { waitUntil: 'domcontentloaded' });
        overviewCalls.length = 0;
        await page.reload({ waitUntil: 'domcontentloaded' });
        await page.waitForURL((u) => u.pathname === '/');
        await page.getByTestId('overview-tasks').waitFor();
        await page.waitForTimeout(1500);
        const counts = Object.fromEntries(await Promise.all(['tasks', 'runs', 'cases'].map(async (k) => [k, Number(await page.getByTestId(`overview-${k}-count`).innerText())])));
        const news = await page.getByTestId('overview-news').count();
        const calls = [...overviewCalls];
        await shot('overview');
        await page.getByTestId('overview-search').fill('Chargeback evidence');
        const filtered = { cases: await page.getByTestId('overview-cases-row').count(), tasks: await page.getByTestId('overview-tasks-row').count() };
        await page.getByTestId('overview-search').fill('');
        await page.getByTestId('overview-tasks-row').first().click();
        await page.waitForURL((u) => u.pathname === '/reviews');
        const opened = new URL(page.url()).searchParams.get('review');
        check('4 Overview shows the four widgets from one request, and a row opens its page', counts.tasks >= 1 && counts.runs >= 1 && counts.cases >= 1 && news === 1 && calls.some((c) => c.endsWith('/v1/overview') || c.includes('/v1/overview?')) && calls.every((c) => c.includes('/v1/overview')) && filtered.cases === 1 && filtered.tasks === 0 && !!opened, { counts, calls, filtered, opened });
      });

      await step('5 the folded sidebar and an opened group stay as she left them', async () => {
        await page.goto(`${consoleUrl}/chat`, { waitUntil: 'domcontentloaded' });
        await page.getByTestId('sidebar-new-chat').waitFor();
        await page.locator('[data-nav-group="Agents"] [data-sidebar=group-label]').first().click();
        await page.locator('[data-slot=sidebar-trigger]').first().click();
        await page.waitForTimeout(500);
        await page.reload({ waitUntil: 'domcontentloaded' });
        await page.getByTestId('sidebar-new-chat').waitFor();
        await page.waitForTimeout(1000);
        const folded = await sidebar.getAttribute('data-state');
        await page.locator('[data-slot=sidebar-trigger]').first().click();
        await page.waitForTimeout(500);
        const agentsOpen = await groupOpen('Agents');
        check('5 the folded sidebar and an opened group stay as she left them', folded === 'collapsed' && agentsOpen, { folded, agentsOpen });
      });

      await step('5b every sidebar row takes its own click at 1280 and 1440 px, open and folded', async () => {
        const hits = {};
        for (const w of [1280, 1440]) {
          await page.setViewportSize({ width: w, height: 900 });
          for (const folded of [false, true]) {
            await page.goto(`${consoleUrl}/cases`, { waitUntil: 'domcontentloaded' });
            await page.getByTestId('sidebar-new-chat').waitFor();
            const state = await sidebar.getAttribute('data-state');
            if ((state === 'collapsed') !== folded) await page.locator('[data-slot=sidebar-trigger]').first().click();
            await page.waitForTimeout(400);
            // A normal click: Playwright refuses when another element (an invisible group label) would take it.
            await page.getByTestId('sidebar-new-chat').click({ timeout: 5000 });
            await page.waitForURL((u) => u.pathname === '/chat', { timeout: 15_000 });
            await page.locator('[data-sidebar=header] a[href="/reviews"]').first().click({ timeout: 5000 });
            await page.waitForURL((u) => u.pathname === '/reviews', { timeout: 15_000 });
            hits[`${w}-${folded ? 'folded' : 'open'}`] = 'ok';
          }
        }
        // Leave the sidebar open, as the steps after expect.
        if ((await sidebar.getAttribute('data-state')) === 'collapsed') await page.locator('[data-slot=sidebar-trigger]').first().click();
        await page.setViewportSize({ width: 1440, height: 1000 });
        check('5b every sidebar row takes its own click at 1280 and 1440 px, open and folded', Object.keys(hits).length === 4, hits);
      });

      await step('6 an ended session keeps the page and her draft', async () => {
        await page.goto(`${consoleUrl}/chat`, { waitUntil: 'domcontentloaded' });
        const box = page.getByRole('textbox', { name: /message|ask/i }).first();
        await box.waitFor();
        await box.fill(DRAFT);
        // Another tab of the same browser loses the session (a refused refresh clears the shared session the same way).
        const other = await page.context().newPage();
        await other.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded' });
        await other.evaluate(() => window.localStorage.removeItem('ops-platform-session'));
        await other.close();
        await page.waitForTimeout(3000);
        if (!(await page.getByTestId('session-ended-dialog').count())) {
          await page.screenshot({ path: join(SHOTS, 'session-ended-missing.png') });
          throw new Error(`no dialog; at ${page.url()}, stored session ${await page.evaluate(() => !!window.localStorage.getItem('ops-platform-session'))}, page says ${(await page.locator('body').innerText()).replace(/\s+/g, ' ').slice(0, 200)}`);
        }
        const stayed = new URL(page.url()).pathname;
        await shot('session-ended');
        await page.getByTestId('session-sign-in-again').click();
        await page.waitForURL((u) => u.pathname.startsWith('/login'));
        await page.getByLabel('Work email').fill(MAYA);
        await page.getByLabel('Password').fill(PASSWORD);
        await page.getByTestId('login-submit').click();
        await page.waitForURL((u) => u.pathname === '/chat', { timeout: 60_000 });
        const back = page.getByRole('textbox', { name: /message|ask/i }).first();
        await back.waitFor();
        await page.waitForTimeout(800);
        const kept = await back.inputValue();
        check('6 an ended session keeps the page and her draft', stayed === '/chat' && kept === DRAFT, { stayed, kept });
      });

      await step('7 signing out forgets the draft', async () => {
        await page.locator('[data-sidebar=footer] [data-sidebar=menu-button]').first().click();
        await page.getByTestId('sign-out').click();
        await page.waitForURL((u) => u.pathname.startsWith('/login'));
        await page.getByLabel('Work email').fill(MAYA);
        await page.getByLabel('Password').fill(PASSWORD);
        await page.getByTestId('login-submit').click();
        await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
        await page.goto(`${consoleUrl}/chat`, { waitUntil: 'domcontentloaded' });
        const box = page.getByRole('textbox', { name: /message|ask/i }).first();
        await box.waitFor();
        await page.waitForTimeout(800);
        const left = await box.inputValue();
        check('7 signing out forgets the draft', left === '', { left });
      });

      await step('8 at 375 px the sidebar opens as a sheet', async () => {
        await page.setViewportSize({ width: 375, height: 800 });
        await page.goto(`${consoleUrl}/chat`, { waitUntil: 'domcontentloaded' });
        await page.locator('[data-slot=sidebar-trigger]').first().click();
        const sheet = page.locator('[data-slot=sidebar][data-mobile=true]');
        await sheet.waitFor({ timeout: 15_000 });
        const hasChats = await sheet.getByTestId('sidebar-chats').count();
        await page.screenshot({ path: join(SHOTS, 'sidebar-sheet-375-light.png') });
        const wide = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
        check('8 at 375 px the sidebar opens as a sheet', hasChats === 1 && !wide, { hasChats, wide });
        await page.setViewportSize({ width: 1440, height: 1000 });
      });

      check('9 no page errors', errors.length === 0, errors.slice(0, 3));
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true, agentsEnv: { OPS_FILES_URL: files } },
);
finish();
