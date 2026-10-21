// uc-078 the advisor's helper answers about a customer and compares products, ui layer:
// docs/usecases/console/advisor-helper-answers.md. Needs withUiStack's `demo` option: kb-service and models-service with
// the fake OpenAI (its rules in .run/fake-openai/script.json) on the run's database, with the demo seeds run against
// the run's ports (ag_advisor wired to Retail products and the bank reads). Signed in through platform-service as James.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const JAMES = 'j.richardson@harborpine.example';
const PASSWORD = 'northfield-demo';
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: PASSWORD }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });
// A wait armed before a click must not reject unhandled if the script fails first; that crash skips harness cleanup.
const armed = (p) => (p.catch(() => undefined), p);

await withUiStack(
  async (consoleUrl) => {
    const J = as(await tokenFor(JAMES));
    const created = await (await fetch(`${agents}/chat/threads`, { method: 'POST', headers: J, body: JSON.stringify({ agentId: 'ag_advisor', kbIds: [] }) })).json();
    if (!created.data) throw new Error(`setup: thread create answered ${JSON.stringify(created).slice(0, 300)}`);

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(JAMES);
      await page.getByLabel('Password').fill(PASSWORD);
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      await page.goto(`${consoleUrl}/chat/${created.data.id}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const box = page.getByRole('textbox', { name: 'Message' });
      await box.waitFor({ timeout: 120_000 });
      const send = async (text) => {
        await box.fill(text);
        const sent = armed(page.waitForResponse((r) => r.request().method() === 'POST' && /\/chat\/threads\/[^/]+\/messages$/.test(r.url()), { timeout: 120_000 }));
        await page.getByRole('button', { name: 'Send', exact: true }).click();
        const res = await sent;
        await Promise.race([res?.finished().catch(() => undefined), new Promise((r) => setTimeout(r, 60_000))]);
      };
      const widget = (shape) => page.locator(`[data-testid="widget"][data-shape="${shape}"]`);

      // US1: the customer's record and accounts, from the fake bank, drawn by shape.
      await send('What does Priya Natarajan have with us?');
      const summary = await page.getByText(/Priya Natarajan holds one .* account/).last().waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const record = widget('record').last();
      const accounts = widget('rows').last();
      const recordShown = (await record.getAttribute('data-renderer').catch(() => null)) === 'fields' && (await record.getByText(/CUS-1002/).count()) > 0;
      const accountsShown = (await accounts.getAttribute('data-renderer').catch(() => null)) === 'table' && (await accounts.getByText('BUS-7781').count()) > 0;
      check('her record draws as fields and her accounts as a table, with the summary', summary && recordShown && accountsShown, { summary, recordShown, accountsShown, widgets: await page.locator('[data-testid="widget"]').evaluateAll((w) => w.map((e) => `${e.getAttribute('data-shape')}:${e.getAttribute('data-renderer')}:${e.textContent.slice(0, 80)}`)) });

      // US2: the comparison cites the product sheet by page.
      await send('Compare Savings Plus and Money Market for her');
      const compared = await page.getByText(/Savings Plus suits a customer saving for a goal/).last().waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const marker = page.getByRole('button', { name: /^Citation 1: .*Retail Product Sheet/ }).last();
      await marker.click({ timeout: 15_000 }).catch(() => undefined);
      const where = await page.getByRole('dialog').innerText().catch(() => '');
      check('the comparison cites the Retail Product Sheet with its page', compared && /Retail Product Sheet/.test(where) && /p\.\s?4/.test(where), { compared, where: where.slice(0, 200) });
      await page.keyboard.press('Escape');

      // US2's table: the model returns the comparison as rows through the structured-result tool (c-055 T021).
      const table = await widget('rows').filter({ hasText: /Money Market/ }).count();
      check('the comparison also shows as a table widget', table === 1, { table });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, demo: true },
);

finish();
