// uc-110 a Security admin adds a secret and a host with Enter, and Cancel sends nothing, ui layer:
// docs/usecases/console/dialogs-save-on-enter.md. Signed in through platform-service; secrets and egress on tools-service.
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

import { ROOT, TOOLS_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const TAG = Math.random().toString(36).slice(2, 6);
const HOST = `ledger-${TAG}.example.com`;
const SECRET = `LEDGER_${TAG.toUpperCase()}`;

await withUiStack(
  async (consoleUrl) => {
    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      page.on('pageerror', (e) => errors.push(e.message));
      const writes = [];
      page.on('request', (r) => r.method() === 'POST' && r.url().includes(`:${TOOLS_PORT}/`) && writes.push(new URL(r.url()).pathname));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill('s.adeyemi@northfieldbank.com');
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      const dialog = page.getByRole('dialog');

      // Step 1: Cancel sends nothing.
      await page.goto(`${consoleUrl}/settings/egress`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByRole('button', { name: 'Add host' }).first().click({ timeout: 120_000 });
      await dialog.getByLabel('Host').fill(HOST);
      await dialog.getByRole('button', { name: 'Cancel' }).click();
      await page.waitForTimeout(800);
      check('Cancel closes Add host and sends no POST', !(await dialog.isVisible()) && !writes.some((p) => p.startsWith('/v1/egress')), writes);

      // Step 2: Enter in the host field adds it.
      await page.getByRole('button', { name: 'Add host' }).first().click();
      await dialog.getByLabel('Host').fill(HOST);
      await dialog.getByLabel('Host').press('Enter');
      await page.getByRole('cell', { name: HOST }).waitFor({ timeout: 30_000 }).catch(() => undefined);
      check('Enter in Add host lists the host', (await page.getByRole('cell', { name: HOST }).count()) === 1 && writes.includes('/v1/egress/hosts'), writes);

      // Step 3: Enter in the secret's value field saves it.
      await page.goto(`${consoleUrl}/settings/secrets`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByRole('button', { name: 'Add secret' }).first().click({ timeout: 120_000 });
      await dialog.getByLabel('Name').fill(SECRET);
      await dialog.getByLabel('Value').fill('s3cret');
      await dialog.getByLabel('Value').press('Enter');
      await page.getByRole('cell', { name: SECRET }).waitFor({ timeout: 30_000 }).catch(() => undefined);
      check('Enter in Add secret lists the secret', (await page.getByRole('cell', { name: SECRET }).count()) === 1 && writes.includes('/v1/secrets'), writes);

      check('no page errors', errors.length === 0, errors);
      const dir = join(ROOT, '.codeloop/evidence/113');
      mkdirSync(dir, { recursive: true });
      writeFileSync(join(dir, 'uc-110-tools-posts.json'), `${JSON.stringify(writes, null, 2)}\n`);
    } finally {
      await browser.close();
    }
  },
  { platform: true, tools: {} },
);

finish();
