// uc-116 a builder issues and revokes the mint key a bank's server starts widget sessions with, ui layer:
// docs/usecases/console/widget-mint-keys.md. Signed in through platform-service. James creates a mint key from the
// embed's row, the secret is shown once, the bank's server mints a session with it, and after James revokes it the
// same key mints nothing. Ravi, a viewer, sees no key controls.
import { AGENTS_PORT, PLATFORM_PORT, check, chromium, finish, withUiStack } from '@ops-ai/usecase-runner/harness';

const agents = `http://127.0.0.1:${AGENTS_PORT}`;
const INTRANET = 'http://127.0.0.1:4611';
const NAME = `Teller Desk ${Math.random().toString(36).slice(2, 6)}`;
const JAMES = 'j.richardson@northfieldbank.com';
const RAVI = 'r.menon@northfieldbank.com';
const tokenFor = async (email) => (await (await fetch(`http://127.0.0.1:${PLATFORM_PORT}/v1/auth/sign-in`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password: 'northfield-demo' }) })).json()).data.token;
const as = (token) => ({ Authorization: `Bearer ${token}`, 'X-Team-Id': 'team_ops', 'Content-Type': 'application/json' });

async function signIn(browser, consoleUrl, email) {
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
  await page.goto(`${consoleUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('northfield-demo');
  await page.getByRole('button', { name: /^Sign in/ }).first().click();
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 60_000 });
  return page;
}

const mint = (dep, secret) =>
  fetch(`${agents}/v1/widget-deployments/${dep}/sessions`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${secret}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: 'teller@bank.example', name: 'Teller', origin: INTRANET }),
  });

await withUiStack(
  async (consoleUrl) => {
    const J = as(await tokenFor(JAMES));
    const made = await (await fetch(`${agents}/v1/agents`, { method: 'POST', headers: J, body: JSON.stringify({ name: NAME, role: 'Answers teller questions' }) })).json();
    if (!made.data) throw new Error(`setup: create agent: ${JSON.stringify(made).slice(0, 300)}`);
    const pub = await fetch(`${agents}/v1/agents/${made.data.id}/publish-requests`, { method: 'POST', headers: J, body: JSON.stringify({ version: made.data.version, note: 'first' }) });
    if (!pub.ok) throw new Error(`setup: publish answered ${pub.status}: ${await pub.text()}`);
    const dep = await (await fetch(`${agents}/v1/widget-deployments`, { method: 'POST', headers: J, body: JSON.stringify({ name: 'Teller intranet', agentId: made.data.id, origins: [INTRANET] }) })).json();
    if (!dep.data) throw new Error(`setup: create embed: ${JSON.stringify(dep).slice(0, 300)}`);

    const browser = await chromium.launch();
    const errors = [];
    try {
      // 1. James opens the embed's keys and presses Create key with no name, then with one.
      const james = await signIn(browser, consoleUrl, JAMES);
      james.on('pageerror', (e) => errors.push(`console: ${e.message}`));
      await james.goto(`${consoleUrl}/agents/${made.data.id}?tab=channels`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await james.getByTestId('widget-keys-open').click({ timeout: 120_000 });
      const dialog = james.getByRole('dialog', { name: 'Mint keys for Teller intranet' });
      await dialog.getByText('No keys yet.').waitFor({ timeout: 30_000 });
      await dialog.getByTestId('widget-key-create').click();
      const nameError = await dialog.getByText('Name the server that will use it, like Intranet server.').isVisible({ timeout: 10_000 }).catch(() => false);
      check('1 a key with no name is refused under its field', nameError && (await dialog.locator('#widget-key-name').getAttribute('aria-invalid')) === 'true');
      await dialog.locator('#widget-key-name').fill('Intranet server');
      const created = james.waitForResponse((r) => r.request().method() === 'POST' && r.url().endsWith(`/widget-deployments/${dep.data.id}/keys`), { timeout: 30_000 });
      await dialog.getByTestId('widget-key-create').click();
      const createdStatus = (await created).status();
      const secret = (await dialog.getByTestId('widget-key-secret').locator('code').textContent({ timeout: 15_000 }))?.trim() ?? '';
      check('1 the key is created and its secret shown once, naming the tenant and key', createdStatus === 201 && /^wk\.[^.]+\.wkk_[^.]+\.[^.]+$/.test(secret), { createdStatus, secret: secret.replace(/\.[^.]+$/, '.…') });
      await dialog.getByTestId('widget-keys').getByText('Intranet server').waitFor({ timeout: 15_000 });
      check('1 the list names the key and says it was never used', await dialog.getByTestId('widget-keys').getByText('Never').isVisible());

      // 2. The bank's server mints a session with it; the list then shows it used.
      const minted = await mint(dep.data.id, secret);
      check('2 the server mints a session with the key', minted.status === 201, minted.status);
      await dialog.getByRole('button', { name: 'Done' }).click();
      await james.getByTestId('widget-keys-open').click();
      const reopened = james.getByRole('dialog', { name: 'Mint keys for Teller intranet' });
      await reopened.getByTestId('widget-keys').waitFor({ timeout: 15_000 });
      check('2 a reopened dialog does not show the secret again', (await reopened.getByTestId('widget-key-secret').count()) === 0 && !(await james.content()).includes(secret));
      const used = await reopened.getByTestId('widget-keys').getByText('Never').waitFor({ state: 'detached', timeout: 15_000 }).then(() => true, () => false);
      check('2 the key reads as used', used);

      // 3. James revokes it, cancelling once; the same key then mints nothing.
      await reopened.getByRole('button', { name: 'Revoke' }).click();
      const confirm = james.getByRole('alertdialog').or(james.getByRole('dialog', { name: 'Revoke Intranet server' }));
      await confirm.getByRole('button', { name: 'Cancel' }).click();
      check('3 cancelling leaves the key working', (await mint(dep.data.id, secret)).status === 201);
      await reopened.getByRole('button', { name: 'Revoke' }).click();
      const revoked = james.waitForResponse((r) => r.request().method() === 'POST' && r.url().includes('/revoke'), { timeout: 30_000 });
      await confirm.getByRole('button', { name: 'Revoke' }).click();
      check('3 the revoke answers 200', (await revoked).status() === 200);
      await reopened.getByText('Revoked').waitFor({ timeout: 15_000 });
      const after = await mint(dep.data.id, secret);
      const code = (await after.json()).error?.code;
      check('3 the revoked key mints nothing', after.status === 401 && code === 'widget_key_invalid', { status: after.status, code });

      // 4. Ravi, a viewer, sees the embed and no key controls.
      const ravi = await signIn(browser, consoleUrl, RAVI);
      ravi.on('pageerror', (e) => errors.push(`console (viewer): ${e.message}`));
      await ravi.goto(`${consoleUrl}/agents/${made.data.id}?tab=channels`, { waitUntil: 'domcontentloaded', timeout: 120_000 });
      await ravi.getByTestId('widget-embeds').waitFor({ timeout: 120_000 });
      check('4 a viewer sees no Mint keys button', (await ravi.getByTestId('widget-keys-open').count()) === 0);

      check('no page errors', errors.length === 0, errors);
    } finally {
      await browser.close();
    }
  },
  { platform: true },
);

finish();
