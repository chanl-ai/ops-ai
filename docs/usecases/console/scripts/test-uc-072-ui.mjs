// uc-072 a banker asks, gets a cited answer, and decides a drafted write inside the thread, ui layer:
// docs/usecases/console/chat-act-in-thread.md. Scripted model only; signed in through platform-service as Maya. The
// Wire Fraud Sentinel answers from its knowledge with a citation, drafts a wire hold that waits for approval; Maya
// approves it in the thread after a step-up and the thread resumes; a second hold she rejects with a reason.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const MAYA = 'm.okafor@northfieldbank.com';
const PASSWORD = 'northfield-demo';
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);

await withUiStack(
  async (consoleUrl) => {
    const M = as(await tokenFor(MAYA));
    const created = await (await fetch(`${agents}/chat/threads`, { method: 'POST', headers: M, body: JSON.stringify({ agentId: 'ag_fraud', kbIds: ['kb_people'] }) })).json();
    if (!created.data) throw new Error(`setup: thread create answered ${JSON.stringify(created).slice(0, 300)}`);
    const thread = created.data.id;

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      const decisions = [];
      page.on('pageerror', (e) => errors.push(e.message));
      const calls = [];
      page.on('response', (r) => /step-up|reauth|auth\//.test(r.url()) && calls.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`));
      // The card decides through Reviews' own route (M4), not a chat-only path.
      page.on('response', (r) => r.request().method() === 'POST' && /\/reviews\/[^/]+\/decision$/.test(r.url()) && decisions.push(r.status()));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(MAYA);
      await page.getByLabel('Password').fill(PASSWORD);
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      await page.goto(`${consoleUrl}/chat/${thread}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const box = page.getByRole('textbox', { name: 'Message' });
      await box.waitFor({ timeout: 120_000 });
      const send = async (text) => {
        await box.fill(text);
        const sent = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 }));
        await page.getByRole('button', { name: 'Send', exact: true }).click();
        const res = await sent;
        await Promise.race([res?.finished().catch(() => undefined), new Promise((r) => setTimeout(r, 60_000))]);
      };

      await send('What is the daily wire limit for a personal account?');
      const answered = await page.getByText(/\$25,000 online/).last().waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const marker = page.getByRole('button', { name: /^Citation 1: / });
      await marker.click({ timeout: 15_000 }).catch(() => undefined);
      const opened = await page.getByRole('dialog').getByText(/limit/i).first().waitFor({ timeout: 10_000 }).then(() => true, () => false);
      check('the answer streams in with a citation that opens on its passage', answered && opened, { answered, opened });
      await page.keyboard.press('Escape');

      await send('Place a 24-hour hold on wire W-88213');
      const card = page.locator('section').filter({ hasText: 'W-88213' }).last();
      const approve = card.getByRole('button', { name: 'Approve', exact: true });
      const drafted = await approve.waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const waitingOn = drafted ? await card.getByTestId('approval-waiting-on').innerText().catch(() => '') : '';
      check('the drafted hold waits for approval in the thread, naming the wire and whom it waits on', drafted && /^Waiting on \S/.test(waitingOn) && !/^Waiting for approval$/.test(waitingOn), { drafted, waitingOn });
      await approve.click();
      const confirmRun = page.getByRole('button', { name: 'Approve and run' });
      if (await confirmRun.waitFor({ timeout: 3_000 }).then(() => true, () => false)) await confirmRun.click();
      const stepUp = page.getByRole('dialog', { name: 'Confirm it is you' });
      const asked = await stepUp.waitFor({ timeout: 15_000 }).then(() => true, () => false);
      // Non-vacuous: a console that skipped the step-up would post the decision before this point.
      check('Maya is asked to confirm it is her before anything is sent', asked && decisions.length === 0, { asked, decisions });
      await page.locator('#reauth-secret').fill(PASSWORD);
      if (await page.locator('#reauth-code').count()) await page.locator('#reauth-code').fill('123456');
      await page.getByTestId('reauth-submit').click();
      const resumed = await page.getByText('The hold is in place.').last().waitFor({ timeout: 60_000 }).then(() => true, () => false);
      check('one decision is accepted after the step-up and the thread resumes and reports', decisions.length === 1 && decisions[0] === 200 && resumed, { decisions, resumed, calls, dialog: resumed ? undefined : (await stepUp.innerText().catch(() => 'closed')).slice(0, 300) });

      // The decided review records the step-up it was approved under (a fingerprint, never the token), and the review
      // detail in Reviews says so.
      const decided = ((await (await fetch(`${agents}/reviews?page=1&pageSize=50&view=resolved`, { headers: M })).json()).data?.data ?? []).find((r) => r.origin?.kind === 'chat' && r.origin.threadId === thread);
      await page.goto(`${consoleUrl}/reviews?review=${decided?.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const stepUpLine = page.getByTestId('review-step-up');
      const shown = await stepUpLine.waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const text = shown ? await stepUpLine.innerText() : '';
      check('the decided review shows it was approved with a step-up and its fingerprint', !!decided?.stepUpRef && shown && text.includes('Approved with step-up') && text.includes(decided.stepUpRef), { id: decided?.id, stepUpRef: decided?.stepUpRef, text });
      await page.goto(`${consoleUrl}/chat/${thread}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await box.waitFor({ timeout: 120_000 });

      // A failed step-up leaves the dialog open over the thread; close it so the reject path can run.
      if (await stepUp.isVisible().catch(() => false)) await stepUp.getByRole('button', { name: 'Cancel' }).click();

      await send('Place a 24-hour hold on wire W-77001');
      const second = page.locator('section').filter({ hasText: 'W-77001' }).last();
      await second.getByRole('button', { name: 'Reject' }).click({ timeout: 60_000 });
      const dialog = page.getByRole('dialog', { name: /^Reject / });
      await dialog.getByLabel('Reason').fill('The customer confirmed the payee by phone');
      await dialog.getByRole('button', { name: 'Reject' }).click();
      const told = await page.getByText('Understood. The hold was rejected, so the wire continues.').last().waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const reason = (await second.getByText('Reason: The customer confirmed the payee by phone').count()) === 1;
      check('a rejected hold keeps its reason on the card and the agent says the wire continues', told && reason, { told, reason, decisions });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
