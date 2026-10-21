// uc-105 a Security admin sets where each purpose stores its files and with which credential, ui layer:
// docs/usecases/console/storage-settings-per-purpose.md. Signed in through platform-service as Sam (admin on
// team_security), against files-service. The credential's value never comes back; a chat attachment uploaded after the
// save lands in the chat target; a target that fails its test is refused naming the purpose and the version stays.
import { FILES_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const files = `http://127.0.0.1:${FILES_PORT}`;
const SAM = 's.adeyemi@harborpine.example';
const SECRET = `uc105-secret-${Math.random().toString(36).slice(2, 10)}`;
const PDF = Buffer.from('%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj << /Type /Catalog >> endobj\ntrailer\n%%EOF\n', 'latin1');
const armed = (p) => (p.catch(() => undefined), p);
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;

async function choose(page, scope, label, option) {
  await scope.getByLabel(label, { exact: true }).click();
  await page.getByRole('option', { name: option, exact: true }).click();
}

await withUiStack(
  async (consoleUrl) => {
    const S = { Authorization: `Bearer ${await tokenFor(SAM)}`, 'X-Team-Id': 'team_security' };
    const browser = await chromium.launch();
    try {
      const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
      const errors = [];
      const bodies = [];
      page.on('pageerror', (e) => errors.push(e.message));
      page.on('response', async (r) => r.url().includes('/v1/settings/storage') && bodies.push(await r.text().catch(() => '')));
      await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByLabel('Email').fill(SAM);
      await page.getByLabel('Password').fill('northfield-demo');
      await page.getByRole('button', { name: /^Sign in/ }).first().click();
      await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
      await page.goto(`${consoleUrl}/settings/storage`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await page.getByTestId('storage-settings').waitFor({ timeout: 120_000 });
      check('the page opens on files-service with nothing saved yet', /Not saved yet/.test(await page.getByTestId('storage-version').innerText()));

      // A named credential: saved once, then only its name is ever shown or returned.
      await page.getByTestId('credential-add').click();
      const dialog = page.getByRole('dialog');
      await dialog.getByLabel('Name').fill('BANK_S3');
      await dialog.getByLabel('Access key ID').fill('AKIAUC105EXAMPLE');
      await dialog.getByLabel('Secret access key').fill(SECRET);
      await dialog.getByTestId('credential-save').click();
      await page.getByTestId('storage-credentials').getByText('BANK_S3').waitFor({ timeout: 30_000 });
      await dialog.waitFor({ state: 'hidden', timeout: 15_000 }).catch(() => undefined);
      const leaks = { response: bodies.some((b) => b.includes(SECRET)), page: (await page.content()).includes(SECRET) };
      const listed = await (await fetch(`${files}/v1/settings/storage/credentials`, { headers: S })).text();
      check('the credential is listed by name, and its value is in no response and not on the page', !leaks.response && !leaks.page && !listed.includes(SECRET) && listed.includes('BANK_S3'), { leaks, listed: listed.slice(0, 200) });

      // A default target and a chat target, both on the files service's disk; saved with the Save button.
      await page.getByTestId('target-default-add').click();
      await page.getByTestId('target-add').click();
      await page.getByRole('menuitem', { name: 'Chat attachment', exact: true }).click();
      const chat = page.getByTestId('storage-target-chat_attachment');
      await chat.getByLabel('Folder').fill('chat-store');
      const saved = armed(page.waitForResponse((r) => r.request().method() === 'PUT' && r.url().endsWith('/v1/settings/storage'), { timeout: 60_000 }));
      await page.getByTestId('storage-save').click();
      const savedStatus = (await saved)?.status();
      await page.getByTestId('storage-version').getByText(/Version 1/).waitFor({ timeout: 30_000 }).catch(() => undefined);
      check('Save writes version 1', savedStatus === 200 && /Version 1/.test(await page.getByTestId('storage-version').innerText()), savedStatus);

      // The scanning mode reads as a sentence, and the connection test draws its steps as a StepList.
      const page_text = await page.getByTestId('storage-settings').innerText();
      check('the scanning mode is a sentence, not the wire value', /Files are (not )?scanned/.test(page_text) && !/Scanning is (hook|inline|off)/.test(page_text), page_text.slice(0, 200));
      await page.getByRole('button', { name: 'Test', exact: true }).first().click();
      const steps = page.getByTestId('storage-test-result').first().getByTestId('step-list');
      await steps.waitFor({ timeout: 30_000 }).catch(() => undefined);
      const states = await steps.locator('[data-state]').evaluateAll((els) => els.map((e) => e.getAttribute('data-state')).filter((x) => ['pending', 'running', 'done', 'failed'].includes(x))).catch(() => []);
      check('the connection test draws a StepList with every step done', states.length >= 3 && states.every((x) => x === 'done'), states);

      // A chat attachment uploaded now lands in the chat target.
      const ticket = (await (await fetch(`${files}/v1/files/uploads`, { method: 'POST', headers: { ...S, 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'statement.pdf', size: PDF.length, mime: 'application/pdf', purpose: 'chat_attachment' }) })).json()).data;
      await fetch(ticket.uploadUrl.startsWith('http') ? ticket.uploadUrl : `${files}${ticket.uploadUrl}`, { method: 'PUT', headers: { ...S, ...ticket.headers }, body: PDF });
      const done = (await (await fetch(`${files}/v1/files/uploads/${ticket.fileId}/complete`, { method: 'POST', headers: S })).json()).data;
      check('a chat attachment uploaded after the save is stored in the chat target', done?.file?.storage?.container === 'chat-store', done?.file?.storage ?? done);

      // A target that cannot be reached is refused naming the purpose; the saved version stays.
      await choose(page, chat, 'Backend', 'Amazon S3 or S3-compatible');
      await chat.getByLabel('Bucket').fill('bank-chat');
      await choose(page, chat, 'Credential', 'BANK_S3');
      await chat.getByLabel('Endpoint').fill('http://127.0.0.1:9');
      const refused = armed(page.waitForResponse((r) => r.request().method() === 'PUT' && r.url().endsWith('/v1/settings/storage'), { timeout: 60_000 }));
      await page.getByTestId('storage-save').click();
      const refusal = await refused;
      const shown = await page.getByTestId('storage-target-error').innerText({ timeout: 30_000 }).catch(() => '');
      const after = (await (await fetch(`${files}/v1/settings/storage`, { headers: S })).json()).data;
      check('a target that fails its test is refused naming the purpose, and the saved version stays 1', refusal?.status() === 422 && /chat_attachment/.test(shown) && after.version === 1 && after.document.targets.find((t) => t.purpose === 'chat_attachment')?.backend === 'local', { status: refusal?.status(), shown, version: after.version });

      // A credentials list that fails to load says so; it does not read as "No credentials yet".
      const creds = '**/v1/settings/storage/credentials';
      await page.route(creds, (r) => r.abort());
      await page.reload({ waitUntil: 'domcontentloaded' });
      const errorShown = await page.getByTestId('storage-credentials-error').waitFor({ timeout: 60_000 }).then(() => true, () => false);
      const falseEmpty = await page.getByText('No credentials yet').count();
      check('a failed credentials load shows an error, not "No credentials yet"', errorShown && falseEmpty === 0, { errorShown, falseEmpty });
      await page.unroute(creds);
      await page.reload({ waitUntil: 'domcontentloaded' });

      // Removing a credential asks first, naming it; the confirm removes it.
      await page.getByRole('button', { name: 'Remove BANK_S3' }).click({ timeout: 60_000 });
      const dialog2 = page.getByTestId('delete-credential-dialog');
      const asked = await dialog2.waitFor({ timeout: 15_000 }).then(() => true, () => false);
      const stillListed = (await (await fetch(`${files}/v1/settings/storage/credentials`, { headers: S })).text()).includes('BANK_S3');
      await dialog2.getByTestId('delete-credential-confirm-btn').click();
      await page.getByTestId('storage-credentials').getByText('BANK_S3').waitFor({ state: 'detached', timeout: 30_000 }).catch(() => undefined);
      const gone = !(await (await fetch(`${files}/v1/settings/storage/credentials`, { headers: S })).text()).includes('BANK_S3');
      check('removing a credential asks first, and the confirm removes it', asked && stillListed && gone, { asked, stillListed, gone });

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
