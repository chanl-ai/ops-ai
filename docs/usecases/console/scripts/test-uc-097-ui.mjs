// uc-097 a builder saves settings pages and create dialogs with Enter, ui layer:
// docs/usecases/console/forms-save-on-enter.md. Signed in through platform-service.
import { AGENTS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const TAG = Math.random().toString(36).slice(2, 6);

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      const posts = [];
      page.on('request', (r) => r.method() !== 'GET' && r.url().includes(`:${AGENTS_PORT}/`) && posts.push(`${r.method()} ${new URL(r.url()).pathname}`));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('j.richardson@harborpine.example');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });

      // Steps 1-2: the New widget dialog.
      await page.goto(`${consoleUrl}/widgets`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const dialog = page.getByRole('dialog');
      await page.getByTestId('new-widget-button').click({ timeout: 120_000 });
      await dialog.getByLabel('Name').fill(`Limits ${TAG}`);
      await dialog.getByLabel('When the agent uses it').fill('The person asks for limits.');
      await dialog.getByRole('button', { name: 'Cancel' }).click();
      await page.waitForTimeout(800);
      check('Cancel closes the dialog and creates nothing', !(await dialog.isVisible()) && !posts.some((p) => p === 'POST /v1/widgets'), posts);
      await page.getByTestId('new-widget-button').click();
      await dialog.getByLabel('Name').fill(`Limits ${TAG}`);
      await dialog.getByLabel('When the agent uses it').fill('The person asks for limits.');
      await dialog.getByLabel('Name').press('Enter');
      await page.waitForURL((u) => /^\/widgets\/[^/]+$/.test(u.pathname), { timeout: 30_000 }).catch(() => undefined);
      check('Enter in the name field creates the widget and opens its editor', new URL(page.url()).pathname === `/widgets/limits-${TAG}`, page.url());

      // Steps 3-4: the New guardrail dialog; Enter in the topics field adds a topic and saves nothing.
      await page.goto(`${consoleUrl}/guardrails`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('new-guardrail-button').click({ timeout: 120_000 });
      const before = posts.length;
      const hint = (await dialog.getByLabel('Message instead of an answer').getAttribute('placeholder')) ?? '';
      check('the guardrail message placeholder is an example, starting with e.g.', hint.startsWith('e.g. '), hint);
      await dialog.getByLabel('Blocked topics').fill('crypto tips');
      await dialog.getByLabel('Blocked topics').press('Enter');
      await page.waitForTimeout(500);
      check('Enter in the topics field adds the topic and saves nothing', (await dialog.getByText('crypto tips').count()) > 0 && posts.length === before && (await dialog.isVisible()), posts.slice(before));
      await dialog.getByLabel('Name').fill(`No tips ${TAG}`);
      await dialog.getByLabel('Message instead of an answer').fill('I cannot give tips.');
      const created = page.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith('/v1/guardrails'), { timeout: 30_000 }).catch(() => null);
      await dialog.getByLabel('Name').press('Enter');
      const res = await created;
      await dialog.waitFor({ state: 'hidden', timeout: 10_000 }).catch(() => undefined);
      check('Enter in the name field creates the guardrail and closes the dialog', res?.status() === 201 && !(await dialog.isVisible()), res?.status());

      // Step 5: Account is sample data (uc-125): its name field is off, so Enter saves nothing and claims nothing.
      await page.goto(`${consoleUrl}/account`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      const nameField = page.getByLabel('Name');
      await nameField.waitFor({ timeout: 120_000 });
      const off = await nameField.isDisabled();
      await nameField.press('Enter', { timeout: 2_000 }).catch(() => undefined);
      await page.waitForTimeout(500);
      check('Enter on the sample-data account name saves nothing and claims nothing', off && (await page.getByText('Saved your name').count()) === 0, { off });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);

finish();
