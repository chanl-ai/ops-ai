// uc-054 a builder imports a spec with access preset per operation and no connection to pick, ui layer:
// docs/usecases/console/import-presets-access.md. Signed in through platform-service; tools-service reads the fake
// bank's spec over https.
import { PLATFORM_PORT, TOOLS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const tools = `http://127.0.0.1:${TOOLS_PORT}`;
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;

await withUiStack(
  async (consoleUrl, stack) => {
    // An admin allows the bank's host and the private range it serves on.
    const P = { Authorization: `Bearer ${await tokenFor('p.shah@northfieldbank.com')}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' };
    await fetch(`${tools}/v1/egress/hosts`, { method: 'POST', headers: P, body: JSON.stringify({ value: stack.bank.host, note: 'uc-054' }) });
    await fetch(`${tools}/v1/egress/ranges`, { method: 'POST', headers: P, body: JSON.stringify({ value: stack.bank.range, note: 'uc-054' }) });

    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('j.richardson@northfieldbank.com');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      await page.goto(`${consoleUrl}/tools`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('import-operations').click({ timeout: 120_000 });
      const dialog = page.getByRole('dialog', { name: 'Import operations' });
      await dialog.waitFor({ timeout: 30_000 });
      await dialog.getByText('OpenAPI', { exact: false }).first().click();
      check('the import dialog asks for no connection record', (await dialog.getByText('Connection', { exact: true }).count()) === 0 && (await dialog.locator('#mod-conn').count()) === 0);
      await dialog.locator('#spec-url').fill(`https://${stack.bank.host}/v1/openapi-open.json`);
      await dialog.getByRole('button', { name: 'Next' }).click();
      await dialog.getByLabel('Access for get_account').waitFor({ timeout: 60_000 });

      check('a spec with no security scheme shows the no-auth warning', (await dialog.getByText(/declares no API key or bearer security scheme/).count()) === 1);
      const readAccess = (await dialog.getByLabel('Access for get_account').innerText()).trim();
      const writeAccess = (await dialog.getByLabel('Access for place_hold').innerText()).trim();
      const readOn = await dialog.locator('#op-get_account').isChecked();
      const writeOn = await dialog.locator('#op-place_hold').isChecked();
      check('GET comes in as Read and selected; POST as Write and opt-in', readAccess === 'Read' && writeAccess === 'Write' && readOn && !writeOn, { readAccess, writeAccess, readOn, writeOn });

      await dialog.locator('#op-place_hold').click();
      const saved = page.waitForResponse((r) => r.request().method() === 'POST' && /\/v1\/tool-modules$/.test(r.url()), { timeout: 60_000 });
      await dialog.getByRole('button', { name: 'Save draft' }).click();
      const res = await saved;
      const made = res.ok() ? (await res.json()).data : null;
      const access = Object.fromEntries((made?.operations ?? []).map((o) => [o.name, o.access]));
      check('the saved module keeps each confirmed access: get_account read, place_hold write', res.status() === 201 && access.get_account === 'read' && access.place_hold === 'write', { status: res.status(), access });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: { bank: true } },
);

finish();
