// uc-057 a write held in a chat is listed in Reviews and approved there, ui layer:
// docs/usecases/console/chat-holds-in-reviews.md. Scripted model only; signed in through platform-service. James
// asks an agent for a write in chat; Maya approves it from Reviews; the call reaches the fake bank.
import { AGENTS_PORT, PLATFORM_PORT, TOOLS_PORT, approveToolReview, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const agentsUrl = `http://127.0.0.1:${AGENTS_PORT}`;
const TAG = Math.random().toString(36).slice(2, 6);
const WRITE = `place_hold_${TAG}`;
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const as = (token, team) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
const json = async (r) => {
  const body = await r.json();
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};

await withUiStack(
  async (consoleUrl, stack) => {
    const P = as(await tokenFor('p.shah@northfieldbank.com'), 'team_ops');
    const J = as(await tokenFor('j.richardson@northfieldbank.com'), 'team_ops');
    const N = as(await tokenFor('n.petrov@northfieldbank.com'), 'team_security');
    // Only a Security admin changes the egress allow-list (c-079), so Sam lists the host.
    const S = as(await tokenFor('s.adeyemi@northfieldbank.com'), 'team_security');
    await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: S, body: JSON.stringify({ value: stack.bank.host, note: 'uc-057' }) });
    await fetch(`${tools}/v1/egress/ranges`, { method: 'POST', headers: S, body: JSON.stringify({ value: stack.bank.range, note: 'uc-057' }) });
    // A published module with one write, granted to a new agent.
    const mid = (await json(await fetch(`${tools}/v1/tool-modules/blank`, { method: 'POST', headers: J, body: JSON.stringify({ displayName: `Holds ${TAG}`, name: `uc057-${TAG}`, type: 'http' }) }))).id;
    await fetch(`${tools}/v1/tool-modules/${mid}/operations`, { method: 'POST', headers: J, body: JSON.stringify({ name: WRITE, description: 'Place a hold', access: 'write', method: 'POST', url: `https://${stack.bank.host}/v1/accounts/{accountId}/holds` }) });
    await json(await fetch(`${tools}/v1/tool-modules/${mid}/reviews`, { method: 'POST', headers: J, body: JSON.stringify({ note: 'uc-057' }) }));
    await approveToolReview(mid, N);
    await new Promise((r) => setTimeout(r, 31_000)); // agents-service keeps each tenant's tool list for 30 seconds
    const agent = await json(await fetch(`${agentsUrl}/v1/agents`, { method: 'POST', headers: J, body: JSON.stringify({ name: `Holds desk ${TAG}`, role: 'Places holds' }) }));
    const granted = await fetch(`${agentsUrl}/v1/agents/${agent.id}`, { method: 'PATCH', headers: J, body: JSON.stringify({ toolIds: [WRITE] }) });
    if (!granted.ok) throw new Error(`setup: granting ${WRITE} answered ${granted.status}: ${await granted.text()}`);
    // A chat runs the agent's published version; the ui harness approves publish requests on its own.
    const version = (await granted.json()).data.version;
    await json(await fetch(`${agentsUrl}/v1/agents/${agent.id}/publish-requests`, { method: 'POST', headers: J, body: JSON.stringify({ version, note: 'uc-057' }) }));
    // James asks for the write in chat; the scripted model calls it, and the call is held for approval.
    const thread = (await json(await fetch(`${agentsUrl}/chat/threads`, { method: 'POST', headers: J, body: JSON.stringify({ agentId: agent.id, kbIds: [] }) }))).id;
    const sent = await fetch(`${agentsUrl}/chat/threads/${thread}/messages`, { method: 'POST', headers: { ...J, Accept: 'text/event-stream' }, body: JSON.stringify({ content: `call ${WRITE} ${JSON.stringify({ accountId: 'CHQ-2219' })}` }) });
    const held = /"kind":\s*"approval"/.test(await sent.text());
    check('the chat write is held for approval', held);

    const listed = (await json(await fetch(`${agentsUrl}/reviews?page=1&pageSize=50&view=open`, { headers: as(await tokenFor('m.okafor@northfieldbank.com'), 'team_ops') }))).data.find((r) => r.origin?.kind === 'chat' && r.origin.threadId === thread);
    check('the reviews API lists it as a chat hold with its thread', !!listed && listed.title.includes(WRITE), listed ?? null);

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('m.okafor@northfieldbank.com');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      await page.goto(`${consoleUrl}/reviews`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const row = page.getByRole('row', { name: new RegExp(WRITE) }).first();
      await row.waitFor({ timeout: 120_000 });
      // The source column (`Chat with <agent>`) is hidden by default since lists show five columns; the badge stays.
      check('Reviews shows the hold marked "From chat"', (await row.getByTestId('review-from-chat').count()) === 1);
      // The quick view, by its link as the list opens it.
      await page.goto(`${consoleUrl}/reviews?review=${thread}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      // The showcase run found the card empty and no word of who decides: it says what approving does, by the
      // operation's description, and names the team that decides (the thread's, as the write names no approving team).
      const sheet = page.getByTestId('review-sheet');
      await sheet.getByTestId('task-decide').waitFor({ timeout: 60_000 });
      const card = (await sheet.getByTestId('task-decide').innerText()).replace(/\s+/g, ' ');
      check('the "If you approve" card says what approving does', /If you approve/.test(card) && card.includes('Place a hold'), card.slice(0, 300));
      const decides = (await sheet.getByTestId('review-deciding-team').innerText().catch(() => '')).trim();
      check('the review names the team that decides it, by name', decides === 'Operations decides', decides);
      const link = page.getByTestId('review-open-conversation');
      check('the review links to its conversation', (await link.getAttribute('href')) === `/chat/${thread}`);
      const decided = page.waitForResponse((r) => r.request().method() === 'POST' && /\/reviews\/[^/]+\/decision$/.test(r.url()), { timeout: 60_000 });
      // The review opens in a side sheet; its Approve sends the decision.
      await page.getByRole('dialog').getByRole('button', { name: /^Approve/ }).click();
      const res = await decided;
      check('Maya approves it from Reviews', res.status() === 200, res.status());
      await new Promise((r) => setTimeout(r, 3000));
      const rows = (await json(await fetch(`${tools}/v1/executions?tool=${WRITE}`, { headers: J }))).data;
      check('the held write runs once at the gateway', rows.filter((x) => x.status === 'ok').length === 1, rows.map((x) => [x.decision, x.status]));
      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: { bank: true, gateway: true } },
);

finish();
