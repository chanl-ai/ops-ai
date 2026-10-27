// uc-061 tool results draw as widgets by shape through the real chat stream, ui layer:
// docs/usecases/console/widgets-through-chat.md. Scripted model only; signed in through platform-service. James imports
// the fake bank's insights spec (one operation per shape, one declaring x-ops-shape, one that fits no shape), grants
// them to an agent and asks for each in chat; agents-service shapes each answer and the console draws it.
import { AGENTS_PORT, PLATFORM_PORT, TOOLS_PORT, approveToolReview, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const agentsUrl = `http://127.0.0.1:${AGENTS_PORT}`;
const TAG = Math.random().toString(36).slice(2, 6);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const as = (token, team) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': team, 'Content-Type': 'application/json' });
const json = async (r) => {
  const body = await r.json();
  if (body.data === undefined) throw new Error(`${r.url} answered ${r.status}: ${JSON.stringify(body).slice(0, 300)}`);
  return body.data;
};
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);
const ASK = ['get_account', 'list_transactions', 'daily_spend', 'balance_history', 'dispute_summary', 'account_profile', 'statement_lines'];

await withUiStack(
  async (consoleUrl, stack) => {
    const J = as(await tokenFor('j.richardson@harborpine.example'), 'team_ops');
    const N = as(await tokenFor('n.petrov@harborpine.example'), 'team_security');
    // Egress is Security's admin's to change (tools-service callers.security_admin); a refused setup fails here, not as
    // an egress_denied import later.
    const S = as(await tokenFor('s.adeyemi@harborpine.example'), 'team_security');
    for (const [path, value] of [['hosts', stack.bank.host], ['ranges', stack.bank.range]]) {
      const res = await fetch(`${tools}/v1/egress/${path}`, { method: 'POST', headers: S, body: JSON.stringify({ value, note: 'uc-061' }) });
      if (!res.ok) throw new Error(`setup: allowing egress ${path} answered ${res.status}: ${await res.text()}`);
    }
    const source = { kind: 'openapi', specUrl: `https://${stack.bank.host}/v1/openapi-shapes.json` };
    const found = await json(await fetch(`${tools}/v1/tool-modules/discover`, { method: 'POST', headers: J, body: JSON.stringify(source) }));
    const names = found.operations.map((o) => o.name);
    check('discovery finds one read per shape in the insights spec', ASK.every((n) => names.includes(n)), names);
    const made = await json(await fetch(`${tools}/v1/tool-modules`, { method: 'POST', headers: J, body: JSON.stringify({ name: `uc061-insights-${TAG}`, displayName: `Insights ${TAG}`, system: 'Core banking', type: 'openapi', endpoint: '', operations: found.operations, source }) }));
    await json(await fetch(`${tools}/v1/tool-modules/${made.id}/reviews`, { method: 'POST', headers: J, body: JSON.stringify({ note: 'uc-061' }) }));
    await approveToolReview(made.id, N, J);
    await new Promise((r) => setTimeout(r, 31_000)); // agents-service keeps each tenant's tool list for 30 seconds
    const agent = await json(await fetch(`${agentsUrl}/v1/agents`, { method: 'POST', headers: J, body: JSON.stringify({ name: `Insights desk ${TAG}`, role: 'Reads account insights' }) }));
    const granted = await fetch(`${agentsUrl}/v1/agents/${agent.id}`, { method: 'PATCH', headers: J, body: JSON.stringify({ toolIds: ASK }) });
    if (!granted.ok) throw new Error(`setup: granting answered ${granted.status}: ${await granted.text()}`);
    await json(await fetch(`${agentsUrl}/v1/agents/${agent.id}/publish-requests`, { method: 'POST', headers: J, body: JSON.stringify({ version: (await granted.json()).data.version, note: 'uc-061' }) }));
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
      await page.getByRole('textbox', { name: 'Message' }).waitFor({ timeout: 120_000 });

      for (const [i, op] of ASK.entries()) {
        await page.getByRole('textbox', { name: 'Message' }).fill(`call ${op} ${JSON.stringify({ accountId: 'CHQ-2219' })}`);
        const sent = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 }));
        await page.getByRole('button', { name: 'Send', exact: true }).click();
        const res = await sent;
        await Promise.race([res?.finished().catch(() => undefined), new Promise((r) => setTimeout(r, 60_000))]);
        await page.getByText('Here is what I found.').nth(i).waitFor({ timeout: 60_000 }).catch(() => undefined);
      }

      const widget = (shape) => page.locator(`[data-testid="widget"][data-shape="${shape}"]`);
      const drawn = async () => Object.fromEntries(await Promise.all(['record', 'rows', 'series', 'metric'].map(async (s) => [s, await widget(s).evaluateAll((els) => els.map((e) => e.getAttribute('data-renderer')))])));
      const live = await drawn();
      check('each answer streams in as its shape with the default renderer; the declared rows beat an inferred series', JSON.stringify(live) === JSON.stringify({ record: ['fields'], rows: ['table', 'table', 'table'], series: ['line'], metric: ['stat'] }), live);

      const tx = widget('rows').first();
      const titled = (await tx.getAttribute('aria-label')) === 'transactions';
      const paged = (await tx.locator('tbody tr').count()) === 10 && (await tx.getByText('Page 1 of 2').count()) === 1;
      const stat = (await widget('metric').getByText('3 cases').count()) === 1;
      check('the transactions table is titled from its key and paged; the metric shows its value and unit', titled && paged && stat, { titled, paged, stat });

      const profileCard = page.getByTestId('chat-tool-call').filter({ hasText: 'account_profile' });
      const cards = await page.getByTestId('chat-tool-call').count();
      check('an answer that fits no shape stays a tool card with no widget', (await profileCard.count()) === 1 && cards === ASK.length && (await page.getByTestId('widget').count()) === 6, { profile: await profileCard.count(), cards, widgets: await page.getByTestId('widget').count() });

      // 250 lines: agents-service sends the first 200 with hint.truncatedFrom, and the table says what was cut.
      const lines = widget('rows').last();
      const cut = (await lines.getByTestId('widget-truncated').innerText().catch(() => '')).trim();
      check('a result cut at 200 rows says so on its table', cut === 'Showing 200 of 250 rows' && (await lines.getByText('Page 1 of 20').count()) === 1, { cut });

      const spend = widget('series');
      await spend.getByRole('radio', { name: 'Table' }).click();
      const cols = (await spend.getByRole('columnheader').allInnerTexts()).join('|');
      check('the person switches the inferred series to a table keyed by its date', (await spend.getAttribute('data-renderer')) === 'table' && cols === 'date|groceries|transit', cols);

      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.getByRole('textbox', { name: 'Message' }).waitFor({ timeout: 120_000 });
      await widget('metric').waitFor({ timeout: 60_000 }).catch(() => undefined);
      const reloaded = await drawn();
      check('after a reload the thread draws the same widgets from the stored parts', JSON.stringify(reloaded) === JSON.stringify(live), reloaded);

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: { bank: true, gateway: true } },
);

finish();
