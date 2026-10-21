// uc-089 an agent shows a table and a figure in chat with no tool behind them, ui layer:
// docs/usecases/console/agent-presents-widgets.md. Scripted model only; signed in through platform-service. The model
// calls the kernel's built-in present tool, which the chat stream turns into widget parts the console draws.
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
const armed = (p) => (p.catch(() => undefined), p);

const LIMITS = { shape: 'rows', data: [{ account: 'CHQ-2219', daily: 25000, per_wire: 10000 }, { account: 'SAV-0412', daily: 5000, per_wire: 5000 }], hint: { title: 'Wire limits' } };
const DISPUTES = { shape: 'metric', data: { label: 'open disputes', value: 4, delta: -2 } };
const NOT_A_SHAPE = { shape: 'html', data: { body: '<button>Approve</button>' } };

await withUiStack(
  async (consoleUrl) => {
    const J = as(await tokenFor('j.richardson@harborpine.example'), 'team_ops');
    const agent = await json(await fetch(`${agentsUrl}/v1/agents`, { method: 'POST', headers: J, body: JSON.stringify({ name: `Limits desk ${TAG}`, role: 'Explains account limits' }) }));
    // A chat runs only on a live version; publishing goes through a request, which the dev review settles at once.
    const v = agent.version ?? 1;
    await json(await fetch(`${agentsUrl}/v1/agents/${agent.id}/publish-requests`, { method: 'POST', headers: J, body: JSON.stringify({ version: v, note: 'uc-089' }) }));
    const thread = (await json(await fetch(`${agentsUrl}/chat/threads`, { method: 'POST', headers: J, body: JSON.stringify({ agentId: agent.id, kbIds: [] }) }))).id;

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('j.richardson@harborpine.example');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      await page.goto(`${consoleUrl}/chat/${thread}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const box = page.getByRole('textbox', { name: 'Message' });
      await box.waitFor({ timeout: 120_000 });

      const ask = async (args) => {
        await box.fill(`call present ${JSON.stringify(args)}`);
        const sent = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 }));
        await page.getByRole('button', { name: 'Send', exact: true }).click();
        const res = await sent;
        await Promise.race([res?.finished().catch(() => undefined), new Promise((r) => setTimeout(r, 60_000))]);
      };
      const widget = (shape) => page.locator(`[data-testid="widget"][data-shape="${shape}"]`);

      await ask(LIMITS);
      await widget('rows').first().waitFor({ timeout: 60_000 }).catch(() => undefined);
      const table = widget('rows').first();
      const cols = (await table.getByRole('columnheader').allInnerTexts().catch(() => [])).join('|');
      const rows = await table.locator('tbody tr').count();
      check('the agent shows the two accounts as a titled table', (await table.getAttribute('aria-label')) === 'Wire limits' && rows === 2 && cols === 'account|daily|per_wire', { cols, rows });

      await ask(DISPUTES);
      await widget('metric').first().waitFor({ timeout: 60_000 }).catch(() => undefined);
      const stat = widget('metric').first();
      check('the agent shows the open disputes figure as a stat card', (await stat.getAttribute('data-renderer')) === 'stat' && (await stat.getByText('open disputes').count()) === 1, await stat.innerText().catch(() => ''));

      await ask(NOT_A_SHAPE);
      await page.waitForTimeout(1500);
      check('a shape present does not allow draws nothing: the model cannot hand the person its own UI', (await page.getByTestId('widget').count()) === 2 && (await page.getByRole('button', { name: 'Approve' }).count()) === 0, { widgets: await page.getByTestId('widget').count() });

      await page.reload({ waitUntil: 'domcontentloaded' });
      await box.waitFor({ timeout: 120_000 });
      await widget('metric').first().waitFor({ timeout: 60_000 }).catch(() => undefined);
      check('after a reload the thread draws the same two widgets from the stored parts', (await widget('rows').count()) === 1 && (await widget('metric').count()) === 1);

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);

finish();
