// uc-058 another person's chat stays private, ui layer: docs/usecases/console/chat-read-only-for-others.md.
// Scripted model only; signed in through platform-service. James chats with an agent; Maya, a teammate following a link
// to that thread, gets 404 and sees none of it, since chat reads are owner only (owner decision, c7ebccb); James can type.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agentsUrl = `http://127.0.0.1:${AGENTS_PORT}`;
const TAG = Math.random().toString(36).slice(2, 6);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const as = (token, team) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
const json = async (r) => {
  const body = await r.json();
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};

await withUiStack(
  async (consoleUrl) => {
    // James's chat with a new agent, one message long.
    const J = as(await tokenFor('j.richardson@northfieldbank.com'), 'team_ops');
    const agent = await json(await fetch(`${agentsUrl}/v1/agents`, { method: 'POST', headers: J, body: JSON.stringify({ name: `Helper ${TAG}`, role: 'Answers questions' }) }));
    await json(await fetch(`${agentsUrl}/v1/agents/${agent.id}/publish-requests`, { method: 'POST', headers: J, body: JSON.stringify({ version: agent.version, note: 'uc-058' }) }));
    const thread = (await json(await fetch(`${agentsUrl}/chat/threads`, { method: 'POST', headers: J, body: JSON.stringify({ agentId: agent.id, kbIds: [] }) }))).id;
    await fetch(`${agentsUrl}/chat/threads/${thread}/messages`, { method: 'POST', headers: { ...J, Accept: 'text/event-stream' }, body: JSON.stringify({ content: `Hello from James ${TAG}` }) }).then((r) => r.text());

    const browser = await chromium.launch();
    try {
      const errors = [];
      const open = async (email, owner) => {
        const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
        page.on('pageerror', (e) => errors.push(e.message));
        await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.getByLabel('Email').fill(email);
        await page.getByLabel('Password').fill('northfield-demo');
        await page.getByRole('button', { name: /^Sign in/ }).first().click();
        await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
        await page.goto(`${consoleUrl}/chat/${thread}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        if (owner) await page.getByText(`Hello from James ${TAG}`).first().waitFor({ timeout: 120_000 });
        else await page.waitForLoadState('networkidle', { timeout: 60_000 }).catch(() => undefined);
        await page.waitForTimeout(800);
        return page;
      };

      const M = as(await tokenFor('m.okafor@northfieldbank.com'), 'team_ops');
      const mayaApi = (await fetch(`${agentsUrl}/chat/threads/${thread}`, { headers: M })).status;
      const maya = await open('m.okafor@northfieldbank.com', false);
      const mayaReads = await maya.getByText(`Hello from James ${TAG}`).count();
      check("a teammate gets 404 on the owner's chat and sees none of it", mayaApi === 404 && mayaReads === 0, { mayaApi, mayaReads });

      const james = await open('j.richardson@northfieldbank.com', true);
      const jamesBox = await james.locator('textarea').count();
      check('the owner reads the chat and has the message box', jamesBox === 1, { jamesBox });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
