// uc-087 a banker finds, starts and continues chats, ui layer: docs/usecases/console/chat-find-start-continue.md.
// Scripted model only; signed in through platform-service as James. Slow and failed replies are made in the browser
// (a held or refused request), never in the console or the services, so the states shown are the real ones.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack, replyDone } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const JAMES = 'j.richardson@harborpine.example';
const LONG = 'What is the daily wire limit for a personal account opened by a minor in Saskatchewan?';
const RAIL_PAGE = 30;
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const armed = (p) => (p.catch(() => undefined), p);
const MESSAGES = /\/chat\/threads\/[^/]+\/messages$/;
// A reply streams; wait for its end, but never past 60 s, so a stream that stays open cannot hang the run.
const settled = async (p) => {
  const res = await p;
  await replyDone(res, 60_000);
};

await withUiStack(
  async (consoleUrl) => {
    const J = { Authorization: `Bearer ${await tokenFor(JAMES)}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
    const thread = async (id) => (await (await fetch(`${agents}/chat/threads/${id}`, { headers: J })).json()).data;
    const assistants = async (id) => (await thread(id)).messages.filter((m) => m.role === 'assistant').map((m) => m.id);

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(JAMES);
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      // Empty: nobody has chatted yet. The chats column starts folded on the chat home; Show chats opens it.
      await page.goto(`${consoleUrl}/chat`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('chat-list-open').click({ timeout: 60_000 });
      const column = page.getByTestId('chat-list-column');
      const empty = await column.getByText('No chats yet. Ask something to start one.').waitFor({ timeout: 60_000 }).then(() => true, () => false);
      check('with no chats the chats column says so', empty);

      // Start from the chat home: the first message creates the thread and is sent.
      const agent = (await (await fetch(`${agents}/chat/agents`, { headers: J })).json()).data[0];
      const prompt = 'What are your opening hours?';
      const home = page.getByTestId('home-start');
      const sent = armed(page.waitForResponse((r) => r.request().method() === 'POST' && MESSAGES.test(r.url()), { timeout: 120_000 }));
      await home.getByRole('textbox', { name: 'Message' }).fill(prompt);
      await home.getByRole('button', { name: 'Send', exact: true }).click({ timeout: 60_000 });
      await settled(sent);
      await page.waitForURL(/\/chat\/th_/, { timeout: 60_000 }).catch(() => undefined);
      const tid = new URL(page.url()).pathname.split('/').pop();
      const regenerate = page.getByRole('button', { name: 'Regenerate' });
      const answered = await regenerate.waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const stored = tid?.startsWith('th_') ? await thread(tid) : null;
      check('a first message from the chat home starts a thread and is answered', answered && stored?.messages[0]?.content === prompt && stored.messages.length === 2, { prompt, tid, messages: stored?.messages.map((m) => `${m.role}: ${m.content.slice(0, 60)}`) });

      // Regenerate: the answer is replaced, not added.
      const before = await assistants(tid);
      const again = armed(page.waitForResponse((r) => r.request().method() === 'POST' && MESSAGES.test(r.url()), { timeout: 60_000 }));
      await regenerate.click();
      await settled(again);
      await regenerate.waitFor({ timeout: 60_000 }).catch(() => undefined);
      const after = await assistants(tid);
      check('regenerate replaces the answer with a new one', after.length === 1 && before.length === 1 && after[0] !== before[0], { before, after });

      // Slow: the request is held; the thread shows the agent working and offers Stop, which hands the composer back.
      let held = 0;
      await page.route(MESSAGES, async (route) => {
        held += 1;
        await new Promise((r) => setTimeout(r, 6_000));
        await route.continue().catch(() => undefined);
      });
      const box = page.getByRole('textbox', { name: 'Message' });
      await box.fill('Is anyone there?');
      await page.getByRole('button', { name: 'Send', exact: true }).click();
      const stop = page.getByRole('button', { name: 'Stop', exact: true });
      const working = await stop.waitFor({ timeout: 3_000 }).then(() => true, () => false);
      const thinking = await page.getByText(/Thinking…|Searching .*…/).first().isVisible().catch(() => false);
      if (working) await stop.click();
      const back = await page.getByRole('button', { name: 'Send', exact: true }).waitFor({ timeout: 5_000 }).then(() => true, () => false);
      await new Promise((r) => setTimeout(r, 7_000));
      const afterStop = (await thread(tid)).messages.length;
      check('a slow reply shows the agent working with Stop, and Stop hands the composer back with nothing sent', held === 1 && working && thinking && back && afterStop === 2, { held, working, thinking, back, afterStop });
      await page.unroute(MESSAGES);

      // Error: the send is refused; the typed message is kept with Retry, and Retry sends it.
      await page.route(MESSAGES, (route) => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ success: false, error: { code: 'model_unavailable', message: 'No model is configured.', status: 503 } }) }));
      await box.fill('Check my limits');
      await page.getByRole('button', { name: 'Send', exact: true }).click();
      const banner = page.getByText('Your message wasn’t sent');
      const refused = await banner.waitFor({ timeout: 15_000 }).then(() => true, () => false);
      const reason = refused ? await page.getByText('No model is configured.').isVisible() : false;
      await page.unroute(MESSAGES);
      const retried = armed(page.waitForResponse((r) => r.request().method() === 'POST' && MESSAGES.test(r.url()) && r.status() === 200, { timeout: 60_000 }));
      if (refused) await page.getByRole('button', { name: 'Retry', exact: true }).click();
      await settled(retried);
      await page.getByText('Check my limits').last().waitFor({ timeout: 30_000 }).catch(() => undefined);
      const afterRetry = await thread(tid);
      check('a refused send shows why and keeps the message, and Retry sends it', refused && reason && afterRetry.messages.length === 4 && afterRetry.messages[2].content === 'Check my limits', { refused, reason, messages: afterRetry.messages.length });

      // The chats column pages by cursor as it scrolls, and search runs on the server: the oldest thread, past the first page, is found by
      // words in its question that its title does not show.
      const make = async () => (await (await fetch(`${agents}/chat/threads`, { method: 'POST', headers: J, body: JSON.stringify({ agentId: agent.id, kbIds: [] }) })).json()).data.id;
      const oldest = await make();
      await (await fetch(`${agents}/chat/threads/${oldest}/messages`, { method: 'POST', headers: { ...J, Accept: 'text/event-stream' }, body: JSON.stringify({ content: LONG }) })).text();
      for (let i = 0; i < RAIL_PAGE + 2; i++) await make();
      const total = (await (await fetch(`${agents}/chat/threads?pageSize=1`, { headers: J })).json()).data.pagination.total;
      const searches = [];
      page.on('request', (r) => r.url().includes('/chat/threads?') && new URL(r.url()).searchParams.get('search') && searches.push(new URL(r.url()).searchParams.get('search')));
      await page.goto(`${consoleUrl}/chat`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      // Opened once, the column stays open in this browser.
      const ROWS = '[data-testid="chat-list-column"] a[href^="/chat/th_"]';
      const rows = page.locator(ROWS);
      await rows.first().waitFor({ timeout: 60_000 });
      await page.waitForFunction((sel) => document.querySelectorAll(sel).length > 0, ROWS);
      const first = await rows.count();
      const more = column.getByTestId('chat-list-more');
      const offered = (await more.count()) > 0;
      await column.getByRole('textbox', { name: 'Search chats' }).fill('saskatchewan');
      await page.waitForFunction((sel) => document.querySelectorAll(sel).length === 1, ROWS, { timeout: 15_000 }).catch(() => undefined);
      const found = await rows.evaluateAll((els) => els.map((e) => e.getAttribute('href')));
      const title = (await thread(oldest)).title;
      check('search runs on the server and finds a question its title does not show, past the first page', found.length === 1 && found[0] === `/chat/${oldest}` && !/saskatchewan/i.test(title) && searches.includes('saskatchewan'), { found, title, searches, first });
      await column.getByRole('textbox', { name: 'Search chats' }).fill('');
      await page.waitForFunction(([sel, n]) => document.querySelectorAll(sel).length === n, [ROWS, RAIL_PAGE], { timeout: 15_000 }).catch(() => undefined);
      // Scrolling the end of the list into view reads the next page.
      for (let i = 0; i < 5 && (await rows.count()) < total; i++) {
        await more.scrollIntoViewIfNeeded().catch(() => undefined);
        await page.waitForTimeout(1_000);
      }
      await page.waitForFunction(([sel, n]) => document.querySelectorAll(sel).length === n, [ROWS, total], { timeout: 15_000 }).catch(() => undefined);
      const all = await rows.evaluateAll((els) => els.map((e) => e.getAttribute('href')));
      check('the chats column shows a page of chats and reads the next as it scrolls, with no chat twice', first === RAIL_PAGE && offered && all.length === total && new Set(all).size === total && (await more.count()) === 0, { first, offered, shown: all.length, unique: new Set(all).size, total });

      // Error: the list cannot load; the column says so on a button that tries again, and it loads.
      await page.route('**/chat/threads?*', (route) => (route.request().method() === 'GET' ? route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ success: false, error: { code: 'internal', message: 'Something went wrong.', status: 500 } }) }) : route.continue()));
      await page.reload({ waitUntil: 'domcontentloaded' });
      const failed = await column.getByText(/Couldn’t load chats/).waitFor({ timeout: 60_000 }).then(() => true, () => false);
      await page.unroute('**/chat/threads?*');
      if (failed) await column.getByRole('button', { name: 'Couldn’t load chats. Try again' }).click();
      const recovered = await rows.first().waitFor({ timeout: 30_000 }).then(() => true, () => false);
      check('a list that cannot load says so on a button that tries again, and it loads', failed && recovered, { failed, recovered });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
