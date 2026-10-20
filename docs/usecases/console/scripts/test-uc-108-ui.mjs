// uc-108 a chat shows when its budget is spent and the person continues, ui layer:
// docs/usecases/console/chat-budget-continue.md. Signed in through platform-service. An agent whose conversations may
// make one model call: James's second message pauses on a budget card with the server's numbers, he continues and the
// turn answers; Priya, a team admin, raises the budget on her own chat; the wrong person is refused on each action.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const NAME = `Budget Desk ${Math.random().toString(36).slice(2, 6)}`;
const armed = (p) => (p.catch(() => undefined), p);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });

async function signIn(browser, consoleUrl, email, errors) {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  page.on('pageerror', (e) => errors.push(`${email}: ${e.message}`));
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('northfield-demo');
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

async function send(page, text) {
  const box = page.getByRole('textbox', { name: 'Message' });
  await box.fill(text);
  const sent = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 }));
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  const res = await sent;
  await Promise.race([res?.finished().catch(() => undefined), new Promise((r) => setTimeout(r, 60_000))]);
}

await withUiStack(
  async (consoleUrl) => {
    const J = as(await tokenFor('j.richardson@northfieldbank.com'));
    const P = as(await tokenFor('p.shah@northfieldbank.com'));
    const M = as(await tokenFor('m.okafor@northfieldbank.com'));
    // An agent whose conversations may make one model call, published (dev auto-approve).
    const made = await (await fetch(`${agents}/v1/agents`, { method: 'POST', headers: J, body: JSON.stringify({ name: NAME, role: 'Answers account questions' }) })).json();
    if (!made.data) throw new Error(`setup: create agent: ${JSON.stringify(made).slice(0, 300)}`);
    const guardrails = { ...made.data.guardrails, maxModelCallsPerConversation: 1 };
    const saved = await (await fetch(`${agents}/v1/agents/${made.data.id}`, { method: 'PATCH', headers: J, body: JSON.stringify({ guardrails, note: 'one call per conversation' }) })).json();
    if (!saved.data) throw new Error(`setup: caps: ${JSON.stringify(saved).slice(0, 300)}`);
    const pub = await fetch(`${agents}/v1/agents/${made.data.id}/publish-requests`, { method: 'POST', headers: J, body: JSON.stringify({ version: saved.data.version, note: 'first' }) });
    if (!pub.ok) throw new Error(`setup: publish answered ${pub.status}: ${await pub.text()}`);
    const thread = async (H) => (await (await fetch(`${agents}/chat/threads`, { method: 'POST', headers: H, body: JSON.stringify({ agentId: made.data.id, kbIds: [] }) })).json()).data.id;
    const jt = await thread(J);
    const pt = await thread(P);

    const browser = await chromium.launch();
    const errors = [];
    try {
      // James: the first answer spends the one call; the next message pauses on the budget card.
      const james = await signIn(browser, consoleUrl, 'j.richardson@northfieldbank.com', errors);
      await james.goto(`${consoleUrl}/chat/${jt}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByRole('textbox', { name: 'Message' }).waitFor({ timeout: 120_000 });
      await send(james, 'What are your opening hours?');
      await send(james, 'And on weekends?');
      const card = james.getByTestId('budget-card');
      const shown = await card.waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const text = shown ? await card.innerText() : '';
      const ledger = (await (await fetch(`${agents}/chat/threads/${jt}`, { headers: J })).json()).data.messages.find((m) => m.budget)?.budget;
      const paused = { shown, text, ledger, raise: await james.getByTestId('budget-raise').count(), composer: await james.getByText('paused on its budget').count() };
      check('a spent budget shows a card with the server’s numbers, Continue for the owner and no Raise for a builder', shown && !!ledger && text.includes(`${ledger.spent} of ${ledger.cap} model calls`) && paused.raise === 0 && paused.composer > 0, paused);

      // The wrong person on each action is refused by the server.
      const otherContinue = await fetch(`${agents}/chat/threads/${jt}/budget`, { method: 'POST', headers: M, body: JSON.stringify({ action: 'continue' }) });
      const builderRaise = await fetch(`${agents}/chat/threads/${jt}/budget`, { method: 'POST', headers: J, body: JSON.stringify({ action: 'raise', maxCalls: 10 }) });
      check('someone else cannot continue James’s chat, and a builder cannot raise', otherContinue.status === 403 && builderRaise.status === 403, { otherContinue: otherContinue.status, builderRaise: builderRaise.status });

      // Continue: the paused turn answers and the card says who continued.
      const answered = armed(james.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/chat/threads/${jt}/budget`), { timeout: 120_000 }));
      await card.getByTestId('budget-continue').click();
      const continued = (await answered)?.status();
      const done = await james.getByTestId('budget-answered').waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const after = (await (await fetch(`${agents}/chat/threads/${jt}`, { headers: J })).json()).data.messages;
      const replied = after.slice(after.findIndex((m) => m.budget) + 1).some((m) => m.role === 'assistant' && m.content);
      check('Continue resumes the turn: it answers, the card says it was continued, and the box takes messages again', continued === 200 && done && replied && (await james.getByText('paused on its budget').count()) === 0, { continued, done, replied });

      // Priya, a team admin, raises the budget on her own chat.
      const priya = await signIn(browser, consoleUrl, 'p.shah@northfieldbank.com', errors);
      await priya.goto(`${consoleUrl}/chat/${pt}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await priya.getByRole('textbox', { name: 'Message' }).waitFor({ timeout: 120_000 });
      await send(priya, 'What are your opening hours?');
      await send(priya, 'And on weekends?');
      await priya.getByTestId('budget-raise').click({ timeout: 60_000 });
      await priya.getByLabel('New model-call cap').fill('5');
      const raisedRes = armed(priya.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/chat/threads/${pt}/budget`), { timeout: 120_000 }));
      await priya.getByTestId('budget-raise-save').click();
      const raised = (await raisedRes)?.status();
      const note = await priya.getByTestId('budget-answered').innerText({ timeout: 60_000 }).catch(() => '');
      check('a team admin raises the budget on the card and the turn continues', raised === 200 && /raised to 5/.test(note), { raised, note });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
