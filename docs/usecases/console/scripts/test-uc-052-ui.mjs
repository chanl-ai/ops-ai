// uc-052 access is Read or Write in the console, ui layer: docs/usecases/console/access-is-read-or-write.md.
// Headless Chromium, signed in through platform-service, against tools-service's seeded modules.
import { PLATFORM_PORT, TOOLS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const TAG = Math.random().toString(36).slice(2, 6);
const HOST = `payments-${TAG}.bank.example`;
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;

const PAGES = ['/tools', '/access', '/logs/tool-calls', '/agents', '/workflows', '/reviews'];

await withUiStack(
  async (consoleUrl) => {
    // James's module with a read and a write, made through tools-service as a builder would.
    const J = { Authorization: `Bearer ${await tokenFor('j.richardson@harborpine.example')}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
    // Egress writes are Security-admin only, so the host is added as Sam; every setup call is checked.
    const S = { Authorization: `Bearer ${await tokenFor('s.adeyemi@harborpine.example')}`, 'X-Team-Id': 'team_security', 'Content-Type': 'application/json' };
    const setup = async (r) => {
      if (!r.ok) throw new Error(`setup: ${r.url} answered ${r.status}: ${(await r.text()).slice(0, 300)}`);
      return r;
    };
    await setup(await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: S, body: JSON.stringify({ value: HOST, note: 'uc-052' }) }));
    const made = await (await setup(await fetch(`${tools}/v1/tool-modules/blank`, { method: 'POST', headers: J, body: JSON.stringify({ displayName: `Payments ${TAG}`, name: `uc052-${TAG}`, type: 'http' }) }))).json();
    const moduleId = made.data.id;
    for (const [name, access, method] of [[`get_payment_${TAG}`, 'read', 'GET'], [`create_payment_${TAG}`, 'write', 'POST']])
      await setup(await fetch(`${tools}/v1/tool-modules/${moduleId}/operations`, { method: 'POST', headers: J, body: JSON.stringify({ name, description: '', access, method, url: `https://${HOST}/v1/payments` }) }));
    // The write's approval policy asks for two approvers (c-048 T005).
    const detail = (await (await fetch(`${tools}/v1/tool-modules/${moduleId}`, { headers: J })).json()).data;
    const write = detail.operations.find((o) => o.access === 'write');
    await setup(await fetch(`${tools}/v1/tool-modules/${moduleId}/operations/${write.id}`, { method: 'PATCH', headers: J, body: JSON.stringify({ approvers: 2 }) }));
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

      const seen = [];
      for (const path of PAGES) {
        await page.goto(`${consoleUrl}${path}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
        await page.locator('main').first().waitFor({ timeout: 120_000 });
        await page.waitForTimeout(2500);
        if ((await page.getByText(/Moves money|money movement/i).count()) > 0) seen.push(path);
      }
      check('no page offers or shows a "Moves money" class', seen.length === 0, seen);

      await page.goto(`${consoleUrl}/tools`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByRole('button', { name: /^Access/ }).first().click({ timeout: 60_000 });
      const filter = (await page.getByRole('option').allInnerTexts()).map((t) => t.replace(/\s*\d+\s*$/, '').trim());
      await page.keyboard.press('Escape');
      check('the module list filters access by Read and Write only', JSON.stringify(filter) === '["Read","Write"]', filter);

      await page.goto(`${consoleUrl}/tools/${moduleId}`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const add = page.getByTestId('ops-add');
      await add.waitFor({ timeout: 120_000 });
      const badges = (await page.locator('table').first().innerText()).match(/\b(Read|Write)\b/g) ?? [];
      const onModule = (await page.getByText(/Moves money|money movement/i).count()) === 0;
      await add.click();
      await page.locator('#http-access').click({ timeout: 30_000 });
      const classes = (await page.getByRole('option').allInnerTexts()).map((t) => t.trim());
      await page.keyboard.press('Escape');
      check("a module's page shows no money class, and a new operation's access is Read or Write", onModule && badges.includes('Read') && badges.includes('Write') && JSON.stringify(classes) === '["Read","Write"]', { onModule, badges, classes });

      const supervised = (await page.locator('table').first().innerText()).includes('Two approvals');
      check('a write whose policy needs two approvals says so on the module page', supervised);

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);

finish();
