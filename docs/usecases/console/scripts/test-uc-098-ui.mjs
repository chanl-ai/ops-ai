// uc-098 a builder pages and searches a growing list on the server, ui layer:
// docs/usecases/console/lists-page-on-the-server.md. Signed in through platform-service.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agentsUrl = `http://127.0.0.1:${AGENTS_PORT}`;
const TAG = Math.random().toString(36).slice(2, 6);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;

await withUiStack(
  async (consoleUrl) => {
    const J = { Authorization: `Bearer ${await tokenFor('j.richardson@northfieldbank.com')}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
    for (let i = 0; i < 12; i++) {
      const r = await fetch(`${agentsUrl}/v1/guardrails`, { method: 'POST', headers: J, body: JSON.stringify({ name: `Rule ${TAG} ${String(i).padStart(2, '0')}`, topics: [`topic-${TAG}-${i}`], message: 'Not here.' }) });
      if (r.status !== 201) throw new Error(`setup: creating a guardrail answered ${r.status}: ${await r.text()}`);
    }
    const total = (await (await fetch(`${agentsUrl}/v1/guardrails?page=1&pageSize=10`, { headers: J })).json()).data.pagination.total;

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      const asked = [];
      page.on('request', (r) => r.url().includes(`:${AGENTS_PORT}/v1/guardrails?`) && asked.push(new URL(r.url()).searchParams));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('j.richardson@northfieldbank.com');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      // Step 1: page 1 of the API's total.
      await page.goto(`${consoleUrl}/guardrails`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const rows = page.locator('table tbody tr');
      await page.getByText(`Page 1 of ${Math.ceil(total / 10)}`).waitFor({ timeout: 120_000 }).catch(() => undefined);
      check('page 1 shows ten rows and the total from the API', (await rows.count()) === 10 && (await page.getByText(`${total} rows`).count()) > 0 && asked.some((q) => q.get('page') === '1'), { rows: await rows.count(), total, asked: asked.map(String) });

      // Step 2: the next page is asked of the server.
      const firstOnPage1 = await rows.first().innerText();
      await page.getByRole('button', { name: 'Go to next page' }).click();
      await page.getByText(`Page 2 of ${Math.ceil(total / 10)}`).waitFor({ timeout: 30_000 }).catch(() => undefined);
      await page.waitForFunction((t) => document.querySelector('table tbody tr')?.textContent?.replace(/\s+/g, '') !== t && !document.querySelector('[aria-busy="true"]'), firstOnPage1.replace(/\s+/g, ''), { timeout: 30_000 }).catch(() => undefined);
      await page.waitForTimeout(500);
      const second = await rows.count();
      check('page 2 asks the server and shows the remaining rows', asked.some((q) => q.get('page') === '2') && second === Math.min(10, total - 10), { second, total, texts: (await rows.allInnerTexts()).map((t) => t.slice(0, 60)) });

      // Step 3: a search goes to the server and returns to page 1.
      await page.getByPlaceholder('Search names or owners…').fill(`Rule ${TAG} 07`);
      await page.getByText('1 row').first().waitFor({ timeout: 30_000 }).catch(() => undefined);
      check('a search is answered by the server on page 1 with its own total', asked.some((q) => q.get('search') === `Rule ${TAG} 07` && q.get('page') === '1') && (await rows.count()) === 1, { rows: await rows.count(), asked: asked.map(String).slice(-2) });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);

finish();
